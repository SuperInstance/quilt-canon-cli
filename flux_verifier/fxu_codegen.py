"""Codegen for canon_verify.fxu — the FLUX canon-verifier module.

The reference interpreter (flux_verifier/interpreter.py, ability-transfer PR #4)
is a 32-bit stack machine: 256-byte memory, u16 LOAD/STORE with IMMEDIATE
addresses, no indirect load/store, no indirect jump, no 64-bit arithmetic.
Consequences, stated honestly:

  1. FNV-1a 64-bit runs as 4 x u16 limbs (a0..a3, a0 lowest) in memory.
     Multiply by FNV_PRIME = 0x100000001B3 = p0 + p2*2^32 with p0 = 0x01B3,
     p2 = 0x0100. Schoolbook per limb, mod 2^64 (limb-4 carry discarded):

         t0 = a0*p0                  -> a0' = t0 & 0xFFFF ; c0 = t0 >> 16
         t1 = a1*p0 + c0             -> a1' = t1 & 0xFFFF ; c1 = t1 >> 16
         t2 = a2*p0 + a0*p2 + c1     -> a2' = t2 & 0xFFFF ; c2 = t2 >> 16
         t3 = a3*p0 + a1*p2 + c2     -> a3' = t3 & 0xFFFF (carry dropped)

     Every partial sum is < 2^26, so 32-bit stack ops are exact.
  2. STORE truncates to 16 bits (_store16 keeps value & 0xFFFF) — the single
     hard ISA constraint found while building this. A 32-bit intermediate can
     NEVER round-trip through data memory. Two follow-on design rules:
       a. carries and cross products live ON THE STACK only;
       b. limbs are double-buffered (old at 200..207, new at 212..219) so the
          t2/t3 cross products can read OLD a0/a1 after t0/t1 already wrote
          the NEW limbs. Codegen alternates the two buffers per byte; no copy.
  3. The module is STRAIGHT-LINE (fully unrolled): with only immediate
     addressing there is no way to index the input by a loop counter, so the
     byte length N is baked in at codegen time. One module instance per input
     length; the SPEC is this codegen + the pinned interpreter, not a single
     frozen byte string. A LOAD_IDX/escape op would collapse the family to
     one module (P2 open question, see docs/FLUX_CANON_VERIFIER.md).
  4. Fuel enforcement does not depend on FUEL_CHECK — the PR #4 governor
     meters EVERY instruction (_check_fuel in step()). FUEL_CHECK is still
     emitted every FUEL_CHECK_EVERY bytes (draft section 9.1 liveness rule is
     one per 1024 instructions; we are ~4x inside that) for draft
     conformance and trace observability.

Module contract (host embedding, see host.py):
  input:  host writes N serialized bytes to vm.memory[0:N]   (CAP: read bytes)
  init:   module stores FNV offset basis 0xCBF29CE484222325 into limbs
  body:   per byte: h ^= byte; h *= FNV_PRIME (mod 2^64), u16-limbed
  output: HALT with stack [..., a3, a2, a1, a0]; host reads u64 =
          (a3<<48)|(a2<<32)|(a1<<16)|a0 from the top four stack entries.
"""
from __future__ import annotations

from .interpreter import Assembler

# Memory map — two u16-limb buffers, alternating roles per byte.
# P0 legacy zone (n + 20 <= 200): buffers at 200..219, 256-byte memory.
# Fabric zone (larger n): buffers relocated ABOVE the input, 8-aligned.
BUF_A_LEGACY = 200    # limbs a0..a3 at 200, 202, 204, 206
BUF_B_LEGACY = 212    # limbs a0..a3 at 212, 214, 216, 218
LEGACY_ZONE_END = 220  # first address past the legacy buffer zone
MEM_MIN = 256
# u16 absolute addressing caps memory at 65536; keep margin for the zone.
MAX_INPUT = 65000


def buffer_zone(n: int) -> tuple[int, int, int]:
    """(buf_a, buf_b, memory_size) for an n-byte input.

    P0 contract: for every n that fit the legacy zone, the placement is
    UNCHANGED (buf 200/212, memory 256) so the frozen canon_verify.fxu and
    its sha256 pin stay byte-identical. Larger n relocates the zone above
    the input, 8-aligned, with 32 bytes of slack.
    """
    if not (0 < n <= MAX_INPUT):
        raise ValueError(f"input length {n} out of (0, {MAX_INPUT}]")
    if n + (LEGACY_ZONE_END - BUF_A_LEGACY) <= BUF_A_LEGACY:
        return BUF_A_LEGACY, BUF_B_LEGACY, MEM_MIN
    base = (n + 7) & ~7
    return base, base + 12, base + 32

# FNV_PRIME limb constants (see module docstring).
_P0 = 0x01B3
_P2 = 0x0100

# Draft section 9.1 wants a FUEL_CHECK at least every 1024 instructions;
# one byte costs ~58 instructions, so every 16 bytes is ~4x inside the rule.
FUEL_CHECK_EVERY = 16


def _emit_multiply(lines: list[str], old: int, new: int) -> None:
    """h *= FNV_PRIME (mod 2^64); reads limbs at `old`, writes at `new`.

    Cross products a0*p2 / a1*p2 are 32-bit and stay on the stack — see
    module docstring rule 2 (STORE is 16-bit; no wide value may round-trip
    through data memory).
    """
    o0, o1, o2, o3 = old, old + 2, old + 4, old + 6
    n0, n1, n2, n3 = new, new + 2, new + 4, new + 6
    # t0 = a0*p0 -> n0, carry on stack
    lines.append(f"    LOAD {o0}            ; t0 = a0*{_P0:#x}")
    lines.append(f"    PUSH {_P0}")
    lines.append("    MUL")
    lines.append("    DUP")
    lines.append("    PUSH 0xFFFF")
    lines.append("    AND")
    lines.append(f"    STORE {n0}")
    lines.append("    PUSH 16")
    lines.append("    SHR                    ; c0")
    # t1 = a1*p0 + c0 -> n1, carry
    lines.append(f"    LOAD {o1}            ; t1 = a1*{_P0:#x} + c0")
    lines.append(f"    PUSH {_P0}")
    lines.append("    MUL")
    lines.append("    ADD")
    lines.append("    DUP")
    lines.append("    PUSH 0xFFFF")
    lines.append("    AND")
    lines.append(f"    STORE {n1}")
    lines.append("    PUSH 16")
    lines.append("    SHR                    ; c1")
    # t2 = a2*p0 + a0*p2 + c1 -> n2, carry
    lines.append(f"    LOAD {o2}            ; t2 = a2*{_P0:#x} + a0*{_P2:#x} + c1")
    lines.append(f"    PUSH {_P0}")
    lines.append("    MUL")
    lines.append(f"    LOAD {o0}")
    lines.append(f"    PUSH {_P2}")
    lines.append("    MUL")
    lines.append("    ADD")
    lines.append("    ADD")
    lines.append("    DUP")
    lines.append("    PUSH 0xFFFF")
    lines.append("    AND")
    lines.append(f"    STORE {n2}")
    lines.append("    PUSH 16")
    lines.append("    SHR                    ; c2")
    # t3 = a3*p0 + a1*p2 + c2 -> n3 (final carry dropped: mod 2^64)
    lines.append(f"    LOAD {o3}            ; t3 = a3*{_P0:#x} + a1*{_P2:#x} + c2")
    lines.append(f"    PUSH {_P0}")
    lines.append("    MUL")
    lines.append(f"    LOAD {o1}")
    lines.append(f"    PUSH {_P2}")
    lines.append("    MUL")
    lines.append("    ADD")
    lines.append("    ADD")
    lines.append("    DUP")
    lines.append("    PUSH 0xFFFF")
    lines.append("    AND")
    lines.append(f"    STORE {n3}")
    lines.append("    POP                    ; discard limb-4 carry")


def _emit_byte(lines: list[str], j: int, old: int, new: int) -> None:
    """h ^= memory[j]; h *= FNV_PRIME. The XOR reads the OLD buffer; the
    multiply reads OLD and writes NEW."""
    word_addr = j & ~1
    if j % 2 == 0:
        lines.append(f"    LOAD {word_addr}            ; byte {j}: w & 0xFF")
        lines.append("    PUSH 0xFF")
        lines.append("    AND")
    else:
        lines.append(f"    LOAD {word_addr}            ; byte {j}: w >> 8")
        lines.append("    PUSH 8")
        lines.append("    SHR")
    lines.append(f"    LOAD {old}            ; a0 ^= byte (old buffer)")
    lines.append("    XOR")
    lines.append(f"    STORE {old}")
    _emit_multiply(lines, old, new)


def module_source(n: int) -> str:
    """Assembler source for the canon verifier over an n-byte input."""
    first, second, _mem = buffer_zone(n)
    lines: list[str] = [
        "; canon_verify.fxu — generated by flux_verifier.fxu_codegen",
        f"; input contract: {n} serialized bytes at memory[0:{n}]",
        f"; FNV-1a 64-bit, u16-limbed double-buffered, fuel-checked every "
        f"{FUEL_CHECK_EVERY} bytes",
        "",
        "    ; init: FNV offset basis 0xCBF29CE484222325 -> a3a2a1a0",
        "    PUSH 0x2325",
        f"    STORE {first}",
        "    PUSH 0x8422",
        f"    STORE {first + 2}",
        "    PUSH 0x9CE4",
        f"    STORE {first + 4}",
        "    PUSH 0xCBF2",
        f"    STORE {first + 6}",
        "",
    ]
    for j in range(n):
        if j > 0 and j % FUEL_CHECK_EVERY == 0:
            lines.append("    ESCAPE TEMPORAL FUEL_CHECK")
            lines.append("    POP                    ; discard observability probe")
        old = first if j % 2 == 0 else second
        new = second if j % 2 == 0 else first
        _emit_byte(lines, j, old, new)
    # results of byte n-1 landed in its `new` buffer
    final = second if (n - 1) % 2 == 0 else first
    lines += [
        "",
        "    ; output: push a3, a2, a1, a0 (host reads top four stack entries)",
        f"    LOAD {final + 6}",
        f"    LOAD {final + 4}",
        f"    LOAD {final + 2}",
        f"    LOAD {final}",
        "    HALT",
        "",
    ]
    return "\n".join(lines)


def build_module(n: int) -> bytes:
    """Assemble the canon verifier for an n-byte input."""
    return Assembler().parse(module_source(n)).assemble()


def memory_size_for(n: int) -> int:
    """Host embedding must size VM memory to fit input + limb buffers."""
    return buffer_zone(n)[2]
