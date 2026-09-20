"""Extract the bundled 71-paper corpus snapshot from the source worker.js.

One-off regeneration tool (run from the repo root):

    python3 flux_verifier/corpus/_regen.py /path/to/quilt-live-canon/worker.js

Verifies the parse against the live-invariant count, then rewrites
flux_verifier/corpus/canon_71.json (the data.json canon shape).
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from flux_verifier.corpus import (  # noqa: E402
    CORPUS_PAPERS, parse_worker_canon,
)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    with open(sys.argv[1], encoding="utf-8") as fh:
        canon = parse_worker_canon(fh.read())
    if len(canon) != CORPUS_PAPERS:
        raise SystemExit(f"parse produced {len(canon)} papers, "
                         f"expected {CORPUS_PAPERS} — refusing to write")
    out = os.path.join(_HERE, "canon_71.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(canon, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {out}: {len(canon)} papers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
