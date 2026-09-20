#!/usr/bin/env python3
"""canon-lint FLUX gate tests — the immune system, verified in BOTH directions.

Doctrine (docs/FLUX_CANON_VERIFIER.md): the gate must fail LOUD on tamper
and pass CLEAN on truth. So every test here runs both ways:

  1. clean gate        vendored bundle → zero failures; notes name all
                       three defense lines (corpus / fabric / certs).
  2. quick smoke       --quick path still the 9-cell P0 cross-check, clean.
  3. corpus tamper     one paper's title flipped → gate FAILS with the
                       corpus-drift message; vm/cert lines never fire.
  4. cert tamper       recorded certs with one module_sha256 flipped →
                       gate FAILS with cert-drift; corpus+fabric stay green.
  5. fuel boundary     the gate's budget discipline is measured, never
                       trusted: budget == 100x exact steps, and a budget
                       one below the measurement dies OUT_OF_FUEL and
                       surfaces as a gate failure — never a hang.
  6. CLI end-to-end    `lint.py --dir <stubs> --verify-flux` exits 0 clean
                       and exits 1 against a tampered --flux-corpus.

Run: python3 test/test_lint_gate.py   (stdlib only, ~15s — fuel is real)
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from flux_verifier import corpus, fabric, FluxVerifyError  # noqa: E402
from flux_verifier.proof_certs import load_proof_certs  # noqa: E402


def _load_lint():
    spec = importlib.util.spec_from_file_location(
        "canon_lint", os.path.join(ROOT, "fleet-canon", "lint.py"))
    lint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lint)
    return lint


lint = _load_lint()
PASS = []


def ok(name: str, detail: str = "") -> None:
    PASS.append(name)
    print(f"  ok  {name}" + (f" — {detail}" if detail else ""))


def _tampered_corpus(tmp: str) -> str:
    canon = corpus.load_corpus()
    first = sorted(canon, key=int)[0]
    canon[first]["title"] = canon[first]["title"] + " TAMPERED"
    path = os.path.join(tmp, "corpus_tampered.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(canon, fh)
    return path


def _tampered_certs(tmp: str) -> str:
    certs = load_proof_certs()
    certs["papers"][0]["module_sha256"] = "0" * 64
    path = os.path.join(tmp, "certs_tampered.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(certs, fh)
    return path


def check_clean_gate() -> None:
    failures, notes = lint.verify_flux(sample_size=8)
    assert failures == [], failures
    joined = "\n".join(notes)
    assert "corpus reference hash == target" in joined
    assert "fabric vm -> 0x445185a3a99fd2e7" in joined
    assert "recompute clean" in joined
    ok("gate: clean vendored bundle passes (3 defense lines, 0 failures)",
       f"{len(notes)} notes")


def check_quick_smoke() -> None:
    failures, notes = lint.verify_flux(sample_size=4, quick=True)
    assert failures == [], failures
    assert any("contract cell" in n for n in notes)
    assert not any("fabric vm" in n for n in notes), \
        "quick path must not burn fabric fuel"
    ok("gate: --quick stays the 9-cell P0 smoke (no corpus fuel burned)")


def check_corpus_tamper(tmp: str) -> None:
    bad = _tampered_corpus(tmp)
    failures, notes = lint.verify_flux(sample_size=8, corpus_path=bad)
    assert len(failures) == 1, failures
    assert "corpus drift" in failures[0]
    assert "0x445185a3a99fd2e7" in failures[0]
    joined = "\n".join(notes)
    assert "fabric vm" not in joined, \
        "line 1 must stop the gate before fuel is burned on bad bytes"
    ok("gate: single-paper tamper fails loud with the corpus-drift message",
       failures[0][:72] + "…")


def check_cert_tamper(tmp: str) -> None:
    bad = _tampered_certs(tmp)
    failures, notes = lint.verify_flux(sample_size=8, certs_path=bad)
    assert failures, "tampered certs must fail the gate"
    assert any("cert drift" in f for f in failures), failures
    joined = "\n".join(notes)
    assert "corpus reference hash == target" in joined, \
        "corpus line stays green when only certs are tampered"
    assert "fabric vm -> 0x445185a3a99fd2e7" in joined, \
        "fabric line stays green when only certs are tampered"
    ok("gate: cert tamper fails loud (cert drift) while corpus+fabric stay green")


def check_fuel_boundary() -> None:
    facts = fabric.fabric_fuel_facts()
    assert facts["fuel_budget"] == facts["steps"] * 100, facts
    try:
        fabric.verify_fabric(fuel=facts["steps"] - 1)
    except FluxVerifyError as exc:
        assert "OUT_OF_FUEL" in str(exc) or "did not HALT" in str(exc)
        ok("gate: fuel one below the measurement dies OUT_OF_FUEL (fail loud)",
           f"budget {facts['fuel_budget']} = 100x {facts['steps']} steps")
    else:
        raise AssertionError("under-fueled fabric run must not HALT clean")
    # and the exact-step budget also fails (HALT never reached — the
    # killing instruction is counted, fuel hits 0 first)
    try:
        fabric.verify_fabric(fuel=facts["steps"])
    except FluxVerifyError:
        ok("gate: fuel == exact steps also fails (HALT is never metered in)")
    else:
        raise AssertionError("exact-step budget must not HALT clean")


def _write_canon_stubs(base: str) -> None:
    repos = lint.tier1_repos()
    for repo in repos:
        os.makedirs(os.path.join(base, repo), exist_ok=True)
        with open(os.path.join(base, repo, "CANON.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(
                "---\n"
                f"canon: 1\nname: {repo}\n"
                "mission: \"Gate test fixture.\"\n"
                "state: active\nfamily: test\nvessel: test\n"
                "born_from: []\nfeeds: []\nowed_by: []\n"
                "canonical_docs: []\nledger: git-log\n"
                "verified: 2026-09-20\n---\n")


def check_cli_end_to_end(tmp: str) -> None:
    stubs = os.path.join(tmp, "stubs")
    _write_canon_stubs(stubs)
    lint_py = os.path.join(ROOT, "fleet-canon", "lint.py")

    clean = subprocess.run(
        [sys.executable, lint_py, "--dir", stubs, "--verify-flux"],
        capture_output=True, text=True)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "flux-verify: fabric vm -> 0x445185a3a99fd2e7" in clean.stdout
    assert "canon-lint: PASS" in clean.stdout
    ok("cli: --dir stubs --verify-flux exits 0 clean with gate notes")

    bad = _tampered_corpus(tmp)
    dirty = subprocess.run(
        [sys.executable, lint_py, "--dir", stubs, "--verify-flux",
         "--flux-corpus", bad],
        capture_output=True, text=True)
    assert dirty.returncode == 1, "tampered corpus must fail the CLI gate"
    assert "corpus drift" in dirty.stdout
    assert "canon-lint: FAIL" in dirty.stdout
    ok("cli: --flux-corpus <tampered> exits 1 with the drift message")


def main() -> int:
    print("canon-lint FLUX gate tests")
    tmp = tempfile.mkdtemp(prefix="flux-gate-test-")
    try:
        check_clean_gate()
        check_quick_smoke()
        check_corpus_tamper(tmp)
        check_cert_tamper(tmp)
        check_fuel_boundary()
        check_cli_end_to_end(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"ALL {len(PASS)} LINT GATE CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
