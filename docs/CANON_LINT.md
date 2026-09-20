# Canon Lint — the contract as prose

This page explains what `tools/canon_lint.mjs` checks and *why*, for humans
landing here from a PR check and for agents deciding whether a new paper
belongs in the corpus. If you only read one file in this repo, read this one.

## What a canon paper is

The fleet's canon corpus lives in `canon/` — one JSON file per paper. Each
paper declares a mission, a list of claims, edges to other papers, and a
content-addressed identity (a hash over its load-bearing fields). Canon lint
is the referee that keeps those declarations structurally honest. It is a
*parse-time* referee: it checks what the paper *says*, not what the paper
*proves*. (The proving layer is the FLUX canon verifier — see
"Springboard" below.)

## The rules, and the failure each one prevents

1. **Every edge must be bidirectional.** If paper A links paper B, paper B
   must link A back. *Failure prevented:* a one-way edge is a claim the
   target never agreed to — the graph quietly becomes a broadcast, not a
   conversation. In CI this is a **build failure**, not a warning.
2. **Every paper declares exactly one mission sentence.** Not zero (a paper
   with no thesis is a footnote pretending to be a chapter), not three
   (three theses is a bibliography). The check is deliberately cheap — and
   it once rejected a *true* mission because the string "Q1.15" contains a
   period. That rejection is recorded in the question pool as "validators
   should parse sentences, not count periods": cheap proxies are honest
   until they aren't, and this one is due for an upgrade that doesn't
   overfit.
3. **Hash declarations are well-formed.** A paper that names its hash must
   name it in the declared format. Hash *correctness* (does the declared
   hash match the content?) is the verifier's job, not lint's.
4. **Provenance is classified, not assumed.** The `classifyTargetProvenance`
   pass (ported from quilt-studio) labels each hash target
   `live | reachable | stranded | unknown`. A canon may be internally
   perfect and still point at nothing — the stranded label is how the fleet
   keeps monuments and drift apart.

## Source of truth

The deployed `quilt-live-canon` worker is the live service of record; this
repo's `canon/` directory is the checked-in mirror that CI can referee.
When they disagree, the worker is *live* and the mirror is *behind* — the
fix is to re-sync the mirror, never to weaken the check. The drift table in
the worker's README records every historical mismatch and its resolution;
lint exists so that table stays short.

## How to run

```bash
node tools/canon_lint.mjs            # full lint of canon/
node --test test/canon_lint.test.mjs # the contract's own tests
```

CI runs both on every push and every pull request (`.github/workflows/canon-lint.yml`).

## Springboard: from parsing to proving

Lint answers "is the paper well-formed?" The next question is "is the paper
*right*?" — and answering it inside the fleet's own sandbox is the point of
`docs/FLUX_CANON_VERIFIER.md`: a fuel-bounded FLUX module recomputes each
paper's declared hash under an auditable instruction budget, so a canon
hash stops being a string a paper *asserts* and becomes a value the
substrate *reproduces*. Read that doc next if you are building anything
that trusts a hash.

## For agents

- Adding a paper? Run lint locally first; the bidirectional-edge rule means
  you usually need a sibling PR in the repo of the paper you link.
- Changing the schema? The rule tests in `test/canon_lint.test.mjs` are the
  contract — update them in the same commit, or CI is lying.
- Tempted to relax a check because a true statement failed it? Don't. File
  the case in the question pool instead; a referee that lies to pass a true
  statement is worse than no referee.
