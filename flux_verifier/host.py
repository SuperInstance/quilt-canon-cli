"""Host embedding for the FLUX canon-verifier module.

Capability discipline (docs/FLUX_CANON_VERIFIER.md):
  * The VM is constructed with allow_fuel_set=False (the PR #4 default-deny):
    the module can never rewrite its own fuel meter. Fuel is host-set only.
  * No capabilities are granted to the module (CAP_INVOKE would trap).
  * The module has no I/O opcodes; the only host -> module channel is the
    initial memory image (the "read candidate bytes" capability).
  * Exit is structurally classified via vm.exit_reason (PR #4 ExitReason):
    HALT / OUT_OF_FUEL / MAX_STEPS, and fuel-policy traps (FuelSetDenied,
    FuelSetViolation) propagate as exceptions.
"""
from __future__ import annotations

import hashlib

from .canon_serializer import fnv1a_64_bytes, serialize_cell
from .fxu_codegen import build_module, memory_size_for
from .interpreter import ExitReason, FluxVM

FUEL_HEADROOM = 10     # budget = measured_steps * HEADROOM (design: 100x corpus;
                       # a single cell is tiny, 10x already bounds worst-case
                       # codegen error at an order of magnitude; see doc table)
MIN_FUEL_BUDGET = 4096


class FluxVerifyError(RuntimeError):
    """Raised when the sandboxed verification cannot produce a trustworthy
    answer (trap, fuel death, malformed output stack, hash mismatch)."""


_module_cache: dict[int, tuple[bytes, int]] = {}


def _measure_ceiling(n: int) -> int:
    """run() step ceiling for a module over n bytes: the exact cost is
    ~52n + fuel-check overhead; the ceiling only guards against a runaway
    measurement, fuel is the real governor."""
    return 1000 + 64 * n


def _module_for(n: int) -> tuple[bytes, int]:
    """(bytecode, exact_instructions_at_unlimited_fuel), cached per length."""
    if n not in _module_cache:
        code = build_module(n)
        probe = FluxVM(memory_size=memory_size_for(n), stack_size=256,
                       allow_fuel_set=False)
        probe.load(code)
        steps = probe.run(max_steps=_measure_ceiling(n))  # fuel=0 -> unlimited
        if probe.exit_reason != ExitReason.HALT:
            raise FluxVerifyError(
                f"self-measure failed: exit={ExitReason(probe.exit_reason).name}")
        _module_cache[n] = (code, steps)
    return _module_cache[n]


def module_sha256(n: int | None = None) -> str:
    """Hash of the module bytecode (n=None -> the contract-cell module)."""
    if n is None:
        n = len(serialize_cell(1, list(range(1, 17)), [2, 3, 4]))
    code, _ = _module_for(n)
    return hashlib.sha256(code).hexdigest()


def run_module(data: bytes, fuel: int = 0) -> tuple[int, int, int, str]:
    """Run the verifier module over data. Returns (hash, steps, fuel_left, exit).
    fuel=0 means unlimited (measurement mode); the host normally passes a
    finite budget.

    The run() max_steps ceiling is set above both the exact metered cost and
    any finite fuel budget, so fuel — never the ceiling — is the binding
    constraint; a ceiling hit means a bug, not a budget.
    """
    code, measured = _module_for(len(data))
    vm = FluxVM(memory_size=memory_size_for(len(data)), stack_size=256,
                allow_fuel_set=False)
    vm.memory[0:len(data)] = data
    vm.fuel = fuel
    vm.load(code)
    ceiling = (fuel if fuel > 0 else measured) + 1000
    steps = vm.run(max_steps=ceiling)
    exit_name = ExitReason(vm.exit_reason).name
    if vm.exit_reason != ExitReason.HALT:
        return (0, steps, vm.fuel, exit_name)
    if len(vm.stack) < 4:
        raise FluxVerifyError(f"short output stack: {vm.stack!r}")
    a0, a1, a2, a3 = (vm.stack[-1], vm.stack[-2], vm.stack[-3], vm.stack[-4])
    h = (a3 << 48) | (a2 << 32) | (a1 << 16) | a0
    return (h, steps, vm.fuel, exit_name)


def fuel_budget(n: int) -> tuple[int, int]:
    """(budget, exact_steps) for an n-byte input. Budget is host-imposed."""
    _, steps = _module_for(n)
    return (max(MIN_FUEL_BUDGET, steps * FUEL_HEADROOM), steps)


def verify_cell(cell_id: int, dials: list[int], neighbors: list[int],
                fuel: int | None = None) -> dict:
    """Verify one cell: VM-executed hash must equal the Python reference hash.

    Returns a result dict with hash, fuel accounting, and exit reason.
    Raises FluxVerifyError on any mismatch or untrustworthy run.
    """
    data = serialize_cell(cell_id, dials, neighbors)
    budget, steps = fuel_budget(len(data))
    if fuel is not None:
        budget = fuel
    h, ran, left, exit_name = run_module(data, fuel=budget)
    expected = fnv1a_64_bytes(data)
    result = {
        "cell_id": cell_id,
        "n_bytes": len(data),
        "steps": ran,
        "fuel_budget": budget,
        "fuel_left": left,
        "fuel_consumed": budget - left,
        "exit": exit_name,
        "vm_hash": h,
        "ref_hash": expected,
    }
    if exit_name != "HALT":
        raise FluxVerifyError(
            f"cell {cell_id}: module did not HALT ({exit_name}) "
            f"after {ran} steps on budget {budget}")
    if h != expected:
        raise FluxVerifyError(
            f"cell {cell_id}: drift — vm=0x{h:016x} ref=0x{expected:016x}")
    result["ok"] = True
    return result
