#!/usr/bin/env python3
"""canon-lint — the fleet canon's consistency gate (Layer C).

Checks, in the doctrine's words: consistency is a first-class problem.

  1. schema        every CANON.md parses; all required fields; canon == 1;
                   state enum; verified is a real date; name == repo name.
  2. edges         feeds/owed_by acknowledged on BOTH sides when the other
                   side has a CANON.md (A.feeds B  =>  B.owed_by A).
  3. staleness     verified > 30d ago + pushes since => warning;
                   > 90d on Tier-1 => failure. (remote mode only)
  4. coverage      Tier-1 repos without CANON.md => warning, or failure
                   with --enforce-coverage (flip when coverage hits 100%).

Usage:
  python3 fleet-canon/lint.py                 # remote, over tier1.txt
  python3 fleet-canon/lint.py --dir fixtures  # local dirs {dir}/{repo}/CANON.md
  python3 fleet-canon/lint.py --enforce-coverage
  python3 fleet-canon/lint.py --verify-flux   # + FULL 71-paper FLUX fabric gate
  python3 fleet-canon/lint.py --verify-flux --quick  # + 9-cell P0 smoke only

Stdlib only. GITHUB_TOKEN used if set (55+ API calls otherwise squeak under
the anonymous 60/hr budget; the token makes it relaxed).

--verify-flux (P2, see docs/FLUX_CANON_VERIFIER.md — "the canon's own immune
system"): by DEFAULT this runs the full 71-paper fabric gate over the pinned
corpus snapshot: reference-hash drift check, sandboxed fabric verification
under the measured corpus fuel budget, and a full recompute of every
recorded proof certificate. ANY drift — corpus hash mismatch, vm/reference
drift, cert recompute failure, fuel boundary violation — is a lint FAILURE
with the same reporting shape as the drift check above.
--quick selects the old P0 smoke (contract cell + seeded synthetic sample,
no corpus) for hosts that want the cheap vm==reference cross-check without
the fabric cost. When flux_verifier (or its pinned interpreter /
canon_verify.fxu) is absent, lint prints an honest SKIP line and NEVER
fails on that account.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIER1 = os.path.join(ROOT, "fleet-canon", "tier1.txt")

REQUIRED = [
    "canon", "name", "mission", "state", "family", "vessel",
    "born_from", "feeds", "owed_by", "canonical_docs", "ledger", "verified",
]
STATES = {"experimental", "active", "stable", "sunset"}
LEDGERS = {"none", "quilt-wal", "git-log"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_LINES = 24  # 20 fields + fences + slack — the stub stays a stub


def tier1_repos() -> list[str]:
    repos = []
    with open(TIER1, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                repos.append(line)
    return repos


class RateLimited(Exception):
    """Raised when GitHub answers 403/429 — the sweep is INCOMPLETE, not clean."""

    def __init__(self, repo: str, retry_after: str | None = None):
        self.repo = repo
        self.retry_after = retry_after
        hint = f" (Retry-After: {retry_after}s)" if retry_after else ""
        super().__init__(f"rate-limited checking {repo}{hint}")


def _open_checked(req: urllib.request.Request, repo: str):
    """urlopen that converts 403/429 into RateLimited instead of crashing
    the whole sweep — a rate-limited run must report INCOMPLETE, never PASS."""
    try:
        return urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise RateLimited(repo, exc.headers.get("Retry-After"))
        raise


def api(path: str, accept: str = "application/vnd.github+json") -> object:
    repo = path.rstrip("/").rsplit("/", 1)[-1]  # best-effort label for errors
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"
            if os.environ.get("GITHUB_TOKEN") else
            "X-Accept-Anonymous: yes",
            "User-Agent": "fleet-canon-lint",
        },
    )
    with _open_checked(req, repo) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_canon_remote(repo: str) -> str | None:
    for ref in ("HEAD", "canon-stub", "canon-md"):
        req = urllib.request.Request(
            f"https://api.github.com/repos/SuperInstance/{repo}/contents/CANON.md?ref={ref}",
        headers={
            "Accept": "application/vnd.github.raw",
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"
            if os.environ.get("GITHUB_TOKEN") else
            "X-Accept-Anonymous: yes",
            "User-Agent": "fleet-canon-lint",
        },
    )
        try:
            with _open_checked(req, repo) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
    return None


def parse_front_matter(text: str) -> dict[str, object] | str:
    """Minimal front-matter parse. Returns dict or an error string."""
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        return f"stub too long: {len(lines)} lines (max {MAX_LINES}) — it became a document"
    if not lines or lines[0].strip() != "---":
        return "missing opening --- fence"
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return "missing closing --- fence"
    if [l for l in lines[end + 1:] if l.strip()]:
        return "content after front-matter — canon is the handle, not the door"
    out: dict[str, object] = {}
    for line in lines[1:end]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            return f"unparseable line: {line!r}"
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            out[key] = [v.strip().strip("'\"") for v in inner.split(",")] if inner else []
        else:
            out[key] = value.strip("'\"")
    return out


def as_list(value: object) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def verify_flux(sample_size: int, quick: bool = False,
                corpus_path: str | None = None,
                certs_path: str | None = None
                ) -> tuple[list[str], list[str]]:
    """The FLUX canon gate. quick=True → P0 smoke; quick=False (default)
    → the full 71-paper fabric immune system (P2).

    Returns (failures, notes). Absent tooling is an honest SKIP, never a
    failure: the lint gate must stay green on hosts without the FLUX
    interpreter vendored.
    """
    pkg = os.path.join(ROOT, "flux_verifier")
    needed = ["interpreter.py", "canon_serializer.py", "host.py",
              "canon_verify.fxu"]
    missing = [f for f in needed if not os.path.exists(os.path.join(pkg, f))]
    if missing:
        return [], [f"flux-verify: SKIP — flux_verifier incomplete "
                    f"(missing {missing})"]
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        from flux_verifier import FluxVerifyError  # noqa: PLC0415
    except ImportError as exc:
        return [], [f"flux-verify: SKIP — flux_verifier not importable ({exc})"]
    if quick:
        return _verify_flux_smoke(sample_size, FluxVerifyError)
    return _verify_flux_full(FluxVerifyError, corpus_path, certs_path)


def _verify_flux_smoke(sample_size: int, flux_exc: type[Exception]
                       ) -> tuple[list[str], list[str]]:
    """P0 — contract cell + seeded synthetic sample through the sandbox.

    The cheap vm==reference cross-check; kept as the --quick path when the
    full fabric gate is overkill (embedded hosts, fast feedback loops).
    """
    failures: list[str] = []
    notes: list[str] = []
    from flux_verifier import (  # noqa: PLC0415 — lazy by design
        CONTRACT_CELL, CONTRACT_HASH, verify_cell,
    )

    def _run(cell_id: int, dials: list[int], neighbors: list[int],
             pinned: int | None = None) -> dict:
        result = verify_cell(cell_id, dials, neighbors)
        if pinned is not None and result["vm_hash"] != pinned:
            raise flux_exc(
                f"vm=0x{result['vm_hash']:016x} != pinned contract "
                f"0x{pinned:016x}")
        return result

    checked = 0
    try:
        contract = _run(*CONTRACT_CELL, pinned=CONTRACT_HASH)
        checked += 1
        notes.append(
            f"flux-verify: contract cell id=1 -> 0x{contract['vm_hash']:016x} "
            f"({contract['steps']} steps, fuel {contract['fuel_consumed']}/"
            f"{contract['fuel_budget']})")
        rng = random.Random(20260920)
        for _ in range(sample_size):
            cid = rng.randrange(1, 2**32)
            dials = [rng.randrange(0, 0x10000) for _ in range(16)]
            nb = [rng.randrange(1, 2**32)
                  for _ in range(rng.randrange(0, 5))]
            _run(cid, dials, nb)
            checked += 1
    except Exception as exc:  # noqa: BLE001 — any drift/trap is a lint failure
        failures.append(f"flux-verify: {exc}")
    else:
        notes.append(f"flux-verify: OK {checked}/{checked} cells agree "
                     "(FLUX module == Python reference, fuel-bounded)")
    return failures, notes


def _verify_flux_full(flux_exc: type[Exception],
                      corpus_path: str | None,
                      certs_path: str | None
                      ) -> tuple[list[str], list[str]]:
    """P2 — the 71-paper fabric gate: the canon's own immune system.

    Three lines of defense, each a different kind of drift:
      1. corpus   the pinned snapshot's REFERENCE fabric hash must equal
                  CANON_TARGET. Cheap (no vm), catches snapshot tamper or
                  a stale bundle before any fuel is burned.
      2. fabric   the sandboxed vm run must HALT with CANON_TARGET under
                  the measured corpus fuel budget (100x). Catches
                  interpreter/codegen/serializer drift.
      3. certs    every recorded proof certificate (per-paper module
                  SHA-256 + fabric cert) must recompute clean. Catches
                  cert-file tamper and pins bytecode identity.

    Any failure lands in `failures` with a flux-verify: prefix — the same
    reporting shape as every other drift check in this linter.
    corpus_path/certs_path exist so tests can point the gate at fixture
    trees without touching the vendored bundle.
    """
    failures: list[str] = []
    notes: list[str] = []
    from flux_verifier import corpus, fabric, proof_certs  # noqa: PLC0415
    from flux_verifier import fnv1a_64_bytes  # noqa: PLC0415

    # Line 1 — corpus reference hash (cheap, no fuel burned).
    try:
        canon = corpus.load_corpus(corpus_path)
        cells = corpus.corpus_cells(canon)
        data = corpus.fabric_bytes(canon)
        ref = fnv1a_64_bytes(data)
    except Exception as exc:  # noqa: BLE001 — a broken corpus is a failure
        failures.append(f"flux-verify: corpus unusable — {exc}")
        return failures, notes
    notes.append(
        f"flux-verify: corpus {len(cells)} papers "
        f"(ids {cells[0][0]}..{cells[-1][0]}, {len(data)} bytes, "
        f"pinned {corpus.CORPUS_REPO}@{corpus.CORPUS_COMMIT[:7]})")
    if ref != corpus.CANON_TARGET:
        failures.append(
            f"flux-verify: corpus drift — reference fabric hash "
            f"0x{ref:016x} != canon target 0x{corpus.CANON_TARGET:016x} "
            f"(snapshot tampered or stale; regenerate: "
            f"python3 flux_verifier/corpus/_regen.py --fetch)")
        return failures, notes  # lines 2/3 would be pure noise on bad bytes
    notes.append(f"flux-verify: corpus reference hash == target "
                 f"0x{corpus.CANON_TARGET:016x}")

    # Line 2 — sandboxed fabric under the measured corpus fuel budget.
    # The same corpus object flows through: gate, vm, and certs verify
    # identical bytes, never three separate loads that could disagree.
    try:
        result = fabric.verify_fabric(canon=canon)
    except Exception as exc:  # noqa: BLE001 — drift/trap/fuel death fails loud
        failures.append(f"flux-verify: {exc}")
    else:
        notes.append(
            f"flux-verify: fabric vm -> 0x{result['vm_hash']:016x} "
            f"({result['steps']} steps, fuel {result['fuel_consumed']}/"
            f"{result['fuel_budget']}, {result['fuel_left']} left)")

    # Line 3 — proof certificate integrity (pure recompute).
    try:
        certs = proof_certs.load_proof_certs(certs_path)
        problems = proof_certs.check_cert_integrity(certs, canon)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"flux-verify: cert integrity check crashed — {exc}")
        return failures, notes
    for problem in problems:
        failures.append(f"flux-verify: cert drift — {problem}")
    if not problems:
        n_papers = len(certs.get("papers", []))
        digest = certs.get("fabric", {}).get("module_sha256", "")[:12]
        notes.append(f"flux-verify: proof certs {n_papers}/{len(cells)} "
                     f"recompute clean (fabric module {digest}…)")
    return failures, notes


def check_schema(repo: str, canon: dict[str, object]) -> list[str]:
    fails = []
    missing = [k for k in REQUIRED if k not in canon]
    if missing:
        fails.append(f"schema: missing fields {missing}")
    if str(canon.get("canon")) != "1":
        fails.append(f"schema: canon version must be 1, got {canon.get('canon')!r}")
    if canon.get("state") not in STATES:
        fails.append(f"schema: state {canon.get('state')!r} not in {sorted(STATES)}")
    if canon.get("ledger") not in LEDGERS:
        fails.append(f"schema: ledger {canon.get('ledger')!r} not in {sorted(LEDGERS)}")
    if not DATE_RE.match(str(canon.get("verified", ""))):
        fails.append(f"schema: verified must be YYYY-MM-DD, got {canon.get('verified')!r}")
    else:
        try:
            dt.date.fromisoformat(str(canon["verified"]))
        except ValueError as exc:
            fails.append(f"schema: verified invalid — {exc}")
    if canon.get("name") != repo:
        fails.append(f"drift: name {canon.get('name')!r} != repo {repo!r}")
    if str(canon.get("mission", "")).count(".") > 1:
        fails.append("schema: mission must be one honest sentence")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="local fixture dir {dir}/{repo}/CANON.md (no API calls)")
    ap.add_argument("--enforce-coverage", action="store_true",
                    help="missing CANON.md on Tier-1 becomes a failure")
    ap.add_argument("--remote", action="store_true",
                    help="scan GitHub remotes (default; flag accepted because "
                         "CI invokes lint with --remote)")
    ap.add_argument("--verify-flux", action="store_true",
                    help="the FLUX canon gate: by default the FULL 71-paper "
                         "fabric + proof certs (P2); skips honestly when "
                         "flux_verifier absent")
    ap.add_argument("--quick", action="store_true",
                    help="with --verify-flux: the 9-cell P0 smoke instead "
                         "of the full 71-paper fabric gate")
    ap.add_argument("--flux-sample", type=int, default=8,
                    help="synthetic cells for --verify-flux --quick "
                         "(default 8)")
    ap.add_argument("--flux-corpus", metavar="PATH",
                    help="with --verify-flux: gate THIS corpus snapshot "
                         "(candidate bytes) instead of the vendored bundle")
    ap.add_argument("--flux-certs", metavar="PATH",
                    help="with --verify-flux: recompute THESE proof certs "
                         "instead of the recorded set")
    args = ap.parse_args()

    repos = tier1_repos()
    canons: dict[str, dict[str, object]] = {}
    failures: list[str] = []
    warnings: list[str] = []
    coverage_missing: list[str] = []

    incomplete: RateLimited | None = None
    for repo in repos:
        if args.dir:
            path = os.path.join(args.dir, repo, "CANON.md")
            text = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        else:
            try:
                text = fetch_canon_remote(repo)
            except RateLimited as exc:
                incomplete = exc
                print(f"  INCOMPLETE  {exc} — {len(canons)}/{len(repos)} checked")
                break
        if text is None:
            coverage_missing.append(repo)
            continue
        parsed = parse_front_matter(text)
        if isinstance(parsed, str):
            failures.append(f"{repo}: parse — {parsed}")
            continue
        fails = check_schema(repo, parsed)
        failures.extend(f"{repo}: {f}" for f in fails)
        if not fails:
            canons[repo] = parsed

    # Edge bidirectionality among repos that have canon files.
    for src, canon in canons.items():
        for dst in as_list(canon.get("feeds")):
            other = canons.get(dst)
            if other is not None and src not in as_list(other.get("owed_by")):
                failures.append(
                    f"edge: {src}.feeds -> {dst} but {dst}.owed_by lacks {src}")
        for dst in as_list(canon.get("owed_by")):
            other = canons.get(dst)
            if other is not None and src not in as_list(other.get("feeds")):
                failures.append(
                    f"edge: {src}.owed_by -> {dst} but {dst}.feeds lacks {src}")

    # Staleness (remote mode; needs the API for pushed_at).
    if not args.dir:
        today = dt.date.today()
        for repo, canon in canons.items():
            if incomplete is not None:
                break
            verified = dt.date.fromisoformat(str(canon["verified"]))
            age = (today - verified).days
            try:
                pushed_at = str(api(f"/repos/SuperInstance/{repo}").get("pushed_at", ""))[:10]
            except RateLimited as exc:
                incomplete = exc
                print(f"  INCOMPLETE  {exc} — staleness phase, "
                      f"{len(canons)}/{len(repos)} canons fetched")
                break
            pushed = dt.date.fromisoformat(pushed_at) if pushed_at else None
            stale_push = pushed is not None and pushed > verified
            if age > 90 and stale_push:
                failures.append(
                    f"staleness: {repo} verified {age}d ago with pushes since — re-curate")
            elif age > 30 and stale_push:
                warnings.append(
                    f"staleness: {repo} verified {age}d ago with pushes since — due")

    # Coverage.
    for repo in coverage_missing:
        msg = f"coverage: {repo} has no CANON.md (Tier-1 requires one)"
        (failures if args.enforce_coverage else warnings).append(msg)

    # FLUX canon gate. Absent tooling skips.
    if args.verify_flux:
        flux_failures, flux_notes = verify_flux(
            args.flux_sample, quick=args.quick,
            corpus_path=args.flux_corpus, certs_path=args.flux_certs)
        failures.extend(flux_failures)
        for note in flux_notes:
            print(f"  INFO  {note}")

    print(f"canon-lint: {len(canons)}/{len(repos)} Tier-1 repos curated")
    for warning in warnings:
        print(f"  WARN  {warning}")
    for failure in failures:
        print(f"  FAIL  {failure}")
    if incomplete is not None:
        print(f"canon-lint: INCOMPLETE — stopped at {incomplete.repo} "
              f"({len(canons)}/{len(repos)} checked); "
              "set GITHUB_TOKEN or wait out the rate limit. "
              "An unchecked sweep is never a PASS.")
        return 2
    verdict = "FAIL" if failures else "PASS"
    print(f"canon-lint: {verdict} "
          f"({len(failures)} failures, {len(warnings)} warnings)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
