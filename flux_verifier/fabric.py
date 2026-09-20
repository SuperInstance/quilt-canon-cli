"""P1 — the 71-paper fabric verifier.

Runs the corpus fabric (flux_verifier.corpus.fabric_bytes, 2927 bytes for the
committed 71-paper canon) through the sandboxed FLUX module and compares the
HALT hash against CANON_TARGET 0x445185a3a99fd2e7 — the same drift discipline
as host.verify_cell and the lint drift check: mismatch raises FluxVerifyError,
a non-HALT exit raises FluxVerifyError, and every number in the result dict
is measured, never trusted.

Fuel: the design sizes the corpus budget at 100x measured single-cell steps
(P0 shipped 10x for the contract cell with the headroom documented). The
fabric budget is measured the same way — run once at unlimited fuel to count
exact steps, then budget = steps * FABRIC_FUEL_HEADROOM. As of this build the
measurement is 152580 steps for 2927 bytes, budget 15258000.
"""
from __future__ import annotations

from .canon_serializer import fnv1a_64_bytes
from .corpus import CANON_TARGET, fabric_bytes
from .host import FluxVerifyError, run_module
from .fxu_codegen import build_module

# Design (docs/FLUX_CANON_VERIFIER.md): corpus budget = 100x measured.
# Never silently inherit P0's 10x single-cell budget across the corpus line.
FABRIC_FUEL_HEADROOM = 100


def fabric_fuel_facts() -> dict:
    """Measured fuel accounting for the corpus fabric module."""
    data = fabric_bytes()
    code = build_module(len(data))
    # unlimited-fuel measurement run (fuel=0): exact step count
    _, steps, _, exit_name = run_module(data, fuel=0)
    if exit_name != "HALT":
        raise FluxVerifyError(f"fabric self-measure did not HALT: {exit_name}")
    budget = steps * FABRIC_FUEL_HEADROOM
    return {
        "n_bytes": len(data),
        "module_bytes": len(code),
        "steps": steps,
        "fuel_headroom": FABRIC_FUEL_HEADROOM,
        "fuel_budget": budget,
    }


def verify_fabric(fuel: int | None = None) -> dict:
    """Sandboxed verification of the 71-paper corpus fabric.

    Returns a result dict (hash, fuel accounting, exit). Raises
    FluxVerifyError on drift (vm != CANON_TARGET), on vm != python reference,
    or on any non-HALT exit — exactly the lint drift discipline.
    """
    data = fabric_bytes()
    facts = fabric_fuel_facts()
    budget = fuel if fuel is not None else facts["fuel_budget"]
    h, ran, left, exit_name = run_module(data, fuel=budget)
    expected_ref = fnv1a_64_bytes(data)
    result = {
        "n_bytes": len(data),
        "steps": ran,
        "fuel_budget": budget,
        "fuel_left": left,
        "fuel_consumed": budget - left,
        "exit": exit_name,
        "vm_hash": h,
        "ref_hash": expected_ref,
        "canon_target": CANON_TARGET,
    }
    if exit_name != "HALT":
        raise FluxVerifyError(
            f"fabric: module did not HALT ({exit_name}) after {ran} steps "
            f"on budget {budget}")
    if h != expected_ref:
        raise FluxVerifyError(
            f"fabric: vm/reference drift — vm=0x{h:016x} "
            f"ref=0x{expected_ref:016x}")
    if h != CANON_TARGET:
        raise FluxVerifyError(
            f"fabric: DRIFT — vm=0x{h:016x} != canon target "
            f"0x{CANON_TARGET:016x} (corpus changed? adapter drift?)")
    result["ok"] = True
    return result
