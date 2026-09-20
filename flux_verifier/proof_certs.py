"""P1 — FLUX proof certificates.

Per-paper: the module bytecode SHA-256 for that paper's canonical cell,
earned by an actual sandboxed run (the vm cell hash is recorded alongside,
so the cert binds content -> bytecode -> executed result). Fabric-level:
the corpus module's bytecode SHA-256, measured fuel, and the verified state
hash against CANON_TARGET.

Design ref (docs/FLUX_CANON_VERIFIER.md): "to_bytecode() SHA-256 recorded per
repo CANON.json (verified.flux_proof), so provenance survives independent of
any host." The org has no prior CANON.json shape — quilt-live-canon's data.json
convention is {"canon": ..., "bodies": ...} and the fleet stub is CANON.md
front matter. build_canon_json() therefore mirrors the CANON.md field names
in JSON and nests the certs under "verified"."flux_proof", the exact field
path the design names.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os

from .canon_serializer import fnv1a_64_bytes, serialize_cell
from .corpus import (
    CANON_TARGET, CORPUS_BRANCH, CORPUS_COMMIT, CORPUS_REPO,
    corpus_cells, fabric_bytes, load_corpus,
)
from .fabric import FABRIC_FUEL_HEADROOM, fabric_fuel_facts
from .fxu_codegen import build_module
from .host import run_module

_CERTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "proof_certs.json")

PAPER_FUEL_HEADROOM = 10  # same rule as host.verify_cell for single cells


def _paper_cert(number: int, dials: list[int], neighbors: list[int]) -> dict:
    data = serialize_cell(number, dials, neighbors)
    code = build_module(len(data))
    _, measured, _, _ = run_module(data, fuel=0)
    budget = max(4096, measured * PAPER_FUEL_HEADROOM)
    h, ran, left, exit_name = run_module(data, fuel=budget)
    if exit_name != "HALT":
        raise RuntimeError(f"paper {number}: cert run did not HALT ({exit_name})")
    ref = fnv1a_64_bytes(data)
    if h != ref:
        raise RuntimeError(f"paper {number}: vm/reference drift in cert run")
    return {
        "number": number,
        "n_bytes": len(data),
        "steps": ran,
        "fuel_budget": budget,
        "module_sha256": hashlib.sha256(code).hexdigest(),
        "cell_hash": f"0x{h:016x}",
    }


def build_proof_certs() -> dict:
    """Earn every cert in the sandbox: per-paper module + fabric module."""
    canon = load_corpus()
    papers = [_paper_cert(n, d, nb) for n, d, nb in corpus_cells(canon)]
    facts = fabric_fuel_facts()
    fabric_code = build_module(facts["n_bytes"])
    data = fabric_bytes(canon)
    h, ran, left, exit_name = run_module(data, fuel=facts["fuel_budget"])
    if exit_name != "HALT" or h != CANON_TARGET:
        raise RuntimeError(
            f"fabric cert run failed: exit={exit_name} hash=0x{h:016x}")
    return {
        "provenance": {
            "corpus_repo": CORPUS_REPO,
            "corpus_branch": CORPUS_BRANCH,
            "corpus_commit": CORPUS_COMMIT,
            "canon_target": f"0x{CANON_TARGET:016x}",
            "generated": dt.date.today().isoformat(),
        },
        "fabric": {
            **facts,
            "module_sha256": hashlib.sha256(fabric_code).hexdigest(),
            "state_hash": f"0x{h:016x}",
            "fuel_consumed": facts["fuel_budget"] - left,
        },
        "papers": papers,
    }


def save_proof_certs(certs: dict, path: str | None = None) -> str:
    out = path or _CERTS_PATH
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(certs, fh, indent=1)
        fh.write("\n")
    return out


def load_proof_certs(path: str | None = None) -> dict:
    with open(path or _CERTS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def check_cert_integrity(certs: dict, canon: dict | None = None) -> list[str]:
    """Recompute every cert from corpus + codegen and report mismatches.

    Returns the list of violations ([] == all certs integral). Pure
    re-computation: module SHA-256s from build_module, cell hashes from the
    reference serializer cross-checked against recorded vm results, fabric
    facts from a fresh measurement run.
    """
    problems: list[str] = []
    canon = canon or load_corpus()
    cells = corpus_cells(canon)
    papers = {p["number"]: p for p in certs.get("papers", [])}
    for number, dials, neighbors in cells:
        cert = papers.get(number)
        if cert is None:
            problems.append(f"paper {number}: missing cert")
            continue
        data = serialize_cell(number, dials, neighbors)
        code = build_module(len(data))
        digest = hashlib.sha256(code).hexdigest()
        if digest != cert["module_sha256"]:
            problems.append(
                f"paper {number}: module_sha256 drift "
                f"(recomputed {digest[:16]}… != recorded {cert['module_sha256'][:16]}…)")
        ref = fnv1a_64_bytes(data)
        if f"0x{ref:016x}" != cert["cell_hash"]:
            problems.append(f"paper {number}: cell_hash drift vs reference")
        if len(data) != cert["n_bytes"]:
            problems.append(f"paper {number}: n_bytes drift")
    facts = fabric_fuel_facts()
    fab = certs.get("fabric", {})
    fabric_code = build_module(facts["n_bytes"])
    digest = hashlib.sha256(fabric_code).hexdigest()
    if digest != fab.get("module_sha256"):
        problems.append("fabric: module_sha256 drift")
    if facts["steps"] != fab.get("steps"):
        problems.append(
            f"fabric: measured steps drift {facts['steps']} != {fab.get('steps')}")
    if f"0x{CANON_TARGET:016x}" != certs.get("provenance", {}).get("canon_target"):
        problems.append("provenance: canon_target mismatch")
    return problems


def build_canon_json(certs: dict, repo_meta: dict) -> dict:
    """CANON.json for this repo, mirroring the fleet CANON.md field names
    with the certs at verified.flux_proof (the design's named field path)."""
    return {
        **repo_meta,
        "verified": {
            "date": certs["provenance"]["generated"],
            "flux_proof": {
                "interpreter": "flux_verifier/interpreter.py "
                               "(ability-transfer PR#4, sha256-pinned)",
                "canon_target": certs["provenance"]["canon_target"],
                "fabric": certs["fabric"],
                "papers": certs["papers"],
            },
        },
    }
