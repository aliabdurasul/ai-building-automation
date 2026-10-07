# S6 — Revision / Regeneration Engine — Report

## S6 RESULT: FULL PASS

Two clean, independent runs (`run1`, `run2`) of `phase0\s6\harness\run_s6.ps1` passed every step (68 steps each:
66 PASS, 2 INFO, 0 FAILED/BLOCKED/NOT_RUN, every process exit code 0). `compare_s6.py run1 run2` gives
**DETERMINISTIC** over 399 semantic items, with 0 differences
(`docs/phase0/S6_comparison_run1_run2.json`). `.project`/`.app` bytes differ between runs, which the spec allows.

Each run takes the canonical model through the full lineage, and every accepted revision is deployed to the local CODESYS
SoftPLC runtime and verified with external pymodbus plus a PLC-side online read-back:

| Step | Revision | Content | Deploy chain |
|---|---|---|---|
| V1 | r001 | FanRunning BOOL DI, SupplyTemp REAL32, FanSpeed REAL32 (+ S1 Command/Status, Setpoint, REAL32 test signal) | PASS, 7/7 verified |
| V2 | r002 | + ReturnTemp | PASS, 8/8 verified |
| rollback | r001 again | V2 → V1, regenerated from stored inputs | PASS, 7/7 verified, identical to r001 |
| invalid | — | 11 invalid revisions | all REJECTED, store intact |
| V3 | r003 | − FanSpeed | PASS, 7/7 verified |
| V4 | — | SupplyTemp REAL32 → INT16 | REJECTED (policy A: TYPE_CHANGED is breaking, needs approval) |
| V5 | r004 | + equipment AHU-02 (Setpoint REAL32 HR, Enable BOOL coil) | PASS, 9/9 verified |
| V6 | — | direction changes | breaking one REJECTED; non-breaking one ACCEPTED in dry-run with mapping PRESERVED |

Evidence:

- Run staging: `C:\AI_BMS_PHASE0\s6\{run1,run2}`.
- Repository copies: `docs/phase0/s6_evidence/{run1,run2}`. These hold the immutable store, all check results, and every deploy chain's engineering, generated, logs and evidence.
- Development runs: `dev1`, `dev2`. dev1 hit the bridge race described in LIMITATIONS; dev2 was a full PASS.

## Architecture

```
CANONICAL MODEL (phase0/s6/model/revisions/*.json, generic: no CODESYS / byte-order facts)
  -> REVISION ENGINE   phase0/s6/engine/revision.py   identity, diff, breaking-change policy
  -> VALIDATOR         S3 validator (structural rules) + revision checks (metadata, parent, equipment, duplicates)
  -> MAPPING ALLOCATOR revision.allocate_with_lock     lock-aware, never reuses retired addresses
  -> GENERATOR         phase0/s6/generator/regenerate.py (S3 ST/mapping/plan generators, pure function)
  -> VENDOR ADAPTER    target profile phase0/s6/model/target_codesys_softplc.json + S1-FIX CODESYS scripts
  -> CODESYS           create/build, verify, deploy (ScriptEngine, --noUI), S3 online bridge
```

- The canonical model contains no CODESYS project names, channel layouts or REAL32 word order. Platform facts (register capacity, coil/DI overlay rule, unsupported features, CODESYS profile) live in the separate target profile.
- The REAL32 order is **measured** at runtime and checked against the S3 measured reference, `docs/phase0/s3_evidence/run2/types/logs/typed_verify.json`, which records CDAB. It is never written into the model.

### Revision metadata (backward-compatible with S3)

Every model has `schema: ai_bms.engineering_model.v1`, `project_id`, `revision` and `parent_revision`. The S3 signal format
is unchanged (`tag`, `datatype`, `direction`, `modbus.area`, optional `address`/`length`). Additions:

- `equipment` list;
- `equipment` on each signal;
- optional `symbol` (a globally unique PLC-level name, e.g. `AHU02_Setpoint`);
- optional `approvals`.

### Identity

The identity is `project_id/equipment/tag`, e.g. `AHU-DEMO/AHU-01/SupplyTemp`. It is deterministic and contains no UUIDs.
Equipment identity is `project_id/equipment`.

### Revision rules

- A new revision must be `max(accepted) + 1`.
- Its `parent_revision` must be an accepted revision.
- Its `project_id` must match the store.
- The allocation history used for revision N is every accepted revision `< N`, so a stored revision always reproduces bit-for-bit.

### Immutable store

```
<run>/engineering/revisions/rNNN/{model,target,validation,revision_diff,allocation,modbus_mapping,codesys_plan,manifest}.json
<run>/generated/revisions/rNNN/plc/{PLC_PRG.st,PLC_PRG_decl.st,PLC_PRG_impl.st,PLC_VARIABLES.txt}
<run>/engineering/revisions/rejected/<label>/   (model + validation + diff of every rejected attempt)
<run>/engineering/revisions/attempts/<label>/   (dry-run results; never accepted)
<run>/engineering/revisions/index.json          (revisions + manifest sha256, rejected, current, events)
```

- Revisions are written once, via a temp directory plus rename.
- `manifest.json` holds the sha256 of every file, and every read verifies it.
- A second commit of an existing revision number is REJECTED with code `STORE` ("revisions are immutable").
- Deploy stages are written only into an empty directory, so nothing is silently overwritten.

## V1

`v1.json` → r001. Allocation, with every mapping action NEW:

| Signal | Address |
|---|---|
| Command | HR0 (pinned S1 word; bits StartCommand, StopCommand) |
| Setpoint REAL32 | HR1–2 |
| Status | IR0 (pinned; bits FanCommand, FanRunning, FanFault) |
| FanSpeed REAL32 | IR1–2 |
| SupplyTemp REAL32 | IR3–4 |
| TestReal32Read REAL32 | IR5–6 |
| FanRunning BOOL | DI144 (overlays IR9, PLC bit 8) |

Runtime results:

- CODESYS create/build: 0 errors, 0 warnings. Verify, deploy and RUN all succeeded.
- S1 regression: PASS.
- Typed verification: 36 cases PASS.
- 7/7 signals `verified:true`.

## V2

`v2.json` (rev 2, parent 1) adds ReturnTemp, which is placed at **IR7–8**. That is the lowest run never owned by any identity. All 7
existing mappings are **PRESERVED**.

Without the lock, the S3 allocator alone would have moved SupplyTemp from IR3 to IR5, TestReal32Read from IR5 to IR7, and put
ReturnTemp at IR3 instead of IR7. The stability check records this. Runtime: typed verification 44 cases PASS, 8/8 verified.

## V3

`v3.json` (rev 3, parent 2) removes FanSpeed. Diff: `REMOVED` / mapping `RETIRED`.

- IR1–2 is recorded in `allocation.retired` as "reserved for this identity; never assigned to another identity" (`last_active_revision 2`).
- The other 7 mappings are PRESERVED.
- Runtime: 36 cases PASS, 7/7 verified.

## V4

`v4_type_change.json` changes SupplyTemp from REAL32 to INT16. The diff reports `TYPE_CHANGED`, breaking=true.

**Chosen policy: (A) BLOCK, with explicit engineer approval.**

- Without approval, the revision is REJECTED with `BREAKING_CHANGE_REQUIRES_APPROVAL`: "AHU-DEMO/AHU-01/SupplyTemp: TYPE_CHANGED 'REAL32' -> 'INT16' is a breaking change; add approvals [...]". Accepted revisions are unchanged.
- With approval (`v4_type_change_approved.json`, `approvals: [{identity, change: TYPE_CHANGED}]`), the engine reallocates option-(B) style. The identity gets a new address, and its old cells stay reserved as retired.
- On this target, the approved revision is REJECTED with `ALLOCATION`: "SupplyTemp: no 1 free register(s) left in INPUT_REGISTER (capacity 10)". That is correct, because every IR cell is either active or retired:
  - IR1–2: retired FanSpeed
  - IR3–4: SupplyTemp's own old cells, retired by the reallocation
  - IR9: the DI overlay
- `test_revision.py` proves the successful reallocation path on a wide target (`test_approved_type_change_reallocates`).

Rationale for A: a datatype change silently reinterprets the same registers for every SCADA/BMS client. An engineer must
approve it, and an approved change must never reuse the old address.

## REVISION DIFF

`engineering/revisions/rNNN/revision_diff.json` holds:

- per-identity changes, each with `type`, `from`/`to`, `field_changes`, `breaking`, `approved` and mapping `action`/`from`/`to`;
- `equipment_changes`, `variable_changes` and `summary`.

Change types: ADDED, REMOVED, UNCHANGED, TYPE_CHANGED, DIRECTION_CHANGED, AREA_CHANGED, ADDRESS_CHANGED,
ATTRIBUTE_CHANGED, EQUIPMENT_ADDED, EQUIPMENT_REMOVED. Mapping actions: PRESERVED, NEW, RESTORED, REALLOCATED, RETIRED.

For each accepted revision, `revision_checks.py diff` checks the metadata, an **independent recomputation** of the change
types, and the scenario expectations (`phase0/s6/model/scenario.json`):

| Revision | Summary | Check |
|---|---|---|
| r001 | 7 ADDED, 1 EQUIPMENT_ADDED | PASS |
| r002 | ADD case: 1 ADDED (ReturnTemp, NEW), 7 UNCHANGED (PRESERVED) | PASS |
| r003 | REMOVE case: 1 REMOVED (FanSpeed, RETIRED), 7 UNCHANGED | PASS |
| r004 | EQUIPMENT case: EQUIPMENT_ADDED AHU-02, 2 ADDED (NEW), 7 UNCHANGED | PASS |

Direction changes:

- **Same area** (V6 non-breaking, AHU-02 Setpoint READ_WRITE → WRITE): `DIRECTION_CHANGED`, breaking=false, mapping PRESERVED at HR3–4. Dry-run ACCEPTED and the store was untouched.
- **Area change** (V6 breaking, SupplyTemp READ → READ_WRITE): `DIRECTION_CHANGED` with field changes direction READ→READ_WRITE and area INPUT_REGISTER→HOLDING_REGISTER, breaking=true. REJECTED with `BREAKING_CHANGE_REQUIRES_APPROVAL`.

## MAPPING STABILITY

Lock-aware allocation (`allocate_with_lock`) assigns every signal one of these actions:

- **PRESERVED**: the same identity with the same datatype and area keeps its exact address.
- **RESTORED**: an identity seen in an earlier revision gets its last address back.
- **NEW**: the lowest free run, using the S3 rule.
- **REALLOCATED**: only for an approved breaking change.

Every cell owned by any identity in any earlier accepted revision is reserved for that identity, so a retired address is never given to another
signal. `revision_checks.py stability` verifies, for 1→2, 2→3 and 3→4, that:

- unchanged identities keep area, address and length, both in the store and in the **runtime-verified** deployed mappings;
- new mappings avoid every address owned by another identity;
- new mappings take the lowest free run.

All three transitions PASS in both runs. In V5, AHU-01 is completely preserved, and AHU-02 is allocated deterministically:

- Setpoint at HR3–4, the lowest free run;
- Enable at COIL 144, which overlays HR9 bit 8 (the bit block from the top, as in S3).

## BREAKING CHANGE

Breaking changes are datatype changes, area changes (including direction changes that force a new area) and explicit address changes. They are BLOCKED
unless approved; when approved they are REALLOCATED and the old address is RETIRED. Measured outcomes: V4 TYPE_CHANGED → REJECTED;
V4 approved → reallocation attempted → REJECTED on real capacity; V6 DIRECTION_CHANGED with an area change → REJECTED.
Every rejection leaves the accepted revisions byte-identical (snapshot check) and is recorded in `index.rejected` and
`revisions/rejected/<label>/`.

## ROLLBACK

`regenerate.py rollback --to 1` performs these steps:

1. Regenerates r001 from its stored model, target and history.
2. Checks that all 11 artifacts are semantically identical to the stored r001.
3. Writes them to a fresh deploy stage.
4. Records an index event `{rollback, from: 2, to: 1}` and sets `current=1`.

The rollback stage then runs through CODESYS create/build, verify, deploy, the S1 regression and typed verification.
`revision_checks.py rollback-compare` compares that stage against the original r001 stage and passes all 7 checks:

- engineering artifacts identical;
- PLC source identical;
- verified mapping identical;
- all signals verified after the rollback;
- CODESYS and runtime results identical, including the create/verify/deploy/S1/typed results and all 36 typed cases;
- rollback runtime PASS;
- index rollback event present.

V3 then continues from parent 2. The rollback does not delete r002, because history stays append-only.

## INVALID MODEL

`revision_checks.py invalid` builds each case from `v2.json` with revision max+1. Every case is **REJECTED**, with process exit
21 and operation REJECTED. Afterwards the store is unchanged and the previous valid revision (r002) still reproduces:

| Case | Code | Message excerpt |
|---|---|---|
| duplicate tag | DUPLICATE_TAG | duplicate tag ReturnTemp in equipment AHU-01 |
| duplicate address | ALLOCATION | INPUT_REGISTER 3..4 overlaps ['ExhaustRaw'] |
| REAL32 length=1 | MODEL_RULE | REAL32 requires length=2, model has length=1 |
| missing datatype | MODEL_RULE | missing datatype |
| missing area | MODEL_RULE | missing area |
| invalid direction | MODEL_RULE | missing/unsupported direction 'BIDIRECTIONAL' |
| direction/area mismatch | MODEL_RULE | READ signal must use INPUT_REGISTER/DISCRETE_INPUT |
| overlapping REAL32 | ALLOCATION | overlaps ['MixedAirTemp'] |
| capacity exceeded | ALLOCATION | no 2 free register(s) left in INPUT_REGISTER (capacity 10) |
| revision already exists | STORE | revision 2 already exists; revisions are immutable |
| unknown parent | STORE | parent_revision 99 is not an accepted revision |

## DETERMINISM

- **Within a run:** `revision_checks.py repro` regenerates every accepted revision (r001–r004) twice. Both copies are identical to each other and to the store (11 artifacts each), and the store integrity check passes: manifests, no extra files, index sha256, no temp directories.
- **Engine:** the `test_revision.py` determinism test runs 20 shuffled signal orders and produces identical allocation, diff and mapping each time.
- **Run to run:** run1 and run2 are semantically identical across 399 items:
  - the store file list and every store artifact of r001–r004;
  - rejected and dry-run attempts, and the index;
  - every check result;
  - every deploy chain's engineering files, generated ST and PLC_VARIABLES hashes, CODESYS create/verify/deploy results, S1 regression, typed cases, measured ordering and verified mapping;
  - the step status vector.

`.project`/`.app` bytes differ, which is not required to match.

## S1 REGRESSION

This passed in all 5 deploy chains of both runs (r001, r002, rollback_r001, r003, r004), using `phase0/s6/probe/s1_regression.py`:

- **Start:** HR0=1 → IR0=3. Named status bits FanCommand=1, FanRunning=1, FanFault=0, taken from the mapping's `bits`. FanRunning DI144 = True.
- **Stop:** HR0=2 → IR0=0. All bits 0; DI144 = False.

## REAL32 REGRESSION

TestReal32Read is injected on the PLC with 21.5, 22.0, 18.25 and 123.456, then read through FC4. Setpoint, and in r004 also AHU02_Setpoint, are written with the same four values via FC16 and read back
both from the PLC and through Modbus.

Raw registers observed:

| Value | Registers |
|---|---|
| 21.5 | [0, 16812] |
| 22.0 | [0, 16816] |
| 18.25 | [0, 16786] |
| 123.456 | [59769, 17142] |

Results:

- The ordering is determined from the samples as **CDAB** in every deploy chain, and `real32_ordering_matches_reference` = true against the S3 measured fact. Tolerance is bit-exact float32.
- The model contains no byte or word order. The mapping's `measured_ordering` is filled only from the runtime measurement.

## CODESYS

CODESYS 3.5.22.30 ScriptEngine, run with `--noUI` and no GUI automation. The S1-FIX adapter scripts are reused unchanged. Each chain:

1. Create project, Modbus TCP server, channel mapping and build: 0 errors, 0 warnings.
2. Fresh-process verify: device tree, channels, IO mappings, PLC_PRG declarations and implementation, no missing variables, rebuild.
3. Deploy preflight.
4. Download and start. Application state `run`; generated variables readable online; tcp/502 owned by the runtime service.

Project names are per revision (`AI_BMS_S6_rNNN.project/.app`). Staging is under `C:\AI_BMS_PHASE0\s6\<run>\deploy\<label>`.

## RUNTIME

- Local CODESYS Control Win V3 x64 SoftPLC (demo mode); the physical PLC was not touched.
- Credentials were read only from process environment variables, set for the harness process and removed afterwards. They are never logged.
- The runtime application was replaced with the user's consent (`S1FIX_REPLACE_RUNTIME_APP=1`).
- The demo runtime stops after about 2 h. The user restarted the service as Administrator before the dev2/run1/run2 window; nothing was bypassed.

## PYMODBUS

External pymodbus client on 127.0.0.1:502, unit 1, using FC1, FC2, FC3, FC4, FC5, FC6 and FC16.

- PLC-side values come from the S3 online bridge (CODESYS ScriptEngine online read and write).
- `verified:true` is set only after a signal passes every runtime case. Every signal of every deployed revision ends up verified (7 / 8 / 7 / 7 / 9).

## Statuses

| Status | Where |
|---|---|
| VERIFIED | every signal of r001, r002, rollback r001, r003, r004 after runtime verification (deploy-stage `modbus_mapping.json`) |
| GENERATED | store artifacts in `engineering/revisions/rNNN` (`verified:false` there by design; the store is immutable) |
| REJECTED | 11 invalid revisions, V4, V4-approved (capacity), V6-breaking |
| UNMAPPED | HeatingValve (PLC variable without a Modbus signal), listed in `mapping.unmapped` |
| UNSUPPORTED | DistinctBitAreas=TRUE; more than 10 registers per area; PLC-originated READ_WRITE HR value visible to FC3 (all measured in S3, carried in the target profile) |

## Changes to earlier stages

- `phase0/s3/engine/canonical.py` `allocate()`: pinned bits are now placed before auto registers, so a pinned DI overlay register can no longer be taken by an auto REAL32. Verified that the 26 S3 engine tests pass and that regenerating the S3 `types`/`ahu` profiles gives byte-identical `PLC_PRG_decl/impl.st`, `allocation.json` and `codesys_plan.json` versus S3 run2. S3 mapping behaviour is unchanged.
- `phase0/s3/probe/typed_verify.py` `Bridge.call`: retries reading a bridge response that Windows reports as briefly locked (PermissionError) right after its rename. The verification logic is unchanged. This fixed the dev1 r003 failure.

## LIMITATIONS

- The approved type change (V4-approved) is proven to reallocate only on a wide target in the unit tests. On the real 10+10 register target it is correctly rejected for capacity, so no approved reallocation was deployed to the runtime.
- The V6 non-breaking direction change was checked as a dry run and not deployed, so the accepted revision chain stays r001–r004.
- Byte equality of `.project`/`.app` is not achieved and not required; their hashes are reported for information only.
- The demo runtime limit (about 2 h) requires a manual Administrator service restart; nothing is automated around it.
- Register capacity remains 10 HR + 10 IR (an S3 measured platform limit), which constrains reallocation headroom.

## NEXT: S2
