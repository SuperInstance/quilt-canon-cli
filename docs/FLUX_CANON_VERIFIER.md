# FLUX Canon Verifier — Design Sketch

*CCC, 2026-09-20. Status: proposal. Grounds: SuperInstance/ability-transfer @ isa-v3-draft (verified same day).*

## Problem

canon-lint (this repo, `fleet-canon/lint.py`) has two holes:

1. **Three ad-hoc harnesses.** Canon hash verification — the canonical serializer from
   dial vectors to the 64-bit state hash — is reimplemented per substrate
   (Rust test, Python test, JS test). They agree today by discipline, not by construction.
2. **No trust boundary.** lint fetches remote CANON.md/CANON.json and evaluates it
   in-process. A hostile or broken submission runs next to the linter with full privileges.

FLUX ISA v3 (ability-transfer) exists precisely for this: *agents execute untrusted code;
the ISA must protect the host* (P4 — security by default), and *fuel budgets are
architectural primitives* (P5 — temporal awareness).

## Design

Canon verification is a pure, deterministic, fuel-bounded computation — the ideal
first FLUX production consumer.

```
┌─────────────────────────────────────────────────────┐
│  canon-lint                                         │
│    │                                                │
│    ▼                                                │
│  ┌──────────────┐    CAP(read: candidate bytes)     │
│  │ FLUX sandbox │ ◀──────────────────────┐          │
│  │ reference/   │                        │          │
│  │ interpreter  │    FUEL_CHECK @ loops  │          │
│  └──────┬───────┘                        │          │
│         │ HALT {hash, status}            │          │
│         ▼                                │          │
│  compare vs CANON_TARGET ────────────────┘          │
└─────────────────────────────────────────────────────┘
```

### Module: `canon_verify.fxu`

- **Input:** the dial/cell list (16×Q1.15 vector for kernels; paper list for the canon fabric).
- **Body:** the canonical serializer — FNV-1a 64-bit chaining + exact integer ops
  (already ℚ-exact; no float anywhere near identity, per quilt-cell house rule).
- **Ops:** LOAD/STORE, integer arithmetic, FUEL_CHECK at every loop head, HALT.
  No I/O opcodes. No SENDMSG/RECVMSG. The module cannot touch the network by construction.
- **Output:** `{state: u64, status: u8}` in registers, read by the host after HALT.

### Host embedding (lint.py side)

- Embed `ability-transfer/reference/interpreter.py` (vendor, like the quilt kernel
  vendored byte-identical into hermit — same pattern, same discipline).
- Grant exactly one capability: `CAP_INVOKE(read, candidate_bytes)`. No fs, no net.
- `SANDBOX_ENTER` before load, `FUEL_CHECK` budget sized to the corpus (71 papers ×
  serializer cost ≈ tiny — budget 100× headroom, fail-loud on exhaustion).
- On HALT: compare register state against `CANON_TARGET` (0x445185a3a99fd2e7 for the
  71-paper fabric). Mismatch = drift, reported exactly like today's lint drift check.

### If the base ISA lacks an op

Use the escape space (0xFF-prefix sub-opcodes, 65,280 slots). One reserved family,
e.g. `0xFF 0x20+` FUTURE_SECURITY or a custom `0xFF 0x80` CANON_DIAL_FMA. This is
deliberately the first real exercise of the escape mechanism — a single-spec extension
with a conformance test, not a fork of the ISA.

## Wins

| # | Win | Replaces |
|---|-----|----------|
| 1 | One bytecode module = one spec. Module hash IS the serializer spec. | 3 substrate harnesses kept in agreement by discipline |
| 2 | Untrusted submissions verify inside a sandbox with a fuel budget. | lint evaluating remote content in-process |
| 3 | FLUX Path B (VM proofs) finally gets a production consumer; SHA-256 proof certificate from `to_bytecode()` attaches per verified canon. | proofs that never ran (fleet memory: FLUX audit, Path A vs B) |

## Build order (one evening each)

1. **P0 — conformance:** vendor interpreter; compile the 16-dial serializer to
   `canon_verify.fxu`; assert module reproduces `0xe435d91d6d92a1d8` (known test cell).
2. **P0 — lint wiring:** lint gains `--verify-flux` flag; sandboxed verify on the Tier-1
   roster; fuel budget enforced.
3. **P1 — 71-paper fabric:** serializer for the full canon cell list → 0x445185a3a99fd2e7.
4. **P1 — proof certificates:** `to_bytecode()` SHA-256 recorded per repo CANON.json
   (`verified.flux_proof`), so provenance survives independent of any host.
5. **P2 — escape extension:** if a dial op is missing from base ISA, spec `0xFF 0x80`
   family + conformance test.

## Honest risks

- Interpreter is single-file Python reference — perf is irrelevant here (verification
  is tiny) but DoS-resistance depends on FUEL_CHECK being unavoidable, not advisory.
  Verify: attempt an infinite loop, confirm exhaustion kill.
- ISA v3 is a draft; op encodings may move. Mitigation: pin the interpreter by hash
  in this repo, same as the kernel vendoring rule.
- This is the *third* substrate for the serializer. The difference: the other two
  remain as reference ports; FLUX becomes the conformance oracle. If FLUX v3 drifts,
  the oracle moves with a pinned hash, not with three silent copies.
