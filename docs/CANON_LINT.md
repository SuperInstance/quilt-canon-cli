# Canon Lint — the contract as prose

This page explains what `fleet-canon/lint.py` checks and *why*, for humans
landing here from a PR check and for agents deciding whether a canon stub
belongs in a repo. If you only read one file in this repo, read this one.

## What a CANON.md is

Every Tier-1 fleet repo carries a `CANON.md`: a stub (max 24 lines — *canon
is the handle, not the door*) whose front-matter declares what the repo is,
what it feeds, and what it owes. Canon lint is the referee that keeps those
declarations structurally honest. It is a *parse-time* referee: it checks
what the stub *says*, not what the repo *proves*. (The proving layer is the
FLUX canon verifier — see "Springboard" below.)

## The rules, and the failure each one prevents

1. **The stub stays a stub.** Over 24 lines, missing fences, or prose after
   the front-matter all fail. *Failure prevented:* a canon that becomes a
   document stops being curated — nobody re-reads a page, everybody re-reads
   a handle.
2. **Schema completeness.** `canon: 1`, `name` == repo name, `state` in
   {experimental, active, stable, sunset}, `ledger` in {none, quilt-wal,
   git-log}, `verified` a real ISO date, and all required fields present.
   *Failure prevented:* a stub that drifts from the repo it describes is a
   signpost pointing at a building that moved.
3. **One honest mission sentence.** The check counts periods — a mission
   with more than one fails. This is deliberately cheap, and cheap proxies
   have a known failure mode: a mission containing "Q1.15." counts two
   periods and fails despite being true. That case lives in the question
   pool as "validators should parse sentences, not count periods." The rule
   stays until the upgrade doesn't overfit; a referee that lies to pass a
   true statement is worse than no referee.
4. **Edges are bidirectional.** `A.feeds B` requires `B.owed_by A`, and
   vice versa, whenever both sides carry a CANON.md. *Failure prevented:* a
   one-way edge is a claim the target never agreed to — the graph quietly
   becomes a broadcast, not a conversation. In CI this is a **build
   failure**, not a warning.
5. **Staleness has windows.** Remote mode (default): `verified` more than
   90 days ago *with pushes since* is a failure on Tier-1; over 30 days is
   a warning. A repo that changed after its canon was verified has, by
   definition, an unverified canon.
6. **Coverage is counted.** Tier-1 repos without a CANON.md are warnings —
   flipping to failures with `--enforce-coverage` once coverage reaches
   100%, so the gate never tightens before the fleet is actually behind it.

## Source of truth

Each repo's `CANON.md` on its default branch is the record (lint also tries
`canon-stub` and `canon-md` refs). `fleet-canon/tier1.txt` is the tier
roster. The deployed `quilt-live-canon` worker is the *live* face of the
canon; when the stub and the worker disagree, the stub is behind — re-curate
the stub, never weaken the check. The worker's README drift table records
historical mismatches (e.g. the `0xbf27a3631cdee337` strand) and their
resolutions; lint exists so that table stays short.

## How to run

```bash
python3 fleet-canon/lint.py                    # remote, over tier1.txt
python3 fleet-canon/lint.py --dir fixtures     # local dirs, no API calls
python3 fleet-canon/lint.py --enforce-coverage # missing CANON.md = failure
python3 fleet-canon/lint.py --verify-flux      # + the FULL 71-paper FLUX gate
python3 fleet-canon/lint.py --verify-flux --quick   # 9-cell smoke instead
node --test test/test.js                       # the gate's own contract tests
```

`--verify-flux` is the canon's immune system at lint time: three defense
lines (corpus reference hash vs target, sandboxed fabric run under the
measured fuel budget, full proof-certificate recompute). Any drift is a
lint FAILURE with the same reporting shape as the other checks. Absent
`flux_verifier` tooling is an honest SKIP. `--flux-corpus`/`--flux-certs`
gate candidate bytes instead of the vendored bundle. See
`docs/FLUX_CANON_VERIFIER.md` for the full discipline.

CI runs both on every push and pull request (`.github/workflows/canon-lint.yml`).
`GITHUB_TOKEN`, if set, relaxes the GitHub API budget.

## Springboard: from parsing to proving

Lint answers "is the stub well-formed and current?" The next question is
"is the canon's *content* right?" — and answering it inside the fleet's own
sandbox is the point of `docs/FLUX_CANON_VERIFIER.md`: a fuel-bounded FLUX
module recomputes a canon's declared hashes under an auditable instruction
budget, so a hash stops being a string a stub *asserts* and becomes a value
the substrate *reproduces*. **Built (P0+P1+P2):** `lint.py --verify-flux`
now runs that sandbox as the gate, and `.github/workflows/flux-canon-gate.yml`
runs it on every push/PR. Read that doc next if you are building anything
that trusts a hash.

## For agents

- Writing a CANON.md? Run `lint.py --dir` against your fixture before
  pushing; the bidirectional-edge rule means the sibling repo usually needs
  its stub updated in the same window.
- Changing the schema or the rules? The contract tests in `test/test.js`
  are the spec — update them in the same commit, or CI is lying.
- Tempted to relax a check because a true statement failed it? Don't. File
  the case in the question pool instead (see `AI-Writings` @
  `quilted-reality`, `QUESTION-POOL.md`).
