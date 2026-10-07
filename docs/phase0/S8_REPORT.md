# S8 — MasterSCADA E2E Validation

```
RESULT:                 PARTIAL
MASTER SCADA VERSION:   4D 1.2.18.32894
CODESYS VERSION:        3.5.22.30 (Control Win V3 x64 SoftPLC)
TARGET:                 127.0.0.1:502 unit 1 — S7 AHU_S1 application (HR0/IR0 contract unchanged)
MODBUS:                 PASS (TCP + FC3/FC4/FC6)
CONNECTIVITY:           PASS
START E2E:              PASS
STOP E2E:               PASS
FAULT E2E:              PARTIAL (CODESYS+Modbus PASS; MasterSCADA FAULT display NOT VERIFIED)
ANALOG E2E:             PARTIAL (Modbus REAL32 CDAB PASS; MasterSCADA REAL32 tags NOT VERIFIED)
TAG VALIDATION:         PASS (FanCommand / FanStatus; FanRunning/FanFault via Status word)
HMI:                    NOT VERIFIED (debug EmulatorSession used; no browser operator path in S8)
EXTERNAL VERIFICATION:  PASS for START/STOP closed loop (CODESYS ↔ Modbus ↔ MasterSCADA)
FAILURES:               none on critical START/STOP path
BLOCKERS:               none after SoftPLC restart
LIMITATIONS:            see below
NEXT PHASE:             close remaining NOT VERIFIED items OR accept Phase 0 Integration with documented gaps
```

## Evidence locations

| Path | Content |
|---|---|
| `phase0/s8/evidence/` | connectivity, create/modbus/verify logs, runtime events, start/stop/fault/analog/tag/matrix JSON |
| `docs/phase0/s8_evidence/run1/` | repository copy of run1 evidence |
| `docs/phase0/s8_evidence/discovery/` | SoftPLC-down discovery baseline |
| `C:\AI_BMS_POC\master_scada_research\hmi_api_poc\phase0_s8\` | MasterSCADA project sandbox (`AHU_S8`) |

S1–S7 evidence trees were **not** modified. CODESYS HR0/IR0 mapping was **not** changed.

## What was proven

### Connectivity

- SoftPLC listening on tcp/502
- pymodbus FC3 / FC4 / FC6 unit 1 OK  
  Evidence: `master_scada_connectivity.json`

### MasterSCADA design-time

- `AiBmsHmiPoc.exe create` → AHU_S8 project
- `modbus` → FanCommand HR0 write INT16, FanStatus IR0 read INT16, IP 127.0.0.1 port 502 unit 1
- `verify` → `fails=0`  
  Evidence: `S09_ms_create.log`, `S10_ms_modbus.log`, `S11_ms_verify.log`

### START E2E — PASS

Observed in `S15_ms_runtime_events.jsonl`:

```
MasterSCADA FanCommand write = 1
        ↓
CODESYS / Modbus HR0 = 1
        ↓
CODESYS logic → IR0 = 3 (FanCommand + FanRunning)
        ↓
MasterSCADA FanStatus = 3 (StatusCode:=Good)
```

`summary`: `write_ok=true`, `closed_loop_ok=true`, `read_ok=true`

### STOP E2E — PASS

```
MasterSCADA FanCommand write = 2
        ↓
HR0 = 2
        ↓
IR0 = 0
        ↓
MasterSCADA FanStatus = 0 (StatusCode:=Good)
```

### External triple verification — PASS (START/STOP)

| Point | START | STOP |
|---|---|---|
| MasterSCADA | FanCommand=1 / FanStatus=3 | FanCommand=2 / FanStatus=0 |
| Modbus | HR0=1 / IR0=3 | HR0=2 / IR0=0 |
| CODESYS (via Modbus + logic) | running | stopped |

Also verified independently with pymodbus before MS runtime: HR0=1→IR0=3, HR0=2→IR0=0.

### FAULT E2E — PARTIAL

- PLC online write `FanFault=TRUE` while running → PLC FanCommand/FanRunning FALSE, **IR0=4** (Modbus)
- Evidence: `fault_e2e.json`
- **MasterSCADA FAULT display**: NOT VERIFIED (MS debug session was not held open during fault inject)

### ANALOG E2E — PARTIAL

Modbus REAL32 with S3-measured **CDAB** (no rediscovery):

| Tag | Modbus decoded |
|---|---|
| SupplyTemp | 21.0 |
| FanSpeed | 50.0 |
| HeatingValve | 100.0 |

- **MasterSCADA REAL32 tags**: NOT VERIFIED (AHU_S8 project only has FanCommand / FanStatus INT16 channels — existing S1 POC shape, not extended)

### HMI — NOT VERIFIED

S8 used the existing debug `IWIN32` EmulatorSession path (same as S1 S15). No nginx/browser operator click path was run. This is **not** a product UI.

## Test matrix summary

From `test_matrix.json`:

| Result | Count |
|---|---|
| PASS | 16 |
| NOT VERIFIED | 3 |
| FAIL | 0 |

NOT VERIFIED:

1. MasterSCADA FAULT display
2. MasterSCADA REAL32 tag read
3. Operator HMI screen E2E

Critical START/STOP / connectivity / triple-compare rows: **all PASS**.

## Limitations

- MasterSCADA automation depends on internal `InSAT.Framework.TestBase.UIServiceForTests` (S1 known dependency).
- Runtime under test is **debug EmulatorSession**, not a production MasterSCADA Windows service.
- SoftPLC is demo SoftPLC, not a physical PLC.
- REAL32 and FAULT were not added as MasterSCADA channels in this validation (no product redesign).
- AiBmsHmiPoc sandbox forces MasterSCADA projects under `C:\AI_BMS_POC\master_scada_research\hmi_api_poc\`.

## Decision

```
S8 RESULT: PARTIAL

Critical MasterSCADA ↔ Modbus ↔ CODESYS START/STOP closed loop: PROVEN
Remaining gaps: FAULT@MS, REAL32@MS, operator HMI

CODESYS Phase 0 (S1–S7): remains COMPLETE
Phase 0 Integration Complete: NOT YET (S8 not FULL PASS)

NEXT PHASE:
  Option A — extend S8 minimally to cover FAULT@MS + REAL32@MS + optional HMI, then FULL PASS
  Option B — accept PARTIAL and start PRODUCT ARCHITECTURE with documented S8 gaps
```
