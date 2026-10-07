# S7 — CODESYS Behavioral Validation — Report

```
S7 RESULT:                 FULL PASS
DEV2:                      28 PASS / 0 FAIL / 0 NOT VERIFIED / 3 NOT APPLICABLE
RUN1:                      28 PASS / 0 FAIL / 0 NOT VERIFIED / 3 NOT APPLICABLE
RUN2:                      28 PASS / 0 FAIL / 0 NOT VERIFIED / 3 NOT APPLICABLE
DETERMINISM:               DETERMINISTIC (run1 vs run2, 378 semantic items, 0 differences, 0 missing)
AHU BEHAVIOR:              PASS
PUMP BEHAVIOR:             PASS
FAULT / RECOVERY:          PASS
HEATING / SETPOINT:        PASS
MODBUS:                    PASS
PLC ONLINE READBACK:       PASS
S1 REGRESSION:             PASS
S2 REGRESSION:             PASS
S3 REGRESSION:             PASS
S6 REGRESSION:             PASS
BUILD:                     PASS (0 errors / 0 warnings on every chain)
DEPLOY:                    PASS
TEST COUNT:                28 matrix tests + 101 behaviour steps per full runtime run
FAILURES:                  none
BLOCKERS:                  none on completed runtime runs
LIMITATIONS:               see below
CODESYS PHASE 0 STATUS:    COMPLETE
NEXT PHASE:                MASTER SCADA E2E
```

Three independent SoftPLC executions of `phase0/s7/harness/run_s7.ps1` (`dev2`, `run1`, `run2`) each completed with:

- 80 harness steps: **78 PASS**, **2 INFO**, none FAILED / BLOCKED / NOT_RUN
- every process exit code **0**
- test matrix **28 PASS**, **0 FAIL**, **0 NOT VERIFIED**, **3 NOT APPLICABLE**
- behaviour steps: pump 27/27, combined 15/15, AHU_SEQ 35/35, AHU_S1 24/24 (**101/101**)

`python phase0/s7/harness/compare_s7.py run1 run2` returns:

```
semantic_verdict: DETERMINISTIC
semantic_items:   378
differences:      []
missing_in_both:  []
binary_bytes:     DIFFERENT   (.project/.app byte identity not required)
```

Comparison artifact: `docs/phase0/S7_comparison_run1_run2.json`.

## Evidence locations

| Run | Staging | Repository copy |
|---|---|---|
| `dev2` | `C:\AI_BMS_PHASE0\s7\dev2` | `docs/phase0/s7_evidence/dev2` |
| `run1` | `C:\AI_BMS_PHASE0\s7\run1` | `docs/phase0/s7_evidence/run1` |
| `run2` | `C:\AI_BMS_PHASE0\s7\run2` | `docs/phase0/s7_evidence/run2` |

Consoles: `C:\AI_BMS_PHASE0\s7_{dev2,run1,run2}_console.txt`.

Offline `dev1` (no credentials) previously proved all four CODESYS builds/verifies at 0/0; deploys were BLOCKED at preflight by design.

## Deploy chains (each full runtime run)

| Chain | Project | Runtime checks |
|---|---|---|
| `pump_r002` | `AI_BMS_S7_PUMP_DEMO_r002.project` | template + S7 PUMP scenario (27 steps), typed REAL32 |
| `combined_r001` | `AI_BMS_S7_BMS_DEMO_r001.project` | S1 HR0/IR0, PUMP template + isolation (15 steps), typed |
| `ahu_seq_r001` | `AI_BMS_S7_AHU_SEQ_r001.project` | S1 HR0/IR0, AHU_SEQ_V1 scenario (35 steps), typed + heating |
| `ahu_s1_r001` | `AI_BMS_S7_AHU_S1_r001.project` | S1 HR0/IR0, AHU_S1FIX_V1 scenario (24 steps), typed + heating |

Target SoftPLC: CODESYS Control Win V3 x64 3.5.22.30, Modbus TCP port **502**. External channel: pymodbus. PLC online channel: ScriptEngine bridge (no GUI automation).

## AHU BEHAVIOR — PASS

**AHU_SEQ_V1** (new sequence template, short timings 2 s / 1 s / 1 s / 2 s):

- START edge: STOPPED → STARTING → DAMPER OPENING → FAN STARTING → RUNNING; HR0=1 → IR0=3; FanCommand / FanRunning TRUE, FanFault FALSE; damper timing checked against template parameters
- STOP edge: RUNNING → STOPPING → DAMPER CLOSING → STOPPED; HR0=2 → IR0=0
- start / stop held and released; edges ignored while running / stopped
- fault: FanFailure in RUNNING → FAULT; DamperFailure during DAMPER OPENING → FAULT
- fault recovery: clears to STOPPED without auto-restart while start held
- negatives: invalid commands, conflicting START/STOP from STOPPED, unknown state → STOPPED, STOP abort during FAN STARTING
- full scenario: **35/35** steps PASS on every runtime run

**AHU_S1FIX_V1** (existing S1 level logic):

- HR0=1 → IR0=3; hold / release stays running; HR0=2 → IR0=0
- conflicting START/STOP: STOP wins; FanFault while running → IR0=4; recovery behaviour measured
- full scenario: **24/24** steps PASS

NOT APPLICABLE (stated in matrix, not claimed as PASS): AHU_S1FIX has no sequence/damper/edge/DamperFailure.

## PUMP BEHAVIOR — PASS

- PUMP_BASIC_V1 template behaviour including start-while-stop-held
- states 0 / 1 / 2 / 3 / 9 via Modbus traces and forced STARTING/STOPPING branches; unknown state → STOPPED
- fault / fault recovery
- REAL32 PumpSpeed / Pressure / FlowRate values **50.0, 3.75, 21.5, 123.456** with S3-measured **CDAB** word order (no rediscovery)
- combined BMS-DEMO isolation scenario PASS

## FAULT / RECOVERY — PASS

Measured on SoftPLC with PLC online writes for FanFailure / DamperFailure / PumpFault / FanFault; Modbus status and discrete inputs observed; recovery paths checked.

## HEATING / SETPOINT — PASS

SupplyTemp < Setpoint → HeatingValve 100.0; ≥ → 0.0; setpoint raised over Modbus; also verified by typed_verify heating check on AHU applications.

## MODBUS / PLC ONLINE READBACK — PASS

Every behaviour expectation on a mapped signal is checked through Modbus **and** PLC online read-back (`modbus_plc_match`). Matrix row “PLC online readback” PASS on all four chains. Typed verification PASS (REAL32 ordering matches S3 reference CDAB).

## REGRESSIONS — PASS

| Suite | Evidence |
|---|---|
| S1 | HR0=1→IR0=3 and HR0=2→IR0=0 on AHU_SEQ, AHU_S1, combined; template equivalence with S6 V1 |
| S2 | combined AHU+PUMP build/deploy/behaviour/isolation; S2 self-test; S2 store reproduction (pump/combined/ahu) |
| S3 | typed_verify on every deployed application; S3 engine self-test; CDAB reference preserved |
| S6 | revision self-test; S6 store reproduction |
| Adapter | adapter-generic scan includes S7 models — no equipment-specific adapter logic |

## BUILD / DEPLOY — PASS

All four chains: CODESYS project create + verify **0 errors / 0 warnings**, deploy to SoftPLC, application RUN, Modbus image variables online, tcp/502 owned by runtime.

## DETERMINISM — PASS

`compare_s7.py` drops volatile timing fields (`t_ms`, `measured_ms`, `timeline`, `samples`, `observed_runs`, poll counters, timestamps) and compares semantic results (states, sequences, Modbus/PLC values, duration tolerance verdicts, typed cases, store artifacts, step status vector).

Result: **DETERMINISTIC**, 378 semantic items, **0** differences, **0** missing. Binary `.project`/`.app` bytes DIFFERENT (informational only).

## TEST COUNT

Per full runtime run:

- harness steps: 80 (78 PASS + 2 INFO)
- matrix tests: 28 PASS (+ 3 NOT APPLICABLE)
- behaviour steps executed: 101 (all passed)

Across `dev2` + `run1` + `run2`: three complete SoftPLC validations with identical matrix outcomes.

## FAILURES

None on completed `dev2`, `run1`, `run2`.

## BLOCKERS

None on the completed runtime runs used for this report.

Earlier in the session, incomplete attempts hung on SoftPLC/bridge before a clean SoftPLC restart; those partial trees were preserved under `C:\AI_BMS_PHASE0\s7\dev2_*partial*` and were **not** used as PASS evidence. The reported PASS runs are the completed clean executions only.

## LIMITATIONS

- SoftPLC is the CODESYS Control Win V3 x64 **demo** SoftPLC (port 502), not a physical PLC.
- AHU timings are engineering-demo parameters (short 2 s / 1 s / 1 s / 2 s), not field HVAC control.
- Heating is the simple SupplyTemp < Setpoint rule (not PID).
- Trace duration tolerance is −100 / +400 ms around template parameters.
- MasterSCADA, LLM, MCP, DWG/PDF AI, physical PLC, and `/ahu` HMI are out of scope for S7.

## CODESYS PHASE 0 STATUS: COMPLETE

Required CODESYS-side Phase 0 evidence is present and green:

- AHU sequence + edges + fault/recovery + heating
- AHU existing S1 behaviour regression
- PUMP behaviour + REAL32 CDAB
- combined multi-equipment
- Modbus ↔ PLC online readback
- S1 / S2 / S3 / S6 regressions
- build 0/0 and deploy
- two independent deterministic SoftPLC runs

## NEXT PHASE

**MASTER SCADA E2E**
