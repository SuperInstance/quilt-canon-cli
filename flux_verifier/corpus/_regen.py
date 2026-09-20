"""Extract the bundled 71-paper corpus snapshot from the source worker.js.

Two modes (run from the repo root):

    python3 flux_verifier/corpus/_regen.py /path/to/quilt-live-canon/worker.js
        Regenerate from a local checkout of the source repo.

    python3 flux_verifier/corpus/_regen.py --fetch
        Download worker.js from the PINNED upstream commit
        (CORPUS_REPO @ CORPUS_BRANCH : CORPUS_COMMIT in corpus/__init__.py)
        and regenerate from it. The pin means "update the corpus" is one
        documented command that cannot silently follow a moved branch — to
        track upstream movement you change the pin in corpus/__init__.py
        (commit hash, not just branch name), then --fetch.

Both modes verify the parse against the live-invariant count, then rewrite
flux_verifier/corpus/canon_71.json (the data.json canon shape). The gate's
line-1 reference hash check in fleet-canon/lint.py is what proves the
rewrite produced the right bytes: a bad regen fails lint on the next run.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from flux_verifier.corpus import (  # noqa: E402
    CORPUS_BRANCH, CORPUS_COMMIT, CORPUS_PAPERS, CORPUS_REPO,
    parse_worker_canon,
)


def _fetch_worker_js() -> str:
    url = (f"https://raw.githubusercontent.com/{CORPUS_REPO}/"
           f"{CORPUS_COMMIT}/worker.js")
    req = urllib.request.Request(url, headers={"User-Agent": "flux-corpus-regen"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _regen(worker_js: str) -> int:
    canon = parse_worker_canon(worker_js)
    if len(canon) != CORPUS_PAPERS:
        raise SystemExit(f"parse produced {len(canon)} papers, "
                         f"expected {CORPUS_PAPERS} — refusing to write")
    out = os.path.join(_HERE, "canon_71.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(canon, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {out}: {len(canon)} papers")
    return 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--fetch":
        print(f"fetching {CORPUS_REPO} @ {CORPUS_COMMIT[:7]} "
              f"(branch {CORPUS_BRANCH})")
        return _regen(_fetch_worker_js())
    if len(sys.argv) == 2:
        with open(sys.argv[1], encoding="utf-8") as fh:
            return _regen(fh.read())
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
