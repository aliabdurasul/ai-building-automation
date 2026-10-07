# S8.1 — MasterSCADA E2E Gap Closure

```
RESULT:                 PARTIAL

MASTER SCADA VERSION:   4D 1.2.18.32894
CODESYS VERSION:        3.5.22.30 (Control Win V3 x64 SoftPLC)

PREVIOUS S8:            PARTIAL

S8.1 TEST COUNT:        13
PASS:                   9
FAIL:                   0
NOT VERIFIED:           0
BLOCKED:                3  (FAULT feedback, FAULT recovery, Operator HMI FAULT)
PARTIAL:                1  (full three-point matrix row — FAULT side incomplete)

FAULT @ MASTER SCADA:   BLOCKED
  SoftPLC ScriptEngine login failed: Invalid user authentication on the target.
  CODESYS_USER / CODESYS_PASSWORD were not available in this agent process.
  SoftPLC cfg has UserMgmtAllowAnonymous=YES, but ScriptEngine still rejected
  empty/common credential variants. Without PLC online FanFault inject, IR0=4
  could not be produced while MasterSCADA was held open. No fabricated PASS.

REAL32 @ MASTER SCADA:  PASS
  Temporary AHU_S81 channels (not S7 redesign):
    SupplyTemp  IR5 REAL32  → MasterSCADA = 21.0 (Good)
    FanSpeed    IR1 REAL32  → MasterSCADA = 50.0 (Good)
  Word order: S3-measured CDAB (no rediscovery). Module float byte-order left at vendor default (id=4 value=2).

OPERATOR HMI:           PASS (available path on this install)
  Minimal temporary screen "S8.1 TEST HMI" (FanCommand / FanStatus / SupplyTemp).
  Path used: debug EmulatorSession + ControllerConfiguration.IncludeHMI HTML5
  + vendor nginx on 127.0.0.1:8143.
  Observed during HMI session: FanStatus 0 and 3 (STOPPED / RUNNING) after START/STOP stimulus.
  Production MasterSCADA Windows service: not found / not launched.
  Operator HMI FAULT: BLOCKED (same PLC-online auth blocker).

THREE-POINT VERIFICATION:

  START/STOP (reconfirmed)
    CODESYS SoftPLC  HR0/IR0 via Modbus
    Modbus           HR0=1→IR0=3 ; HR0=2→IR0=0
    MasterSCADA      FanCommand write / FanStatus=3 then 0 (Good)
    RESULT: PASS

  REAL32 SupplyTemp
    CODESYS SoftPLC (Modbus image)  21.0
    Modbus CDAB                     21.0
    MasterSCADA                     21
    RESULT: PASS

  REAL32 FanSpeed
    CODESYS SoftPLC (Modbus image)  50.0
    Modbus CDAB                     50.0
    MasterSCADA                     50
    RESULT: PASS

  FAULT IR0=4
    CODESYS FanFault → IR0=4 → MS FanStatus=4
    RESULT: BLOCKED (no authenticated PLC online session)

CODESYS:                SoftPLC app AI_BMS_S7_AHU_S1_r001 (HR0/IR0 unchanged)
MODBUS:                 127.0.0.1:502 unit 1 — PASS
MASTER SCADA:           AHU_S81 project (sandbox) — INT16 + temporary REAL32 + TEST HMI

FILES CREATED:
  docs/phase0/S8_1_REPORT.md
  phase0/s8_1/README.md
  phase0/s8_1/evidence/*
    connectivity.json
    fault_master_scada.json
    analog_master_scada.json
    operator_hmi.json
    test_matrix.json
    s81_runtime_events.jsonl
    hmi_runtime_events2.jsonl
  phase0/s8_1/harness/run_s81.py, retry_gaps.py, retry_hmi_http.py, plc_online_bridge_s81.py
  phase0/s8_1/specs/s81_test_hmi.json
  C:\AI_BMS_POC\...\phase0_s81\projects\AHU_S81

  Host test extension (sandbox only, not product):
    AiBmsHmiPoc modes s81runtime + AHU_S81 REAL32 channels (Modbus.cs / S81Runtime.cs)

LIMITATIONS:
  - FAULT@MS requires CODESYS device credentials in the agent environment; not present this run.
  - Operator path validated is debug EmulatorSession + IncludeHMI HTML5, not a production MS service.
  - PLC online read-back of REAL32 was unavailable (same auth); Modbus SoftPLC image used as CODESYS side.
  - S8 evidence under phase0/s8 and docs/phase0/s8_evidence/run1 was preserved (not overwritten).
  - S1–S7 mappings / reports were not modified.

DECISION:
  S8.1 closes REAL32@MS and the available operator HMI path.
  FAULT@MS remains BLOCKED until SoftPLC online credentials are available to the agent.
  Therefore S8.1 cannot be FULL PASS under the stated criteria.
```

---

```
CODESYS PHASE 0:
COMPLETE

MASTER SCADA E2E:
PARTIAL

PHASE 0 INTEGRATION:
NOT COMPLETE

PRODUCT DEVELOPMENT:
NOT STARTED
```

To reach FULL PASS later (separate decision): provide `CODESYS_USER`/`CODESYS_PASSWORD` to the agent process and re-run only the FAULT hold (`retry_gaps.py` fault path) so MasterSCADA FanStatus=4 is observed with IR0=4 — no product work required.
