"""flux_verifier — FLUX canon-verifier (P0).

Sandboxed, fuel-bounded verification of the canonical cell serializer on the
FLUX ISA v3 reference interpreter, per docs/FLUX_CANON_VERIFIER.md.

Provenance pins:
  * interpreter.py is BYTE-IDENTICAL vendored from
    SuperInstance/ability-transfer @ 2b821b7
    ("fuel governance: capability-gated FUEL_SET + structured exhaustion",
    ability-transfer PR #4), file reference/interpreter.py:
    sha256 = 776388d55ac75265018185cbac830e3ac2272483c291e137c0b2c33872336238
  * canon_serializer.py ports serialize_cell()/fnv1a_64_bytes() verbatim from
    SuperInstance/quilt-live-canon-pypi @ b14a821
    (branch canon-canonical-sync, v0.9.1), live_canon/__init__.py.

The module canon_verify.fxu computes FNV-1a 64-bit over the canonical cell
serialization (type‖id‖dials‖neighbors) as 4×u16 limbs, because the reference
interpreter is a 32-bit stack machine with no 64-bit arithmetic.
"""

from .canon_serializer import (
    FNV_OFFSET,
    FNV_PRIME,
    CONTRACT_CELL,
    CONTRACT_HASH,
    fnv1a_64_bytes,
    serialize_cell,
)
from .host import FluxVerifyError, verify_cell, module_sha256

__all__ = [
    "FNV_OFFSET", "FNV_PRIME", "CONTRACT_CELL", "CONTRACT_HASH",
    "fnv1a_64_bytes", "serialize_cell",
    "FluxVerifyError", "verify_cell", "module_sha256",
]

INTERPRETER_PIN_COMMIT = "2b821b746b2396395194881c58dd0a2e983c5ce9"
INTERPRETER_PIN_SHA256 = "776388d55ac75265018185cbac830e3ac2272483c291e137c0b2c33872336238"
