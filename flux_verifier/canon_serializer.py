"""Canonical cell serializer — the cross-substrate contract.

Ported VERBATIM from SuperInstance/quilt-live-canon-pypi @ b14a821
(branch canon-canonical-sync, v0.9.1), live_canon/__init__.py:
serialize_cell() and fnv1a_64_bytes(). The contract cell is the known-answer
vector from that package's test/test_hash.py:

    serialize_cell(1, list(range(1, 17)), [2, 3, 4]) -> fnv1a_64_bytes
    == 0xE435D91D6D92A1D8

This module is the PYTHON REFERENCE SIDE of the flux verifier; the VM side is
flux_verifier/host.py. The two must agree by construction, not by discipline.
"""
from __future__ import annotations

# FNV-1a 64-bit constants (UTF-8/bytes, byte-exact across JS/C/Rust/Verilog/VHDL).
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x00000100000001B3

# The cross-substrate known-answer contract cell.
CONTRACT_CELL = (1, list(range(1, 17)), [2, 3, 4])
CONTRACT_HASH = 0xE435D91D6D92A1D8


def fnv1a_64_bytes(data: bytes) -> int:
    """FNV-1a 64-bit over raw bytes (canonical serialization path)."""
    h = FNV_OFFSET
    for byte in data:
        h ^= byte
        h = (h * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return h


def serialize_cell(cell_id: int, dials: list[int], neighbors: list[int]) -> bytes:
    """Canonical cell serialization, byte-exact with the Quilt spec and the
    Cloudflare Worker: type(1)=0x01, id(uint64 LE), 16 dials(int16 LE),
    neighbors(uint64 LE each)."""
    out = bytearray()
    out.append(0x01)
    out += (int(cell_id) & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
    for d in list(dials)[:16]:
        v = int(d) & 0xFFFF
        out += v.to_bytes(2, "little", signed=False)
    for n in neighbors:
        out += (int(n) & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
    return bytes(out)
