# S1 Evidence Index

All paths are relative to the repo root unless they are absolute. Raw evidence was written by `phase0/s1/harness/run_s1.ps1`. That harness only measures; it does not decide PASS/FAIL. The comparison was produced by `phase0/s1/harness/compare_s1.py`. Secret scan: the evidence contains no credential values. The only "password" hits are MasterSCADA setting names.

## 1. Environment

| Item | File |
|---|---|
| Environment snapshot (structured) | `docs/phase0/S1_environment.json` |
| Raw environment probe output | `docs/phase0/evidence/env_raw.txt` |
| Runbook followed | `docs/phase0/S1_AGENTLESS_RUNBOOK.md` |

## 2. Per-run raw records

| Evidence | RUN 1 | RUN 2 |
|---|---|---|
| Harness record (timestamps, commands, exit codes, created files) | `evidence/run1/harness_run1.json` | `evidence/run2/harness_run2.json` |
| ST generation stdout | `evidence/run1/S02_generate_st.stdout.txt` | `evidence/run2/...` |
| CODESYS generate + build (stdout: script log; stderr: compiler messages) | `evidence/run1/S03_codesys_generate_build.*` | `evidence/run2/...` |
| CODESYS verify read-back (DECL/IMPL text) | `evidence/run1/S04_codesys_verify.stdout.txt` | `evidence/run2/...` |
| Clean mapping attempt | `evidence/run1/S05_codesys_clean_mapping.stderr.txt` + `C:\AI_BMS_PHASE0\s1\run1\codesys\logs\modbus_io_map.json` | same layout under `run2` |
| Boot app + online login attempt | `evidence/run1/S06_codesys_online_attempt.*` + `...\logs\runtime_result.txt` | same layout under `run2` |
| SoftPLC service start (non-elevated) | `harness_run1.json` step `S07_softplc_service_start` | `harness_run2.json` |
| External Modbus probe | `evidence/run1/S08_modbus_probe.stderr.txt` + `...\logs\modbus_v2_probe.json` | same layout under `run2` |
| MasterSCADA create / modbus | `evidence/run1/S09_ms_create.log`, `S10_ms_modbus.log` | `evidence/run2/...` |
| MasterSCADA Modbus read-back verify | `evidence/run1/S11_ms_verify.log` | `evidence/run2/...` |
| HMI build | `evidence/run1/S12_hmi_build.log` | `evidence/run2/...` |
| HMI read-back verify (76 checks) | `evidence/run1/S13_hmi_verify.log`, `S13_hmi_verify_evidence.json` | `evidence/run2/...` |
| MasterSCADA debug runtime read/write | `evidence/run1/S15_ms_runtime.log`, `S15_ms_runtime_events.jsonl` | `evidence/run2/...` |
| HMI runtime (IncludeHMI, 20 s hold) | `evidence/run1/S16_hmi_runtime.log`, `S16_hmi_runtime_events.jsonl` | `evidence/run2/...` |

Structured step status (interpreted from the evidence above): `docs/phase0/S1_run1.json`, `docs/phase0/S1_run2.json`.

## 3. Generated artifacts (kept in staging)

| Artifact | RUN 1 | RUN 2 |
|---|---|---|
| ST sources | `C:\AI_BMS_PHASE0\s1\run1\codesys\generated\PLC_PRG*.st` | `...\run2\...` (SHA256 of `PLC_PRG.st` is `39971DAACED81F17…` in both runs) |
| CODESYS project | `...\run1\codesys\AI_BMS_AHU_DEMO.project` (225104 B, `aea8eb31…`) | `...\run2\...` (225104 B, `a820eb01…`) |
| CODESYS boot app | `...\run1\codesys\generated\AI_BMS_AHU_DEMO.app` (97508 B, `1202db48…`) | `...\run2\...` (97508 B, `f244144f…`) |
| MasterSCADA project | `C:\AI_BMS_POC\master_scada_research\hmi_api_poc\phase0_s1\run1\projects\AHU_S1\` (`.fdb` 61644800 B, `37ae4dc5…`) | `...\phase0_s1\run2\...` (`.fdb` 61644800 B, `ae62c777…`) |
| HTML5 HMI output from the debug runtime | `...\phase0_s1\run1\rt_copy_hmi\rt_work\Debug_1\htdocs\` (141 files) | `...\run2\...` (141 files, byte-identical) |

## 4. Key evidence quotes

- **Build:** "Compile complete -- 0 errors, 0 warnings" (S03 stderr, both runs).
- **Verify:** "STATUS=OK all required symbols present" (S04). The read-back DECL contains only `StartCommand, StopCommand, FanCommand, FanRunning, FanFault, SupplyTemp, Setpoint, FanSpeed, HeatingValve`. There are no Modbus interface variables.
- **Clean mapping:** `{"error": "Modbus_TCP_Server not found", "opened": true}` with process exit code 0.
- **Online:** "Login failed: Unable to connect to the device for item 'Device.Application' ... Invalid user authentication on the target". STATUS=PARTIAL, exit code 4. The following lines, "MANUAL REQUIRED ... / REASON: SoftPLC service start returned Access Denied", are hardcoded in `codesys_runtime.py` (lines 121–122). They are not an observation from this run.
- **Service:** "Cannot open CODESYS Control Win V3 - x64 service on computer '.'" (non-elevated).
- **Modbus probe:** "Connection to (127.0.0.1, 502) failed: timed out", `{"connect": false}`, exit code 0.
- **MasterSCADA Modbus read-back:** "module ... IP=127.0.0.1 Port=502 Unit=1 / FanCommand Address=0 AccessType=Output / FanStatus Address=0 AccessType=Input / VERIFY RESULT fails=0".
- **HMI read-back:** "VERIFY RESULT PASS checks=76 fails=0".
- **Runtime:** "FATAL ... SocketException ... actively refused it 127.0.0.1:502", exit code 1.
- **HMI runtime:** `ms_FanStatus ... StatusCode:=BadOutOfService`, `codesys_HR0: modbus_err:SocketException`. `ms_FanCommand Value:=2 Good` is the parameter's initial value inside MasterSCADA. It is not a value written to a PLC.

## 5. Determinism

`docs/phase0/S1_comparison.json` contains every artifact pair with its raw result, its normalized result, the first normalized difference, the per-category verdicts and the exit-code vector.

## 6. Exclusions (enforced)

- No MCP server, LLM API, Claude, Cline or Cursor automation was used inside any step.
- No `%TEMP%` handler patch was used. The patched `device_h.py` was present but was not loaded.
- No hand-written V2 PLC was used (`codesys_ahu_v2_plc_map.py` was not executed).
- No GUI or coordinate automation, no browser, no nginx.
- The original projects under `C:\AI_BMS_POC\` were not modified. MasterSCADA staging went into a new subfolder `phase0_s1\`, because the host's sandbox guard forces this location.
- The user's `/ahu` HMI and the user projects (`AhuTest1`, `AHUplc`, `Project 1`, `slavak1 bms`) were not touched.
- No `.fdb` file was edited by hand or with SQL.
