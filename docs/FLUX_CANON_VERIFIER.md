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

---

## BUILT status — P0 complete (2026-09-20, lane flux-verifier-p0)

### What exists now

| Piece | Where | Commit |
|-------|-------|--------|
| Vendored PR #4 interpreter (fuel governance: capability-gated FUEL_SET default-deny, ExitReason enum, per-instruction meter). Byte-identical, sha256 `776388d5…6238`, pinned in `flux_verifier/__init__.py`. | `flux_verifier/interpreter.py` | `1d88077` |
| Serializer port, verbatim from quilt-live-canon-pypi @ b14a821 (branch canon-canonical-sync). Known-answer contract cell + FNV-1a 64-bit. | `flux_verifier/canon_serializer.py` | `a6ee8c9` |
| Module codegen + frozen `canon_verify.fxu` (contract cell, 65 bytes in). SPEC = codegen + pinned interpreter, not one frozen byte string — see constraint log. | `flux_verifier/fxu_codegen.py`, `flux_verifier/canon_verify.fxu` | `a6ee8c9` |
| Host embedding + self-test (12 checks, all pass). `allow_fuel_set=False`; fuel host-set; exact step self-measurement. | `flux_verifier/host.py`, `test/test_flux_verify.py` | `9ef31b3` |
| lint `--verify-flux`: pinned contract cell + seeded sample through the sandbox; honest SKIP when tooling absent; green with and without the flag. | `fleet-canon/lint.py` | `c45dbe5` |

**P0 conformance claim:** the module reproduces `0xe435d91d6d92a1d8` for `serialize_cell(1, list(range(1,17)), [2,3,4])` on the pinned interpreter, fuel-accounted (table below), and the reproduction is proven against escape attempts.

### Fuel accounting — contract cell (65-byte input)

| Quantity | Value |
|----------|-------|
| Module bytecode | 8771 bytes, sha256 `5e12a594b9f009010018e9dd2a525ee31f728de550942f37e7f7efe85e88568f` |
| Exact metered instructions (fuel=0 measurement) | 3400 = init 8 + 65 bytes × 52 + 4×(ESCAPE+POP) FUEL_CHECK overhead 8 + output loads 4 (HALT unmetered, excluded from run()'s count) |
| Host budget (lint default) | 34000 = 10× measured steps (design's 100× was sized for the 71-paper corpus; single-cell headroom documented rather than silently inherited) |
| Consumed / left | 3400 / 30600 |
| Boundary: budget == 3400 | OUT_OF_FUEL on the last metered op — the killing instruction **executes** (fuel is decremented after op execution; death lands when the meter hits exactly 0), HALT never reached, 3400 steps counted |
| Boundary: budget == 3401 | Clean HALT, 1 fuel to spare |
| Infinite loop, budget 1000 | OUT_OF_FUEL at exactly 1000 executed JMPs, steps == fuel |
| FUEL_SET escape attempts | all trapped: denied under default-deny (`FuelSetDenied`, trap leaves exit_reason RUNNING); raise-attempt and 0-attempt (the "unlimited" hatch) both `FuelSetViolation` under a granted VM with an active budget; lowering (1000→50) honored and then metered to death at 50 steps |

Governor semantics that matter for hosts (read from the vendored source, not the draft): HALT never meters and is excluded from `run()`'s step count; the OUT_OF_FUEL killing instruction is included. Fuel enforcement is the per-instruction meter — FUEL_CHECK is advisory/observability only, so draft §9.1 liveness compliance cannot be what keeps you safe.

### Interpreter-vs-draft discrepancy log (encoding: interpreter wins, always)

| # | Topic | ISA v3 draft (`isa-v3-draft.md`) | Reference `interpreter.py` (PR #4, wins) |
|---|-------|----------------------------------|------------------------------------------|
| 1 | Machine model | 256-GPR register machine | Pure stack machine |
| 2 | Encoding | 2-byte compressed + 4-byte | 1-byte opcode + immediates (PUSH u32, LOAD/STORE u16 addr) |
| 3 | HALT opcode | 0x01 | 0x00 |
| 4 | NOP opcode | 0x00 | 0x01 |
| 5 | FUEL_CHECK | core 0x09 (§9 mentions 0x60) | escape `0xFF 0x01 0x01` (FUEL op only in trace logs) |
| 6 | FUEL_SET | core 0x61, register operand | escape `0xFF 0x02 0x05` + u16 imm; capability-gated, monotonic-lower |
| 7 | LOAD/STORE | rd, rs1, imm8 addressing | u16 absolute only, 0x40/0x41; **STORE truncates to 16 bits** — no 8/32-bit store exists |
| 8 | Immediate load | LOADI 0x05 imm16 | PUSH 0x55 imm32 |
| 9 | JMP | 0x40 rel imm8 | 0x50 abs u16 |
| 10 | Doc accuracy | — | Interpreter docstring claims "44 core opcodes … aligned to Draft" — overstates; use this table |

Constraint #7 is the one that shaped the build: 64-bit FNV runs as 4×u16 limbs (addresses 200–219, double-buffered per byte), and every 32-bit intermediate (carries, `a0*p2` cross terms) lives on the stack only — no wide value ever round-trips through data memory. The draft's register file would have made this trivial; the stack machine makes it honest.

### What remains

- **P2 — escape extension `0xFF 0x80` CANON_DIAL_FMA:** the draft's escape space is real in the interpreter (`ESCAPE_PREFIX 0xFF`, `_dispatch_extension`), but adding a sub-opcode means forking the vendored interpreter — by the vendoring rule that fork must come with its own conformance test and a pin update.

---

## BUILT status — P1 complete (2026-09-20, lane flux-fabric-p1)

### What exists now (stacked on P0)

| Piece | Where | Commit |
|-------|-------|--------|
| Length-parameterized buffer zone: legacy placement kept for any input that fits below address 200 (P0 module + pin byte-identical, verified); larger inputs relocate the limb buffers 8-aligned above the input. MAX_INPUT 192 → 65000. | `flux_verifier/fxu_codegen.py` | `79eceb3` |
| Host memory sized per input; explicit run() ceilings so fuel — never the max_steps bug-guard — is the binding constraint at fabric scale. | `flux_verifier/host.py` | `79eceb3` |
| Corpus adapter + bundled snapshot: line-anchored worker.js parser, snapshot in the source repo's data.json shape (`canon_71.json`), cell construction byte-exact with worker stateHash (neighbors = ref_papers only). Triple-verified vs worker.js, pypi data.json, and the target hash. | `flux_verifier/corpus/` | `0eabfdb` |
| Fabric verifier: sandboxed module over the 2927-byte corpus fabric → HALT hash compared vs CANON_TARGET; drift = FluxVerifyError (lint discipline). | `flux_verifier/fabric.py` | `42a177d` |
| Proof certs: per-paper module SHA-256 (earned by fuel-bounded vm runs), fabric module cert, integrity recompute, CANON.json with certs at `verified.flux_proof`. | `flux_verifier/proof_certs.py`, `flux_verifier/proof_certs.json`, `CANON.json` | `42a177d` |
| Tests: 18/18 pass (P0's 12 + corpus adapter, fabric vm, fabric fuel boundaries, cert integrity + tamper detection). | `test/test_flux_verify.py` | this PR |

**P1 conformance claim:** the module reproduces `0x445185a3a99fd2e7` for the 71-paper fabric (2927 bytes) on the pinned interpreter, fuel-accounted (table below), verified against both the Python reference and the recorded target.

### Fuel accounting — 71-paper fabric (2927-byte input)

| Quantity | Value |
|----------|-------|
| Fabric input | 2927 bytes = 71 cells (ids 408..478; 1 cell with a neighbor list: 425 → [426,427]) |
| Module bytecode | 392991 bytes, sha256 `9f48f433fa9aa43780c2ba1d358998411df8bbf001eb38d139e8cac122702af6` |
| Exact metered instructions (fuel=0 measurement) | 152580 |
| Host budget | 15258000 = **100× measured** — the design's corpus headroom, measured on the corpus itself; P0's 10× single-cell budget was NOT silently inherited |
| Consumed / left | 152580 / 15111420 |
| Boundary: budget == 152580 | OUT_OF_FUEL on the last metered op — 152580/152580 executed, fuel 0, HALT never reached |
| Boundary: budget == 152581 | Clean HALT, hash reproduces target, 1 fuel to spare |

### Proof certificates

Per-paper certs (71) bind `number → n_bytes → module_sha256 → cell_hash`, every
number earned in the sandbox (fuel-bounded vm run per paper, 10× headroom,
4096 floor — the host.verify_cell rule). Integrity is pure recomputation from
corpus + codegen (`check_cert_integrity`), verified clean and tamper-tested.
Module SHA-256 is length-parameterized by design (the module IS the serializer
spec for a given input length); content binding is carried by `cell_hash` and
the fabric state hash. The org had no prior CANON.json shape, so
`build_canon_json()` mirrors the fleet CANON.md field names and nests the
certs at `verified.flux_proof` — the exact field path the design names.

### Corpus provenance

`SuperInstance/quilt-live-canon @ canon-71-full-corpus`, commit `371e07d`
(bundled CANON in worker.js; live hash equals the target by construction,
guarded upstream by test/canon-hash.test.mjs). Snapshot regeneration:
`python3 -m flux_verifier.corpus._regen path/to/worker.js`.
