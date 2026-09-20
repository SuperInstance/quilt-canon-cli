#!/usr/bin/env python3
"""Regenerate the stub Tier-1 roster under test/fixtures/tier1/.

The lint gate's CI job runs `lint.py --dir test/fixtures/tier1 --verify-flux`
so the FLUX immune system is exercised end-to-end on every push without
conflating tamper signal with live cross-repo CANON.md drift (that is the
daily remote lint's job, see .github/workflows/canon-lint.yml).

The stubs are intentionally minimal and edge-free: the gate suite
(test/test_lint_gate.py) already covers edge/schema drift with its own
fixtures. These exist so the CLI gate path is green-by-construction.

Run from repo root after tier1.txt changes:

    python3 test/fixtures/_gen_stubs.py
"""
from __future__ import annotations

import importlib.util
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

_spec = importlib.util.spec_from_file_location(
    "canon_lint", os.path.join(_ROOT, "fleet-canon", "lint.py"))
lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint)

STUB = """---
canon: 1
name: {repo}
mission: "Gate fixture stub."
state: active
family: test
vessel: test
born_from: []
feeds: []
owed_by: []
canonical_docs: []
ledger: git-log
verified: 2026-09-20
---
"""


def main() -> int:
    base = os.path.dirname(os.path.abspath(__file__))
    for repo in lint.tier1_repos():
        d = os.path.join(base, "tier1", repo)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "CANON.md"), "w", encoding="utf-8") as fh:
            fh.write(STUB.format(repo=repo))
    print(f"stub roster written: {len(lint.tier1_repos())} repos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
