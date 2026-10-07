# Phase 0 Integration Review

Pre-product technical readiness gate. Evidence reviewed only — no Phase 0 evidence modified, no long tests re-run, no product implementation.

---

## Executive Summary

CODESYS Phase 0 (S1-FIX through S7) is **COMPLETE** with deterministic SoftPLC behaviour, typed Modbus, revision engine, and multi-equipment logic.

MasterSCADA E2E (S8 / S8.1) is **PARTIALLY VERIFIED**: critical START/STOP closed loop and REAL32 tag read are proven; the available operator HMI path (debug EmulatorSession + IncludeHMI HTML5 + nginx) was exercised; **FAULT @ MasterSCADA** remains **BLOCKED** by SoftPLC PLC-online authentication in the agent environment — not by a MasterSCADA connection or START/STOP/REAL32 failure.

```text
PHASE 0 TECHNICAL CORE:          COMPLETE
CODESYS:                         COMPLETE
MODBUS:                          COMPLETE
MASTER SCADA:                    PARTIALLY VERIFIED
MASTER SCADA CRITICAL START/STOP: COMPLETE
MASTER SCADA REAL32:             COMPLETE
MASTER SCADA OPERATOR PATH:      VALIDATED IN DEBUG/HTML5 ENVIRONMENT
MASTER SCADA FAULT:              BLOCKED
PRODUCT:                         NOT STARTED
```

**Recommendation:** proceed to **PRODUCT ARCHITECTURE** with the MasterSCADA FAULT gap documented. Do not treat MasterSCADA Phase 0 as FULL PASS.

Capability detail: [`PHASE0_INTEGRATION_MATRIX.md`](PHASE0_INTEGRATION_MATRIX.md).

---

## Verified Technical Stack

Proven engineering chain (SoftPLC + local MasterSCADA sandbox):

```text
Canonical Model
      ↓
Validation / Revision (S3 validator, S6 revision engine)
      ↓
CODESYS Generation (ST + Modbus mapping + plan)
      ↓
CODESYS Build (0 errors / 0 warnings)
      ↓
SoftPLC Deployment (Control Win V3 x64 3.5.22.30)
      ↓
Modbus TCP 127.0.0.1:502 unit 1
      ↓
MasterSCADA 4D tags (FanCommand / FanStatus / REAL32)
      ↓
Operator path: EmulatorSession + IncludeHMI HTML5 + nginx :8143
```

Also proven independently of MasterSCADA:

- External **pymodbus** verification of all mapped types
- **PLC online** read-back / fault inject (when credentials present) through S3 ScriptEngine bridge
- **Deterministic** reproduce across independent runs (S2/S3/S6/S7 compare)

---

## CODESYS Status

| Item | Status |
|---|---|
| Overall | **COMPLETE** |
| S1-FIX | FULL PASS — generate / build / deploy / Modbus HR0↔IR0 |
| S2 | FULL PASS — multi-equipment, PUMP, combined, DETERMINISTIC |
| S3 | FULL PASS — type/mapping engine, CDAB measured, DETERMINISTIC |
| S6 | FULL PASS — revision / lock / regenerate / reject breaking, DETERMINISTIC |
| S7 | FULL PASS — behavioural matrix 28 PASS; AHU/PUMP/fault/heating; DETERMINISTIC |

CODESYS SoftPLC fault handling (FanFault → IR0=4, recovery) is **VERIFIED** on the PLC/Modbus side in S7. That is distinct from MasterSCADA FAULT display (S8.1 BLOCKED).

---

## Modbus Status

| Item | Status |
|---|---|
| Overall | **COMPLETE** |
| Transport | TCP 502 SoftPLC VERIFIED |
| Functions | FC3 / FC4 / FC6 VERIFIED |
| Types | BOOL, INT16, UINT16, WORD, REAL32 VERIFIED |
| Ordering | REAL32 **CDAB** measured (S3 reference); reused, not rediscovered |
| Dual channel | pymodbus + PLC online VERIFIED when credentials available |

---

## MasterSCADA Status

| Item | Status |
|---|---|
| Version under test | 4D 1.2.18.32894 |
| S8 | PARTIAL — START/STOP PASS; FAULT/REAL32/HMI gaps |
| S8.1 | PARTIAL — REAL32 PASS; operator HTML5 path PASS; FAULT BLOCKED |
| Critical START/STOP | **COMPLETE** (three-point MS ↔ Modbus ↔ SoftPLC) |
| REAL32 | **COMPLETE** (SupplyTemp 21.0, FanSpeed 50.0 on AHU_S81) |
| Operator path | **VALIDATED** in debug EmulatorSession + IncludeHMI HTML5 + nginx |
| Production MS service | NOT VERIFIED / not launched |
| FAULT @ MS display | **BLOCKED** (test-environment auth) |

Automation host: `C:\AI_BMS_POC\master_scada_research\hmi_api_poc\host\AiBmsHmiPoc.exe` (sandbox-bound). Projects: AHU_S8 / AHU_S81 under `phase0_s8` / `phase0_s81`.

---

## Remaining Gaps

### MasterSCADA FAULT — BLOCKED BY TEST ENVIRONMENT AUTHENTICATION

**Not a product failure.** Not a START/STOP or REAL32 MasterSCADA failure.

| | |
|---|---|
| Required | `CODESYS_USER`, `CODESYS_PASSWORD` in the agent/process environment |
| Mechanism | PLC-online write `PLC_PRG.FanFault=TRUE` while MS EmulatorSession held open → expect IR0=4 and MS FanStatus=4 Good |
| Observed blocker | ScriptEngine login: *Invalid user authentication on the target* (`phase0/s8_1/evidence/fault_master_scada.json`, `bridge_result*.json`) |
| SoftPLC cfg note | `UserMgmtAllowAnonymous=YES` present; ScriptEngine still rejected empty/common variants without real device credentials |
| Prior proof | S8 CODESYS+Modbus FAULT path PASS when credentials were available; S7 FAULT behaviour PASS |

S8.1 already proved that holding MasterSCADA open reads FanStatus correctly for 0/3 and REAL32. The missing piece is only producing IR0=4 via authenticated online inject during that hold.

### Operator path scope

Proven path is **debug EmulatorSession + IncludeHMI HTML5**, not a licensed production MasterSCADA Windows service. Acceptable as “available operator path on this install”; must not be called production HMI FULL PASS.

### Product surface

Everything in “NOT YET PRODUCTIZED” (matrix / below) remains unimplemented by design.

---

## Reusable Components

Classification from the repository (no refactor performed):

| Path | Classification | Rationale |
|---|---|---|
| `phase0/s3/engine/canonical.py` | REUSABLE CORE CANDIDATE | Canonical types / REAL32 encode-decode; vendor-agnostic |
| `phase0/s3/generator/generate.py` | REUSABLE CORE CANDIDATE | ST + mapping + plan generation (pure) |
| `phase0/s6/engine/revision.py` | REUSABLE CORE CANDIDATE | Identity, diff, breaking policy, lock-aware allocate |
| `phase0/s6/generator/regenerate.py` | REUSABLE CORE CANDIDATE | Revision → regenerate via S3 generators |
| `phase0/s2/logic/` | REUSABLE CORE CANDIDATE | Logic templates (AHU_S1FIX, AHU_SEQ, PUMP) |
| `phase0/s2/model/*.json`, `phase0/s6/model/`, `phase0/s7/model/` | REUSABLE CORE CANDIDATE | Canonical models / scenarios / target profiles |
| `phase0/s3/probe/typed_verify.py` | VALIDATION TOOLING | Typed Modbus + bridge verify |
| `phase0/s2/probe/behavior.py` | VALIDATION TOOLING | Behaviour executor |
| `phase0/s6/probe/revision_checks.py` | VALIDATION TOOLING | Store integrity / reproduce |
| `phase0/s7/probe/test_matrix.py` | VALIDATION TOOLING | Behavioural matrix |
| `phase0/*/harness/` | VALIDATION TOOLING / TEST HARNESS | Run + compare orchestration |
| `phase0/s1fix/codesys/` | VENDOR ADAPTER | CODESYS ScriptEngine create/verify/deploy |
| `phase0/s3/codesys/plc_online_bridge.py` | VENDOR ADAPTER | PLC online read/write bridge |
| `phase0/s8/`, `phase0/s8_1/` | MASTER SCADA VALIDATION / SANDBOX | Evidence + MS E2E harnesses |
| `C:\AI_BMS_POC\master_scada_research\hmi_api_poc\` | LEGACY / SANDBOX / TEMPORARY POC | AiBmsHmiPoc host, nginx sandbox, MS project store |
| `C:\AI_BMS_PHASE0\` | TEST HARNESS staging | Run roots for S1–S7 (outside git; evidence copied to `docs/phase0/`) |
| `docs/phase0/*_evidence/` | VALIDATION EVIDENCE | Immutable run copies |

---

## Temporary / Legacy Components

### Dependencies on `C:\AI_BMS_POC`

| Occurrence | Class | Notes |
|---|---|---|
| `phase0/s1/harness/run_s1.ps1` (`$Poc`, `$MsSandbox`, path rewrite table) | legacy / test-only | Original S1 harness still rewrites POC paths; S1-FIX moved CODESYS off POC |
| `phase0/s1/harness/compare_s1.py` MS stage path | test-only | Compares MS sandbox under POC |
| `phase0/s1fix/model/ahu01.json` `"source": ...AI_BMS_POC\demo...` | legacy (metadata only) | Provenance comment; runtime does not open POC |
| `phase0/s8/README.md`, `phase0/s8_1/harness/*.py` | required (current MS validation) | AiBmsHmiPoc **refuses** paths outside POC sandbox |
| `docs/phase0/S8*_REPORT.md`, S8/S8.1 evidence paths | test-only evidence | Records where MS projects lived |
| `docs/phase0/evidence/run*`, S1 reports | legacy evidence | Historical S1 MS steps |

**Product implication:** CODESYS pipeline can already leave `AI_BMS_POC` (S1-FIX statement). MasterSCADA automation **today** is bound to the POC sandbox host. A product MasterSCADA adapter must eventually replace AiBmsHmiPoc sandbox constraints — classify as *should be removed later* for product, *required* for current Phase 0 MS validation.

### Dependencies on `C:\AI_BMS_PHASE0`

| Occurrence | Class |
|---|---|
| All `phase0/s{1fix,2,3,6,7}/harness/run_*.ps1` `$RunRoot` | test-only staging |
| S8.1 bridge pointing at `s7\run2\deploy\ahu_s1_r001` | test-only |

Staging is outside the repo by design; evidence is copied under `docs/phase0/`. Product should use configurable project/artifact roots, not hardcoded drive letters.

---

## Product Boundary

Smallest future boundary **supported by Phase 0 findings** (description only — not created):

```text
product/
│
├── domain/
│   ├── engineering_model     ← S2/S3/S6/S7 canonical models + templates
│   ├── validation            ← S3 validator + S6 revision rules
│   └── revision              ← S6 revision engine + lock allocator
│
├── generators/
│   └── plc_st_modbus         ← S3/S6 generate / regenerate (deterministic)
│
├── adapters/
│   ├── codesys               ← s1fix/codesys + s3 bridge (SoftPLC first)
│   └── masterscada           ← NEW product adapter (replace AiBmsHmiPoc sandbox)
│
├── project/                  ← NOT IMPLEMENTED (workspace / package)
│
├── artifacts/                ← maps to today’s engineering/ + generated/ stores
│
└── verification/             ← typed_verify, behavior, matrix, MS E2E harness patterns
```

**Not in the first product boundary (unsupported by Phase 0):** document AI, SaaS UI, physical PLC fleets, production MasterSCADA service packaging, LLM loops.

---

## Future AI Boundary

Preferred insertion (not implemented):

```text
Documents
    ↓
AI extraction / reasoning
    ↓
Canonical Engineering Model
    ↓
Deterministic validation (S3/S6 rules)
    ↓
Deterministic generators (ST / Modbus / future MS)
    ↓
Adapters (CODESYS / MasterSCADA)
```

AI must **not** directly drive CODESYS, Modbus, MasterSCADA, or PLC runtime without deterministic validation gates. Phase 0 already proves the deterministic lower half of this stack on SoftPLC + local MS.

---

## Future Product Workflow

| Stage | Phase 0 mark |
|---|---|
| NEW PROJECT | NOT IMPLEMENTED |
| SOURCE DOCUMENTS | NOT IMPLEMENTED |
| DOCUMENT ANALYSIS | NOT IMPLEMENTED |
| ENGINEERING MODEL | ALREADY PROVEN (hand/authored JSON models) |
| ENGINEER REVIEW | NOT IMPLEMENTED |
| VALIDATION | ALREADY PROVEN |
| PLC GENERATION | ALREADY PROVEN |
| MODBUS GENERATION | ALREADY PROVEN |
| MASTER SCADA GENERATION | POC ONLY (AiBmsHmiPoc create/modbus/hmibuild) |
| HMI GENERATION | POC ONLY (minimal TEST HMI / IncludeHMI) |
| BUILD | ALREADY PROVEN (CODESYS); MS compile via EmulatorSession POC |
| DEPLOY | ALREADY PROVEN (SoftPLC); MS = debug session POC |
| E2E VERIFICATION | ALREADY PROVEN (CODESYS/Modbus); PARTIAL (MS FAULT BLOCKED) |
| PROJECT PACKAGE | NOT IMPLEMENTED |

---

## Phase 0 Decision

```text
PHASE 0 TECHNICAL CORE:
COMPLETE

CODESYS:
COMPLETE

MODBUS:
COMPLETE

MASTER SCADA:
PARTIALLY VERIFIED

MASTER SCADA CRITICAL START/STOP:
COMPLETE

MASTER SCADA REAL32:
COMPLETE

MASTER SCADA OPERATOR PATH:
VALIDATED IN DEBUG/HTML5 ENVIRONMENT

MASTER SCADA FAULT:
BLOCKED

PRODUCT:
NOT STARTED
```

Interpretation:

- The **engineering stack** (model → validate → generate → SoftPLC → Modbus → MS tags for START/STOP/REAL32) is proven enough to design product architecture.
- MasterSCADA is **not** Phase 0 FULL PASS: FAULT@MS remains environment-blocked; operator path is debug/HTML5-scoped.
- Closing FAULT@MS later needs credentials + a short S8.1-style hold — it is **not** a prerequisite to start architecture design, but it must stay on the gap list.

---

## Recommended Next Phase

```text
RECOMMENDATION:
PROCEED TO PRODUCT ARCHITECTURE
WITH MASTER SCADA FAULT GAP DOCUMENTED
```

Next phase (separate task, after this review):

1. Design product package layout from the boundary above  
2. Define adapter contracts (CODESYS proven; MasterSCADA to replace POC host)  
3. Keep FAULT@MS as an explicit verification backlog item (`CODESYS_USER` / `CODESYS_PASSWORD`)  
4. Do **not** start LLM, document ingestion, `/ahu` UI, or SaaS implementation in that architecture pass unless explicitly scoped later  

---

**STOP.** No product implementation, architecture code, frontend, backend, LLM agent, or Phase 0 refactor was started by this review.
