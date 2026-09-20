#!/usr/bin/env python3
"""flux_verifier self-test — P0 conformance + fuel-governance proofs.

Run: python3 test/test_flux_verify.py
Stdlib only. Exits non-zero on any failure.

Covers:
  1. contract cell  serialize_cell(1, 1..16, [2,3,4]) -> 0xe435d91d6d92a1d8
     via the PYTHON REFERENCE (sanity) and via the VM MODULE (the P0 claim).
  2. fuel accounting: exact steps at unlimited fuel; clean HALT on a finite
     host budget with exact consumption; OUT_OF_FUEL at the boundary.
  3. governor traps under PR #4:
       - FUEL_SET on allow_fuel_set=False      -> FuelSetDenied (default-deny)
       - FUEL_SET raising the budget (granted) -> FuelSetViolation
       - FUEL_SET 0 = "unlimited" escape hatch -> FuelSetViolation
       - infinite loop under a finite budget   -> OUT_OF_FUEL, steps == budget
  4. seeded synthetic cells: VM hash == Python reference hash.
  5. P1 corpus adapter: bundled snapshot parses, 71 papers, reference
     fabric hash == CANON_TARGET 0x445185a3a99fd2e7.
  6. P1 fabric (VM): sandboxed module over the 2927-byte corpus fabric
     reproduces CANON_TARGET; fuel accounting exact at both boundaries
     (budget == steps dies on the last metered op; budget == steps+1
     HALTs with exactly 1 fuel to spare).
  7. P1 proof certs: all 71 per-paper module SHA-256s recompute clean;
     integrity check detects tampering; fabric cert facts are stable.
"""
from __future__ import annotations

import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flux_verifier import (
    CONTRACT_CELL, CONTRACT_HASH,
    serialize_cell, fnv1a_64_bytes, verify_cell, FluxVerifyError,
)
from flux_verifier.host import run_module, fuel_budget, module_sha256
from flux_verifier.interpreter import (
    Assembler, ExitReason, FluxVM, FuelSetDenied, FuelSetViolation,
)
from flux_verifier import corpus
from flux_verifier.fabric import fabric_fuel_facts, verify_fabric
from flux_verifier.proof_certs import (
    build_proof_certs, check_cert_integrity, load_proof_certs,
)

PASS = []


def ok(name: str, detail: str = "") -> None:
    PASS.append(name)
    print(f"  ok  {name}" + (f" — {detail}" if detail else ""))


def check_contract_reference() -> None:
    cid, dials, nb = CONTRACT_CELL
    data = serialize_cell(cid, dials, nb)
    h = fnv1a_64_bytes(data)
    assert h == CONTRACT_HASH, f"reference drift: {h:#x}"
    assert len(data) == 65, f"contract cell is 65 bytes, got {len(data)}"
    ok("reference: contract cell hashes to 0xe435d91d6d92a1d8", f"{len(data)} bytes")


def check_contract_vm() -> dict:
    cid, dials, nb = CONTRACT_CELL
    result = verify_cell(cid, dials, nb)
    assert result["vm_hash"] == CONTRACT_HASH, f"vm drift: {result['vm_hash']:#x}"
    ok("vm: contract cell reproduces 0xe435d91d6d92a1d8",
       f"steps={result['steps']} fuel={result['fuel_consumed']}/{result['fuel_budget']}")
    return result


def check_fuel_accounting() -> None:
    cid, dials, nb = CONTRACT_CELL
    data = serialize_cell(cid, dials, nb)
    budget, steps = fuel_budget(len(data))

    h_unl, steps_unl, left_unl, exit_unl = run_module(data, fuel=0)
    assert exit_unl == "HALT" and h_unl == CONTRACT_HASH
    assert steps_unl == steps, (steps_unl, steps)
    ok("fuel: unlimited run HALTs and measures exact steps", f"steps={steps}")

    h_b, steps_b, left_b, exit_b = run_module(data, fuel=budget)
    assert exit_b == "HALT" and h_b == CONTRACT_HASH
    assert steps_b == steps and left_b == budget - steps
    ok("fuel: host budget HALTs clean with exact accounting",
       f"budget={budget} consumed={budget - left_b} left={left_b}")

    # Governor semantics (vendored interpreter, exact):
    #   * every metered instruction decrements AFTER executing; the
    #     instruction that drops fuel to exactly 0 IS executed and counted,
    #     then the VM dies OUT_OF_FUEL before the next instruction.
    #   * HALT is unmetered AND excluded from run()'s step count; the
    #     OUT_OF_FUEL killing instruction IS included. Both boundaries
    #     below therefore report `steps` executed — only exit/fuel differ.
    h_t, steps_t, left_t, exit_t = run_module(data, fuel=steps)
    assert exit_t == "OUT_OF_FUEL" and steps_t == steps and left_t == 0, \
        (exit_t, steps_t, left_t)
    ok("fuel: budget == exact steps dies OUT_OF_FUEL on the last metered op",
       f"{steps_t}/{steps} executed, fuel 0, HALT never reached")

    h_1, steps_1, left_1, exit_1 = run_module(data, fuel=steps + 1)
    assert exit_1 == "HALT" and h_1 == CONTRACT_HASH and left_1 == 1, \
        (exit_1, h_1, left_1)
    ok("fuel: budget == steps+1 HALTs clean with exactly 1 fuel to spare")


def _asm(source: str) -> bytes:
    return Assembler().parse(source).assemble()


def check_governor_traps() -> None:
    # 1. default-deny: FUEL_SET traps on a host that never granted it
    vm = FluxVM(allow_fuel_set=False)
    vm.load(_asm("ESCAPE SECURITY FUEL_SET 0xFFFF\nloop: JMP loop"))
    vm.fuel = 1000
    try:
        vm.run()
    except FuelSetDenied:
        ok("governor: FUEL_SET denied under default-deny (allow_fuel_set=False)")
    else:
        raise AssertionError("FUEL_SET escaped the default-deny governor")
    assert vm.exit_reason == ExitReason.RUNNING  # trap propagated, not a halt

    # 2. granted but raising: FuelSetViolation
    vm = FluxVM(allow_fuel_set=True)
    vm.load(_asm("ESCAPE SECURITY FUEL_SET 500"))
    vm.fuel = 100
    try:
        vm.run()
    except FuelSetViolation:
        ok("governor: FUEL_SET raising the active budget traps FuelSetViolation")
    else:
        raise AssertionError("FUEL_SET raised the budget unchecked")

    # 3. granted but requesting 0 (the 'unlimited' escape hatch)
    vm = FluxVM(allow_fuel_set=True)
    vm.load(_asm("ESCAPE SECURITY FUEL_SET 0"))
    vm.fuel = 100
    try:
        vm.run()
    except FuelSetViolation:
        ok("governor: FUEL_SET 0 (unlimited escape hatch) traps FuelSetViolation")
    else:
        raise AssertionError("FUEL_SET 0 escaped while a budget was active")

    # 4. granted and lowering: budget is REPLACED (1000 -> 50), the FUEL_SET
    #    op itself is metered (50->49), then the meter kills the loop.
    vm = FluxVM(allow_fuel_set=True)
    vm.load(_asm("ESCAPE SECURITY FUEL_SET 50\nloop: JMP loop"))
    vm.fuel = 1000
    steps = vm.run()
    assert vm.exit_reason == ExitReason.OUT_OF_FUEL and steps == 50, steps
    ok("governor: FUEL_SET may LOWER the budget (1000->50) and the meter enforces it",
       f"OUT_OF_FUEL at {steps} steps")

    # 5. pure infinite loop under a finite host budget: killed, exactly metered
    vm = FluxVM(allow_fuel_set=False)
    vm.load(_asm("loop: JMP loop"))
    vm.fuel = 1000
    steps = vm.run()
    assert vm.exit_reason == ExitReason.OUT_OF_FUEL and steps == 1000, steps
    ok("governor: infinite loop dies OUT_OF_FUEL, steps == budget", "1000/1000")


def check_seeded_cells(k: int = 8) -> None:
    rng = random.Random(20260920)
    for i in range(k):
        cid = rng.randrange(1, 2**32)
        dials = [rng.randrange(0, 0x10000) for _ in range(16)]
        nb = [rng.randrange(1, 2**32) for _ in range(rng.randrange(0, 5))]
        result = verify_cell(cid, dials, nb)
        assert result["vm_hash"] == result["ref_hash"]
    ok(f"vm==reference on {k} seeded synthetic cells",
       f"sha256(module family)={module_sha256()[:16]}…")


def check_corpus_adapter() -> None:
    canon = corpus.load_corpus()
    assert len(canon) == 71, len(canon)
    cells = corpus.corpus_cells(canon)
    ids = [c[0] for c in cells]
    assert ids == sorted(ids), "fabric cells must be sorted by id"
    assert ids[0] == 408 and ids[-1] == 478 and len(ids) == 71
    data = corpus.fabric_bytes(canon)
    assert len(data) == 2927, len(data)
    assert fnv1a_64_bytes(data) == corpus.CANON_TARGET, (
        f"reference fabric drift: {fnv1a_64_bytes(data):#x}")
    # adapter parser: verified shape parses, wrong shape fails loud
    mini = ('const CANON = {\n'
            '  408: { number: 408, title: "F98 — Suite", f_number: 98, '
            'phase: 222, date: "2026-09-03", ref_papers: [], '
            'ref_f_numbers: [97] },\n'
            '  425: { number: 425, title: "Colon: inside", f_number: 115, '
            'phase: 237, date: "2026-09-03", ref_papers: [426, 427], '
            'ref_f_numbers: [] },\n'
            '};')
    parsed = corpus.parse_worker_canon(mini)
    assert parsed["425"]["ref_papers"] == [426, 427]
    assert parsed["408"]["title"] == "F98 — Suite"
    try:
        corpus.parse_worker_canon('const CANON = {\n  not: an entry,\n};')
    except ValueError:
        pass
    else:
        raise AssertionError("parser accepted an unverified shape")
    ok("corpus: 71 papers (408..478), reference fabric hash == "
       "0x445185a3a99fd2e7", f"{len(data)} bytes")


def check_fabric_vm() -> None:
    facts = fabric_fuel_facts()
    assert facts["n_bytes"] == 2927
    steps = facts["steps"]
    assert facts["fuel_budget"] == steps * 100
    result = verify_fabric()
    assert result["vm_hash"] == corpus.CANON_TARGET, f"{result['vm_hash']:#x}"
    assert result["ref_hash"] == corpus.CANON_TARGET
    assert result["exit"] == "HALT"
    assert result["fuel_consumed"] == steps
    ok("vm: 71-paper fabric reproduces 0x445185a3a99fd2e7 in-sandbox",
       f"steps={steps} fuel={result['fuel_consumed']}/{result['fuel_budget']}")

    data = corpus.fabric_bytes()
    # exact boundary, corpus scale: budget == steps dies on the last metered
    # op (HALT never reached); budget == steps+1 HALTs with 1 to spare.
    h_t, steps_t, left_t, exit_t = run_module(data, fuel=steps)
    assert exit_t == "OUT_OF_FUEL" and steps_t == steps and left_t == 0, \
        (exit_t, steps_t, left_t)
    ok("fuel: fabric budget == exact steps dies OUT_OF_FUEL on the last "
       "metered op", f"{steps_t}/{steps} executed, fuel 0")

    h_1, steps_1, left_1, exit_1 = run_module(data, fuel=steps + 1)
    assert exit_1 == "HALT" and h_1 == corpus.CANON_TARGET and left_1 == 1, \
        (exit_1, h_1, left_1)
    ok("fuel: fabric budget == steps+1 HALTs clean with exactly 1 fuel to spare")


def check_proof_certs() -> None:
    certs = load_proof_certs()
    assert len(certs["papers"]) == 71
    problems = check_cert_integrity(certs)
    assert problems == [], problems
    assert certs["fabric"]["steps"] == fabric_fuel_facts()["steps"]
    assert certs["fabric"]["state_hash"] == "0x445185a3a99fd2e7"
    ok("certs: all 71 paper module SHA-256s + fabric cert recompute clean",
       f"fabric module sha256={certs['fabric']['module_sha256'][:16]}…")

    # tamper detection: one flipped byte in one title must surface as
    # drift. Module SHA-256 is length-parameterized (content-independent
    # by design — it is the serializer spec for that length), so the
    # content-bound cert field is cell_hash; the fabric hash drifts too.
    canon = corpus.load_corpus()
    bad = {k: dict(v) for k, v in canon.items()}
    first = sorted(bad, key=int)[0]
    bad[first]["title"] = bad[first]["title"] + " TAMPERED"
    cells = corpus.corpus_cells(bad)
    data = corpus.fabric_bytes(bad)
    assert fnv1a_64_bytes(data) != corpus.CANON_TARGET
    cell_hash = f"0x{fnv1a_64_bytes(serialize_cell(*cells[0])):016x}"
    cert = {p["number"]: p for p in certs["papers"]}[cells[0][0]]
    assert cell_hash != cert["cell_hash"], "tampered cell hash must drift"
    ok("certs: tampering is detected (fabric hash + cell_hash both drift)")


def main() -> int:
    print("flux_verifier self-test")
    check_contract_reference()
    check_contract_vm()
    check_fuel_accounting()
    check_governor_traps()
    check_seeded_cells()
    check_corpus_adapter()
    check_fabric_vm()
    check_proof_certs()
    print(f"ALL {len(PASS)} FLUX VERIFIER CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
