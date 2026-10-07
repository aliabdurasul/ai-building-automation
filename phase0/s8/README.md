# S8 — MasterSCADA E2E Validation (Phase 0)

**Status:** DISCOVERY COMPLETE — runtime E2E **BLOCKED** until SoftPLC serves Modbus on `127.0.0.1:502`.

This is a **validation phase only**. No product UI, LLM, MCP, generators, or CODESYS mapping changes.

## Discovery summary (2026-10-06)

### Already proven (do not re-prove)

| Phase | Result |
|---|---|
| S1–S7 CODESYS / Modbus | COMPLETE — SoftPLC behavioural + typed + deterministic |
| S7 AHU contract | HR0 Command (bit0 START, bit1 STOP); IR0 Status (FanCommand/FanRunning/FanFault) |

### MasterSCADA on this machine

| Item | Value |
|---|---|
| Product | MasterSCADA 4D |
| Version | **1.2.18.32894** (`C:\Program Files\MPSSoft\MasterSCADA 4D 1.2\version.txt`) |
| Install | `C:\Program Files\MPSSoft\MasterSCADA 4D 1.2` |
| Windows service | **not registered** (S1 fact) |
| Runtime under test (S1) | debug `IWIN32.EXE` EmulatorSession (UDP 31201) |
| Existing automation host | `C:\AI_BMS_POC\master_scada_research\hmi_api_poc\host\AiBmsHmiPoc.exe` |

### Existing MasterSCADA POC (S1 / HMI API)

Reusable agentless modes (design-time + debug runtime):

```
create | modbus | verify | runtime | hmibuild | hmiverify | hmiruntime
```

Hardcoded Modbus channels in `Modbus.cs` (matches S7 HR0/IR0 contract):

| Channel | Area | Address | Access | Type |
|---|---|---|---|---|
| FanCommand | Holding Register | 0 | Output (write) | INT16 |
| FanStatus | Input Register | 0 | Input (read) | INT16 |

IP `127.0.0.1`, port `502`, unit `1`.

S1 result for MasterSCADA **runtime**: FAIL — no PLC on tcp/502 at that time. Design-time create/modbus/HMI build PASS.

Sandbox: `AiBmsHmiPoc` refuses paths outside `C:\AI_BMS_POC\master_scada_research\hmi_api_poc\`. S8 MasterSCADA project staging must live under e.g. `...\phase0_s8\` there. Evidence copies go to `phase0/s8/` and `docs/phase0/s8_evidence/` in this repo.

### SoftPLC at discovery time

| Item | Value |
|---|---|
| Service | `CODESYS Control Win V3 - x64` = **Stopped** |
| tcp/502 | **not listening** |
| tcp/11740 | **not listening** |
| S7 last deploy | `AI_BMS_S7_AHU_S1_r001` (AHU_S1FIX_V1) — suitable for MasterSCADA FanCommand/FanStatus INT16 E2E |

### Out of scope for S8

LLM, MCP, PDF/DWG AI, product UI, `/ahu` HMI, physical PLC, CODESYS generator/refactor, new equipment types, overwriting S1–S7 evidence.

## Planned S8 test matrix (to execute after SoftPLC is up)

| # | Test | Expected when runnable |
|---|---|---|
| 01 | TCP connectivity | 127.0.0.1:502 listen |
| 02 | Modbus connection | FC3/FC4/FC6 unit 1 |
| 03 | MasterSCADA read | FanStatus / IR0 |
| 04 | MasterSCADA write | FanCommand / HR0 |
| 05 | START E2E | MS → HR0=1 → IR0=3 → MS RUNNING |
| 06 | STOP E2E | MS → HR0=2 → IR0=0 → MS STOPPED |
| 07 | RUNNING feedback | IR0=3 bits |
| 08 | STOPPED feedback | IR0=0 |
| 09 | FAULT feedback | FanFailure / FanFault if injectable |
| 10 | REAL32 read | CDAB SupplyTemp/HeatingValve vs MS (if channel added) |
| 11–14 | Tag validation | FanRunning / FanFault / Status / Command |
| 15 | Triple compare | CODESYS ↔ Modbus ↔ MasterSCADA |
| 16 | Runtime stability | hold without BadOutOfService |

## Layout

```
phase0/s8/
  README.md          (this file)
  harness/           (S8 runner scripts — reuse AiBmsHmiPoc, do not rewrite)
  evidence/          (JSON results per test)
  reports/           (interim notes)
docs/phase0/S8_REPORT.md          (final — after runs)
docs/phase0/s8_evidence/          (copied evidence)
C:\AI_BMS_PHASE0\s8\              (staging for non-sandbox artifacts)
C:\AI_BMS_POC\...\phase0_s8\      (MasterSCADA project sandbox)
```

## Next operator action

Restart **CODESYS Control Win V3 - x64** as Administrator (fresh demo window), confirm tcp/502, then continue S8 E2E with the existing `AiBmsHmiPoc` host + S7 AHU_S1 mapping (no CODESYS redesign).
