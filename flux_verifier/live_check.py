"""Verify a candidate quilt-live-canon corpus (worker.js) — companion CI entrypoint.

quilt-live-canon's canon-verify workflow calls this on every push/PR that
touches worker.js, so a canon-data change is gated by the same sandbox the
lint gate uses:

    python3 flux_verifier/live_check.py /path/to/worker.js

Checks, in order:
  1. the candidate CANON block parses against the verified adapter shape;
  2. the candidate's REFERENCE fabric hash equals CANON_TARGET (cheap, no
     fuel burned on drifted bytes);
  3. the sandboxed fabric over the candidate bytes reproduces CANON_TARGET
     under the measured corpus fuel budget.

Exit 0 with the measured facts on stdout when the candidate verifies.
Exit 1 with the drift line on stdout otherwise. Stdlib only; the same
drift discipline as fleet-canon/lint.py (docs/FLUX_CANON_VERIFIER.md).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flux_verifier import corpus, fabric  # noqa: E402
from flux_verifier import fnv1a_64_bytes  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    with open(sys.argv[1], encoding="utf-8") as fh:
        worker_js = fh.read()
    try:
        canon = corpus.parse_worker_canon(worker_js)
    except ValueError as exc:
        print(f"FAIL: candidate CANON block does not parse — {exc}")
        return 1
    cells = corpus.corpus_cells(canon)
    data = corpus.fabric_bytes(canon)
    ref = fnv1a_64_bytes(data)
    print(f"candidate: {len(cells)} papers, ids {cells[0][0]}..{cells[-1][0]}, "
          f"{len(data)} bytes")
    if ref != corpus.CANON_TARGET:
        print(f"FAIL: candidate corpus drift — reference fabric hash "
              f"0x{ref:016x} != canon target 0x{corpus.CANON_TARGET:016x}")
        return 1
    try:
        result = fabric.verify_fabric(canon=canon)
    except Exception as exc:  # noqa: BLE001 — any drift/trap is a failure
        print(f"FAIL: fabric verify — {exc}")
        return 1
    print(f"vm: 0x{result['vm_hash']:016x} ({result['steps']} steps, "
          f"fuel {result['fuel_consumed']}/{result['fuel_budget']}, "
          f"{result['fuel_left']} left)")
    print("PASS: candidate corpus verifies against the canon target")
    return 0


if __name__ == "__main__":
    sys.exit(main())
