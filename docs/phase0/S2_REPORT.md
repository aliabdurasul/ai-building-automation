# S2 — Multi-Equipment Architecture Validation — Report

```
S2 RESULT:        FULL PASS
EQUIPMENT:        AHU-01, PUMP-01
AHU REGRESSION:   PASS
PUMP GENERATION:  PASS
PUMP BUILD:       PASS (0 errors / 0 warnings)
PUMP DEPLOY:      PASS
PUMP MODBUS:      PASS
PUMP REAL32:      PASS (PumpSpeed 50.0, Pressure 3.75 ... measured CDAB = S3 reference)
REVISION:         PASS (V2 ADD, V3 REMOVE, V4 breaking TYPE_CHANGE rejected)
DETERMINISM:      DETERMINISTIC (run1 vs run2, 367 semantic items, 0 differences)
CODESYS ADAPTER:  GENERIC
```

Two clean, independent runs (`run1`, `run2`) of `phase0\s2\harness\run_s2.ps1` passed every step:

- Each run has 80 steps: 78 PASS, 2 INFO, and none FAILED, BLOCKED or NOT_RUN.
- Every process exit code is 0.
- `compare_s2.py run1 run2` gives **DETERMINISTIC** over 367 semantic items, with 0 differences and nothing missing (`docs/phase0/S2_comparison_run1_run2.json`).
- `.project`/`.app` bytes differ between runs, which the spec allows.

The same pipeline (canonical model → revision engine / validator → mapping allocator → PLC generator → CODESYS adapter →
project → build → deploy → Modbus test) handled four applications in each run:

| Deploy chain | Canonical project | CODESYS project | Signals verified at runtime |
|---|---|---|---|
| `pump_r001` | PUMP-DEMO r1 (PUMP-01) | `AI_BMS_S2_PUMP_DEMO_r001.project` | 7/7 + 9 state-machine steps |
| `pump_r002` | PUMP-DEMO r2 (+FlowRate) | `AI_BMS_S2_PUMP_DEMO_r002.project` | 8/8 + 9 state-machine steps |
| `combined_r001` | BMS-DEMO r1 (AHU-01 + PUMP-01) | `AI_BMS_S2_BMS_DEMO_r001.project` | 12/12 + S1 regression + 9 pump steps + 6 isolation steps |
| `ahu_r001` | AHU-DEMO r1 (AHU-01) | `AI_BMS_S2_AHU_DEMO_r001.project` | 7/7 + S1 regression |

Evidence:

- Run staging: `C:\AI_BMS_PHASE0\s2\{run1,run2}`.
- Repository copies: `docs/phase0/s2_evidence/{run1,run2}`. These hold the three immutable stores, all check results, and every deploy chain's engineering, generated, logs and evidence.
- Development runs:
  - `dev1` ran offline without credentials. Every offline step and all 3 CODESYS builds passed; deploys were BLOCKED at the preflight, as designed.
  - `dev2` was a full PASS, the same 80 steps as run1 and run2.

## Architecture: where equipment knowledge lives

```
CANONICAL MODEL     phase0/s2/model/*.json          equipment, variables, signals, logic template selection
                                                    (no addresses except the pinned S1 words, no vendor facts)
LOGIC TEMPLATES     phase0/s2/logic/templates/*.json  equipment behaviour (ST body with {{slot}} placeholders,
                                                    typed slots, behaviour test) - AHU_S1FIX_V1, PUMP_BASIC_V1
REVISION ENGINE     phase0/s6/engine/revision.py    identity project/equipment/tag, diff, policy A, lock-aware allocation
GENERATOR           phase0/s6/generator/regenerate.py + phase0/s3/generator/generate.py  (pure functions)
TARGET PROFILE      phase0/s2/model/target_codesys_softplc.json  register capacity, overlay rule, CODESYS profile,
                                                    project naming "AI_BMS_S2_{project}_r{revision:03d}"
CODESYS ADAPTER     phase0/s1fix/codesys/{create_project,verify_project,deploy}.py   reads only codesys_plan.json
                                                    + generated ST; no equipment knowledge
```

- **Equipment behaviour is data, not code.** A model selects a template per equipment instance, `"logic": {"template": "PUMP_BASIC_V1", "bind": {"StartCommand": "PUMP01_StartCommand"}}`. Unbound slots default to the variable of the same name.
- **Template checks** (code `LOGIC_TEMPLATE`; failure rejects the revision):
  - the template exists;
  - it is made for the equipment type;
  - every slot is bound to a declared variable of the slot's PLC type;
  - a bound variable belongs to the same equipment (isolation);
  - no variable is driven by two instances;
  - free-text logic is not allowed in a templated model.
- **Templates are bundled per revision.** Each revision stores its templates, content plus sha256, in `engineering/logic_templates.json`, so reproduction never depends on template files that may change later. A unit test proves this: a modified template file changes nothing in a revision that is reproduced from its stored bundle.
- **The generator has no equipment branches.** It emits the Modbus image code generically per datatype/area, then the rendered template bodies in model equipment order. `engineering/logic_instances.json` records template, sha256, bindings and the behaviour test for the runtime probe.
- **Backward compatibility.** Models without templates (S3, S6) use the built-in S1 AHU logic exactly as before:
  - S3 `types` regeneration is byte-identical to S3 run2;
  - every S6 run1 store revision (r001–r004) reproduces PASS (harness step F00e);
  - the S6 self-tests still pass (F00c).
- **AHU template equivalence (F00g).** AHU-01 through `AHU_S1FIX_V1` gives exactly the S1/S3/S6 logic:
  - `PLC_PRG_impl.st` is byte-identical;
  - the declaration differs only in its title comment;
  - allocation and codesys_plan are identical except for the project name.

### CODESYS adapter: GENERIC

- The only adapter change in S2 was in `deploy.py`. Its online check used to read four hard-coded AHU expressions (`Mb_Command`, `Mb_Status`, `StartCommand`, `FanRunning`). It now reads every `io_mappings` variable plus the `required_variables` listed in the plan.
- Harness step F00f scans all adapter scripts (`create_project.py`, `deploy.py`, `discover_devices.py`, `verify_project.py`) for every equipment id, equipment type, tag, symbol and PLC variable of all six S2 models, using whole-word matching. It found **0 hits** among 26 names.
- A positive control proves the scanner actually detects such names: the same scan over `phase0/s3/generator/generate.py`, which contains the built-in AHU logic, finds hits.
- The F07 runtime verification in the harness is generic too: every Modbus image variable in the plan must be readable online (9, 11, 16 and 11 variables for the four chains).

## PUMP-01

The canonical model is `phase0/s2/model/pump_v1.json`, project `PUMP-DEMO`, equipment `PUMP-01` of type `PUMP`. It contains no addresses; the allocator chose all of them:

| Identity | Type | Direction | Allocated | Runtime verification |
|---|---|---|---|---|
| PUMP-DEMO/PUMP-01/StartCommand | BOOL | WRITE | COIL 144 (HR9 bit 8) | FC5 write → PLC `StartCommand`; behaviour |
| PUMP-DEMO/PUMP-01/StopCommand | BOOL | WRITE | COIL 145 (HR9 bit 9) | FC5 write → PLC `StopCommand`; behaviour |
| PUMP-DEMO/PUMP-01/PumpFault | BOOL | READ | DI 144 (IR9 bit 8) | Modbus == PLC; TRUE/FALSE in behaviour |
| PUMP-DEMO/PUMP-01/PumpRunning | BOOL | READ | DI 145 (IR9 bit 9) | Modbus == PLC; TRUE/FALSE in behaviour |
| PUMP-DEMO/PUMP-01/PumpState | INT16 | READ | IR 4 | Modbus == PLC; 0/2/9 in behaviour |
| PUMP-DEMO/PUMP-01/PumpSpeed | REAL32 | READ | IR 2–3 | PLC write 50.0, 21.5, 18.25, 123.456 → Modbus decode |
| PUMP-DEMO/PUMP-01/Pressure | REAL32 | READ | IR 0–1 | PLC write 3.75, 22.0, 18.25, 123.456 → Modbus decode |

**PLC generation.** `PLC_PRG.st`, `PLC_PRG_decl.st`, `PLC_PRG_impl.st` and `PLC_VARIABLES.txt` use only pump names:

- the declaration title is `PUMP-DEMO: PUMP-01 (PUMP)`;
- a unit test checks that no AHU name occurs in the pump ST.

**Build and deploy.**

- The ScriptEngine build gave 0 errors and 0 warnings, confirmed by an independent rebuild in `verify_project.py` (also 0/0).
- Deployed to the local CODESYS Control Win V3 x64: application in RUN, tcp/502 owned by the runtime.
- The PUMP project is a separate project and does not touch the AHU projects.

**Pump logic (`PUMP_BASIC_V1`).**

- `PumpState` codes: 0 STOPPED → 1 STARTING → 2 RUNNING → 3 STOPPING → 0, and 9 FAULT.
- Stop dominates start. PumpFault forces FAULT, and clearing the fault returns to STOPPED.
- This is a deterministic demo, not field pump control.

The template's behaviour test runs through Modbus (commands) and a PLC online write (fault injection). Every expectation is checked **both** through Modbus and by PLC online read-back:

| Step | Action | Expected and observed (Modbus = PLC) |
|---|---|---|
| initial_stopped | Start=F, Stop=F, PLC PumpFault=F | State 0, Running F, Fault F |
| start | Start=T | State 2, Running T |
| start_released_keeps_running | Start=F | State 2, Running T |
| stop | Stop=T | State 0, Running F |
| start_while_stop_held_is_ignored | Start=T | State 0, Running F |
| stop_released_starts | Stop=F | State 2, Running T |
| fault_while_running_start_held | PLC PumpFault=T | State 9, Running F, Fault T |
| start_released_in_fault | Start=F | State 9, Running F |
| fault_cleared_stopped | PLC PumpFault=F | State 0, Running F, Fault F |

**REAL32.**

- For PLC `PumpSpeed := 50.0`, Modbus IR2..IR3 reads `[0x0000, 0x4248]`, which decodes to 50.0.
- The samples from this run alone narrow the ordering to a single candidate, **CDAB** (123.456 is the informative value). CDAB equals the S3 measured reference, and the model does not contain it.
- Pressure (IR0..1) and FlowRate (r002, IR5..6) were verified the same way.
- After verification the mapping records `verified: true` and `measured_ordering: CDAB` for each REAL32 signal.

## AHU regression

- `ahu_r001` runs AHU-01 alone (`ahu_v1.json` = S6 V1 signal set through the `AHU_S1FIX_V1` template):
  - build 0/0, deploy, application in RUN;
  - **HR0=1 → IR0=3** (FanCommand and FanRunning set, FanFault clear) and **HR0=2 → IR0=0**; FanRunning DI144 follows;
  - typed verification of all 7 signals, with SupplyTemp, FanSpeed and TestReal32Read decoded as CDAB and the Setpoint REAL32 FC16 writes read back on the PLC.
- `combined_r001` contains AHU-01 next to PUMP-01. The same S1 regression passes on HR0/IR0, which stay pinned.
- Harness steps F00b (S3 engine, 26 tests), F00c (S6 revision engine, 23 tests) and F00e (S6 run1 store, r001–r004 reproduced twice each) all PASS.

## Equipment isolation (AHU-01 + PUMP-01 in one model and one application)

`combined_v1.json` (project `BMS-DEMO`) holds both equipment instances:

- **Identities.** Identities are `BMS-DEMO/AHU-01/...` and `BMS-DEMO/PUMP-01/...`.
- **Command names.** Both instances have `StartCommand`/`StopCommand` *tags*, with distinct identities. The PUMP commands carry explicit PLC symbols `PUMP01_StartCommand`/`PUMP01_StopCommand`, and the template binding maps the pump slots onto them.
- **Allocation.**
  - HR0 Command and IR0 Status are pinned.
  - Setpoint HR1-2; Pressure IR1-2, PumpSpeed IR3-4, PumpState IR5, SupplyTemp IR6-7.
  - PUMP coils C144/145; FanRunning DI144, PumpFault DI145, PumpRunning DI146.
- **Offline checks** (F03d, 12 checks):
  - identities and PLC symbols are unique;
  - every variable is owned by one equipment instance;
  - template bindings stay inside their equipment;
  - no variable is driven twice.
- **Mutation tests:**
  - the same tag (`Setpoint`) in both equipment instances is **ACCEPTED** with two distinct identities;
  - PUMP logic bound to an AHU variable is REJECTED (LOGIC_TEMPLATE, "equipment isolation");
  - a duplicate PLC symbol across equipment is REJECTED (DUPLICATE_SYMBOL);
  - a template for another equipment type is REJECTED;
  - an unknown template is REJECTED.
- **Runtime scenario** (`isolation_scenario_bms.json`, keys are identities, each step verified through Modbus and PLC read-back):
  1. reset;
  2. AHU start does not start the pump;
  3. pump start does not change the AHU;
  4. AHU stop does not stop the pump;
  5. pump fault does not change the AHU;
  6. cleanup.
  
  All 6 steps passed, and the pump template test also passed inside the combined application.

## Revision tests (PUMP-DEMO store)

| Revision | Change | Result |
|---|---|---|
| V1 → r001 | pump signals | all ADDED/NEW; equipment PUMP-01 EQUIPMENT_ADDED; deployed + verified |
| V2 → r002 | + FlowRate REAL32 | FlowRate ADDED/NEW (IR5-6, lowest free); 7 existing identities UNCHANGED/**PRESERVED** at the same addresses; **deployed, 8/8 runtime-verified**; stability check confirms the runtime-verified addresses are unchanged |
| V3 → r003 | − Pressure | Pressure REMOVED/**RETIRED** (IR0-1 kept reserved for that identity); 7 others PRESERVED |
| V4 | PumpSpeed REAL32 → INT16 | **REJECTED**: BREAKING_CHANGE_REQUIRES_APPROVAL, TYPE_CHANGED, breaking=true, approved=false; accepted revisions unchanged |

- A unit test covers the approval path: V4 with an approval entry for `PumpSpeed TYPE_CHANGED` is ACCEPTED and PumpSpeed becomes REALLOCATED. The approved variant is not deployed.
- Reproduction (F11a) and store integrity (F11b) pass for all three stores. Every revision regenerates twice from its stored inputs, including the template bundle, and matches the store semantically.

## Determinism

`compare_s2.py run1 run2` compares, after normalising the run root and dropping timestamps, durations and poll counters:

- every file in all three stores (pump, combined, ahu: accepted revisions, rejected attempts, index);
- every run-level result;
- for each deploy chain:
  - model, target, allocation, plan, diff, validation, templates, instances and the verified mapping;
  - ST hashes;
  - CODESYS create/verify results and deployment results;
  - S1 regression, behaviour and typed cases;
  - REAL32 samples and ordering;
- the step status vector.

Result: **DETERMINISTIC, 367 items, 0 differences**. `pump_r003` is staged but by design has no deploy chain; the compare script records that this is the same in both runs.

## Harness stages

| Stage | Steps |
|---|---|
| F00 | preflight (S3 reference + S6 store evidence present), S3 / S6 / S2 self-tests, S6 store reproduction, adapter-generic scan, AHU template equivalence |
| F01 | model → immutable store (commit) |
| F02 | validation (all stages PASS incl. `logic_template`, template bundle hash) |
| F03 | mapping (allocator-chosen, unique, in capacity, no overlap, one channel per word/bit), stage, diff, isolation |
| F04 | CODESYS project generation + build (`create_project.py`) |
| F05 | independent build verification (`verify_project.py`, 0/0 rebuild, I/O mapping, PLC_PRG == generator) |
| F06 | deploy preflight + deploy (`deploy.py`) |
| F07 | runtime verification (RUN, all image variables online, tcp/502 owned by runtime), S1 regression (AHU chains), behaviour (template / scenario), typed verification (each probe with its own PLC online bridge session) |
| F08 | AHU regression summary |
| F09 | PUMP verification summary |
| F10 | revision tests (V2 deployed, V3, V4 rejected, diffs, stability) and summary |
| F11 | reproduction + store integrity per store; run-to-run determinism via `compare_s2.py` |
| F12 | post-run facts |

## §22 checklist

| Criterion | Result |
|---|---|
| AHU regression | PASS (`ahu_r001` + S1 regression in `combined_r001`) |
| PUMP canonical model | PASS (`pump_v1.json`, no addresses, no vendor facts; unit test) |
| PUMP validation | PASS (F02) |
| PUMP mapping | PASS (F03; allocation.json / modbus_mapping.json) |
| PUMP PLC generation | PASS (pump-only names) |
| PUMP CODESYS project generation | PASS (`AI_BMS_S2_PUMP_DEMO_r001.project`, separate project) |
| Build 0 errors / 0 warnings | PASS (all 4 projects, both runs) |
| Deploy | PASS |
| BOOL runtime | PASS (coils FC5, DI read, state machine) |
| REAL32 runtime | PASS (PumpSpeed 50.0, Pressure, FlowRate; CDAB measured) |
| AHU + PUMP identity isolation | PASS (offline checks, mutations, runtime scenario) |
| Revision ADD | PASS (FlowRate NEW, others PRESERVED, deployed) |
| Revision REMOVE | PASS (Pressure RETIRED) |
| Breaking TYPE_CHANGE rejected | PASS (V4) |
| Mapping stability | PASS (stability r001→r002 incl. runtime-verified addresses, r002→r003) |
| Deterministic run1 / run2 | PASS |
| Existing S3 tests | PASS (F00b, 26 tests) |
| Existing S6 tests | PASS (F00c, 23 tests; F00e S6 store reproduction) |
| No MCP, no LLM API, no GUI automation | confirmed (ScriptEngine `--noUI`, pymodbus, file-protocol bridge) |
| No `C:\AI_BMS_POC`, no physical PLC, no MasterSCADA modification | confirmed (local SoftPLC 127.0.0.1 only) |

Security:

- Credentials were read only from process environment variables, set in the same command as the harness and removed afterwards.
- A secret scan of the repository and `C:\AI_BMS_PHASE0\s2` found 0 hits.
- Replacing the runtime application was consented via `S1FIX_REPLACE_RUNTIME_APP=1`.
- No firewall or Windows security changes, no `%TEMP%` vendor patches, and nothing committed.

## FILES CHANGED

New (S2):

- `phase0/s2/logic/logic_templates.py` — template layer: bundle, checks, render, instances.
- `phase0/s2/logic/templates/AHU_S1FIX_V1.json`, `PUMP_BASIC_V1.json`
- `phase0/s2/model/`:
  - `target_codesys_softplc.json`
  - `pump_v1.json`, `pump_v2.json`, `pump_v3.json`, `pump_v4_type_change.json`
  - `combined_v1.json`, `ahu_v1.json`
  - `scenario_pump.json`, `isolation_scenario_bms.json`
- `phase0/s2/engine/test_s2.py` — 13 offline tests.
- `phase0/s2/probe/behavior.py` — generic template behaviour / identity scenario executor.
- `phase0/s2/probe/s2_checks.py` — validation, mapping, isolation, template-equivalence and adapter-generic checks.
- `phase0/s2/harness/run_s2.ps1`, `phase0/s2/harness/compare_s2.py`
- `docs/phase0/S2_REPORT.md`, `docs/phase0/S2_comparison_run1_run2.json`, `docs/phase0/s2_evidence/{dev1,dev2,run1,run2}/`

Modified (backward compatible; S3/S6 regression verified):

- `phase0/s1fix/codesys/deploy.py` — the online check reads plan variables instead of hard-coded AHU names.
- `phase0/s3/generator/generate.py`:
  - `generate_st(model, entries, logic=None, title=None)`;
  - the built-in AHU logic moved to the constant `AHU_S1FIX_LOGIC`;
  - S3 output is byte-identical.
- `phase0/s6/generator/regenerate.py`:
  - optional logic template bundle (validation stage `logic_template`, `logic_templates.json`, `logic_instances.json`);
  - project name taken from the target profile `artifacts.project_name` (default unchanged, `AI_BMS_S6_r{revision:03d}`).
- `phase0/s3/probe/typed_verify.py`:
  - READ signals with explicit `verification_values` get those values injected (previously only `s3_test` signals);
  - bridge reads retry on transient Windows file locks.

## LIMITATIONS

- **Transient states.** STARTING and STOPPING last one PLC cycle each (simulated run feedback), so only the stable states 0/2/9 and the transitions between them are observed; the transient states themselves are not.
- **Fault injection.** PumpFault is injected PLC-side by online write; there is no physical or simulated field feedback. PUMP_BASIC_V1 is a demo state machine, not field pump control.
- **Template body checks.** A template body is trusted ST text. The engine checks placeholders, slot types, ownership and binding uniqueness; semantic correctness is established by the CODESYS build (0/0) and the runtime behaviour test.
- **Flat PLC namespace.** All equipment share one `PLC_PRG`. A second instance whose variable names collide needs explicit symbols (as `PUMP01_*` here); there is no function-block instancing yet.
- **Revision coverage at runtime.** V3 (r003) is committed, staged and verified offline but not deployed. V2 is the deployed revision step. The approved V4 path is covered by a unit test only.
- **AHU heating check.** `HeatingValve` is not a mapped signal in the AHU/BMS models (same as S6 V1), so the typed verifier's heating-logic cross-check does not apply there.
- **Single runtime application.** Each deploy replaces the runtime application (consented). Chains run sequentially on one local SoftPLC.
- **Demo licence window.** The CODESYS demo runtime stops after about 2 hours and needs a manual service restart by the user as Administrator.
- **Binary bytes.** `.project`/`.app` bytes are not identical between runs; this is not required.

## NEXT: S7 — PLC Behavioral Testing
