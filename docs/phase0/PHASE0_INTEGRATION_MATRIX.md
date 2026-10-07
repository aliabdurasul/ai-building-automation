# Phase 0 Integration Capability Matrix

Status vocabulary (exactly one per row):

```text
VERIFIED | PARTIAL | BLOCKED | NOT VERIFIED | NOT APPLICABLE
```

Evidence is citation-only. No Phase 0 evidence trees were modified for this review.

---

## CODESYS

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Project generation | VERIFIED | S1-FIX, S2, S3, S6, S7 reports; `phase0/s1fix/codesys/create_project.py` | Fresh ScriptEngine projects; 0/0 build errors on deploy chains |
| Build | VERIFIED | S1-FIX FULL PASS; S2/S3/S6/S7 FULL PASS | Every accepted chain: 0 errors / 0 warnings |
| Deploy | VERIFIED | S1-FIX F05; S2/S3/S6/S7 deploy steps | SoftPLC replace + RUN; agentless |
| Runtime start | VERIFIED | S1-FIX F05b; S7 runtime | Application state `run`; tcp/502 owned by SoftPLC |
| Modbus server | VERIFIED | S1-FIX / S3 / S7 Modbus probes | Modbus TCP Server Device on SoftPLC, unit 1, port 502 |
| PLC logic | VERIFIED | S1-FIX AHU_S1FIX; S2 templates; S7 behaviour | Deterministic ST from generators / logic templates |
| AHU sequence | VERIFIED | S7 AHU_SEQ_V1 (35/35 steps) | START/STOP edges, timings, negatives |
| Pump sequence | VERIFIED | S2 + S7 PUMP scenarios (27/27) | State machine + Modbus + PLC online |
| Fault handling | VERIFIED | S7 FAULT/RECOVERY PASS; AHU_SEQ / AHU_S1 / PUMP | CODESYS-side FanFault / FanFailure / recovery proven |
| Heating | VERIFIED | S7 heating/setpoint PASS; S3 typed_verify heating | SupplyTemp &lt; Setpoint → HeatingValve 100.0 |
| REAL32 | VERIFIED | S3 typed_verify; S2/S6/S7 REAL32 | Measured CDAB; bit-exact vs PLC online |
| Multi-equipment | VERIFIED | S2 BMS-DEMO (AHU-01 + PUMP-01); S6 V5 AHU-02 | Combined project + isolation scenario |
| Revision management | VERIFIED | S6 FULL PASS (V1–V6 policies, rollback, reject invalid) | Lock-aware allocator; immutable store |
| Validation | VERIFIED | S3 validator; S6 revision checks; S2/S7 self-tests | Structural + breaking-change policy |
| Deterministic reproduction | VERIFIED | S2/S3/S6/S7 compare DETERMINISTIC | Semantic identity across independent runs |

---

## MODBUS

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| TCP connectivity | VERIFIED | S1-FIX F06; S3 F05b; S8 connectivity; S8.1 connectivity | `127.0.0.1:502` SoftPLC |
| FC3 (holding read) | VERIFIED | S3 typed_verify; S8 connectivity | HR0 / Setpoint / etc. |
| FC4 (input read) | VERIFIED | S3 typed_verify; S8/S8.1 IR0–IR8 | Status + REAL32 image |
| FC6 (single write) | VERIFIED | S1-FIX / S8 START/STOP probes | HR0 command |
| BOOL | VERIFIED | S3 types profile (coil / DI) | Read + write paths |
| INT16 | VERIFIED | S3 types profile | Signed two’s complement |
| UINT16 | VERIFIED | S3 types profile | Unsigned |
| WORD | VERIFIED | S1 Command/Status; S3 WORD cases | Bit fields |
| REAL32 | VERIFIED | S3; S2 PUMP; S6; S7; S8.1@MS | 2 registers |
| CDAB ordering | VERIFIED | S3 measured reference; S2/S6/S7 match | Never assumed in model; measured at runtime |
| Read/write | VERIFIED | S3 READ + WRITE tables | External pymodbus + PLC online |
| External pymodbus verification | VERIFIED | All SoftPLC runtime phases | Independent of MasterSCADA |
| PLC online readback | VERIFIED | S3 bridge; S6/S7 behaviour/typed_verify | BLOCKED only when credentials absent (offline/dev runs by design) |

---

## MASTER SCADA

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Connectivity | VERIFIED | S8 `master_scada_connectivity.json`; S8.1 `connectivity.json` | SoftPLC 502 reachable; MS Modbus client connects |
| Design-time project creation | VERIFIED | S8/S8.1 `create` → AHU_S8 / AHU_S81 | `AiBmsHmiPoc` FirebirdStore HMI template |
| Modbus configuration | VERIFIED | S8/S8.1 modbus + verify `fails=0` | IP 127.0.0.1, port 502, unit 1 |
| START | VERIFIED | S8 START E2E; S8.1 start_closed_loop | MS FanCommand=1 → HR0=1 → IR0=3 → MS FanStatus=3 Good |
| STOP | VERIFIED | S8 STOP E2E; S8.1 | MS FanCommand=2 → HR0=2 → IR0=0 → MS FanStatus=0 Good |
| RUNNING status | VERIFIED | S8/S8.1 FanStatus=3 | Closed-loop readback |
| STOPPED status | VERIFIED | S8/S8.1 FanStatus=0 | Closed-loop readback |
| REAL32 | VERIFIED | S8.1 `analog_master_scada.json` | SupplyTemp=21.0, FanSpeed=50.0 MS Good (AHU_S81 temp channels) |
| Tag validation | VERIFIED | S8 `tag_validation.json`; S8.1 channels | FanCommand HR0; FanStatus IR0; REAL32 tags in S8.1 |
| Operator HMI path | PARTIAL | S8.1 `operator_hmi.json` | Validated: debug EmulatorSession + IncludeHMI HTML5 + nginx `:8143`. Production MS Windows service: not launched |
| FAULT feedback | BLOCKED | S8.1 `fault_master_scada.json`; bridge auth failure | Not a MS START/STOP/REAL32 failure — PLC-online FanFault inject auth missing (`CODESYS_USER`/`CODESYS_PASSWORD`) |

---

## Cross-stack chain (summary)

| Chain | Status | Evidence |
|---|---|---|
| Canonical model → validate → generate → CODESYS build/deploy | VERIFIED | S1-FIX … S7 |
| SoftPLC ↔ pymodbus (external) | VERIFIED | S1-FIX … S7, S8 |
| SoftPLC ↔ MasterSCADA START/STOP/STATUS | VERIFIED | S8, S8.1 |
| SoftPLC ↔ MasterSCADA REAL32 | VERIFIED | S8.1 |
| SoftPLC ↔ MasterSCADA FAULT display | BLOCKED | S8.1 (auth) |
| Operator HTML5 path (debug) | PARTIAL | S8.1 (available path proven; not production service) |

---

## TECHNICAL STACK PROVEN

```text
Canonical Model
      ↓
Validation / Revision
      ↓
CODESYS Generation (ST + mapping + plan)
      ↓
CODESYS Build (0/0)
      ↓
SoftPLC Deployment (RUN)
      ↓
Modbus TCP (pymodbus + MS client)
      ↓
MasterSCADA tags (INT16 command/status + REAL32)
      ↓
Operator HMI path (debug EmulatorSession + IncludeHMI HTML5 + nginx)
```

Critical closed loop proven:

```text
MasterSCADA FanCommand
        ↓
Modbus HR0
        ↓
CODESYS logic
        ↓
Modbus IR0
        ↓
MasterSCADA FanStatus
```

---

## NOT YET PRODUCTIZED

```text
Document ingestion
AI extraction
Engineering agent
Engineer review workflow
Canonical model UI
Production project workspace
MasterSCADA generator (product)
Production HMI generation
Physical PLC adapter
Production deployment
LLM correction loop
SaaS / multi-tenant backend
```

---

*Generated as Phase 0 pre-product gate review. Evidence sources: `docs/phase0/S1_FIX_REPORT.md`, `S2_REPORT.md`, `S3_REPORT.md`, `S6_REPORT.md`, `S7_REPORT.md`, `S8_REPORT.md`, `S8_1_REPORT.md` and their evidence trees.*
