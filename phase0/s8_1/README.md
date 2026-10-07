# S8.1 — MasterSCADA E2E gap closure (validation only)

Preserves S8 evidence under `phase0/s8/` and `docs/phase0/s8_evidence/run1/` (untouched).

## Layout

```
phase0/s8_1/
├── evidence/     # run artifacts (JSON/logs/events)
├── harness/      # orchestrators + anonymous-capable bridge wrapper
├── specs/        # S8.1 TEST HMI JSON (not product UI)
├── reports/      # local copies
└── README.md
```

MasterSCADA sandbox project: `C:\AI_BMS_POC\master_scada_research\hmi_api_poc\phase0_s81\projects\AHU_S81`

## Gaps addressed

| Gap | Approach |
|---|---|
| FAULT @ MS | Hold `s81runtime` EmulatorSession; PLC online `FanFault` inject while sampling `FanStatus` |
| REAL32 @ MS | Temporary `SupplyTemp` (IR5) + `FanSpeed` (IR1) float channels on AHU_S81 only |
| Operator HMI | Minimal `S8.1 TEST HMI` + IncludeHMI HTML5 + nginx `:8143` |

## Commands

```text
python phase0/s8_1/harness/run_s81.py
python phase0/s8_1/harness/retry_gaps.py
python phase0/s8_1/harness/retry_hmi_http.py
```

Requires SoftPLC on `127.0.0.1:502`. PLC online FAULT inject needs working CODESYS device credentials in the process environment (`CODESYS_USER` / `CODESYS_PASSWORD`). SoftPLC anonymous cfg alone was not sufficient for ScriptEngine login in this run.

## Not in scope

No LLM/product UI/`/ahu`/generators/MCP/S1–S7 changes.
