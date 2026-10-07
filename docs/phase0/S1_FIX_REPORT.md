# S1-FIX REPORT

Date: 2026-10-05, times +03:00.

Runs:
- Full PASS runs on a clean SoftPLC runtime: RUN 3 (12:06–12:09) and RUN 4 (12:09–12:12).
- Earlier Minimum PASS runs: RUN 1 and RUN 2 (11:20–11:25). See History.

Executor: Cursor agent running shell commands only. No MCP, no LLM API, no GUI/mouse/keyboard automation, no `%TEMP%` vendor patch. Windows security and the firewall were not changed.

**Result: FULL PASS.** The generated application was downloaded agentlessly to the local CODESYS Control Win V3 x64 runtime and started. On real Modbus TCP (127.0.0.1:502), HR0=1 → IR0=3 and HR0=2 → IR0=0 were observed with pymodbus in both runs. RUN 3 and RUN 4 are semantically identical, including the runtime and Modbus results.

## Old POC not used

**The old POC (`C:\AI_BMS_POC`) was not used for the new deployment.** RUN 3 and RUN 4 do not read, open, copy or modify anything under `C:\AI_BMS_POC`. Every input comes from this repo:
- The model is `phase0/s1fix/model/ahu01.json`.
- The ST, mapping and plan come from `phase0/s1fix/generator/generate.py`.
- The project is created from scratch by `phase0/s1fix/codesys/create_project.py` into `C:\AI_BMS_PHASE0\s1fix\<run>\generated\AI_BMS_AHU_DEMO.project`.
- Deployment is done by `phase0/s1fix/codesys/deploy.py`, from that generated project only.

No technical dependency on the old POC came up, so nothing had to be taken from it.

The application previously running on the SoftPLC, of unknown provenance, was **replaced**. The download used `login(OnlineChangeOption.Never, delete_foreign_apps=True)`, with the owner's explicit consent for this test (`S1FIX_REPLACE_RUNTIME_APP=1`).

## Credentials and security

- Credentials were supplied only as process environment variables of the executing shell (`CODESYS_USER`, `CODESYS_PASSWORD`). The harness and `deploy.py` read them from the environment.
- They are not hardcoded and not written to any file, log, evidence file, this report or git. `deploy.py` masks the password in any error text.
- Secret scan after both runs: `rg -F <password>` over the repo and `C:\AI_BMS_PHASE0\s1fix` found **0 matches**.
- Evidence records only `credentials_source = CODESYS_USER/CODESYS_PASSWORD` and `credentials_present = true`.
- Elevation: the session is **not elevated** (`elevated=false`). It did not need to be, because the runtime service was already running. No restart was attempted and no Windows security setting was bypassed.

## Changes for the clean-runtime deployment

| File | Change |
|---|---|
| `phase0/s1fix/harness/run_s1fix.ps1` | **F04 preflight.** A pre-existing tcp/502 listener is now attributed to its owning process. It is allowed only if the owner is the CODESYS runtime service process **and** the operator consented with `S1FIX_REPLACE_RUNTIME_APP=1`. A 502 listener owned by any non-CODESYS process still BLOCKS. |
| `phase0/s1fix/harness/run_s1fix.ps1` | **New F05b runtime-verify gate.** It requires application_state `run`, the generated variables `PLC_PRG.Mb_Command` and `PLC_PRG.Mb_Status` readable online, and tcp/502 owned by the runtime service pid **after** the download. F06 runs only if this passes. |
| `phase0/s1fix/codesys/deploy.py` | PASS now also requires the online read-back of the generated variables. It falls back from gateway name to GUID, records the pre-login state, and writes the runtime boot application so that a service restart keeps the generated app. |

## GENERATION

**PASS (RUN 3 and RUN 4).**

| Item | Result |
|---|---|
| Generated ST | `PLC_PRG_decl.st` sha256 `8a4f98cf…`, `PLC_PRG_impl.st` `71ff2b02…`, `PLC_PRG.st` `6d57461e…`. Identical in both runs. |
| HR0 command word | `Mb_Command : WORD`, with `StartCommand := Mb_Command.0; StopCommand := Mb_Command.1;` |
| IR0 status word | `Mb_Status : WORD`, with `Mb_Status.0 := FanCommand; Mb_Status.1 := FanRunning; Mb_Status.2 := FanFault;` |
| Mapping artifact | `engineering/modbus_mapping.json`: HR0 → `Application.PLC_PRG.Mb_Command`, IR0 → `Application.PLC_PRG.Mb_Status`. It is generated with `verified:false`. |
| REAL values | SupplyTemp, Setpoint, FanSpeed and HeatingValve are **UNMAPPED** (REAL32 is out of scope; there was no guessing). |

## BUILD

**PASS (RUN 3 and RUN 4).**

Generated project, as read back in a fresh CODESYS process:

```text
Device [4096 0000 0004 3.5.22.30]          CODESYS Control Win V3 x64
  Plc Logic
    Application
      Task Configuration / MainTask / PLC_PRG
      PLC_PRG
  Ethernet [110 0000 0002 4.2.0.0]
    Modbus_TCP_Server [115 0000 0002 4.6.0.0]   Port = 502
      Holding Registers[0] (1000_0_0_0) -> Application.PLC_PRG.Mb_Command
      Input Registers[0]   (2000_0_0_0) -> Application.PLC_PRG.Mb_Status
```

- **Build:** 0 errors, 0 warnings in both the creation build (F02) and the fresh-process rebuild (F03), in both runs.
- **Fresh-process verify (F03):** the device IDs and parents, Port 502, both I/O mappings, PLC_PRG text equal to the generator output and the required variables all passed.

## DEPLOYMENT

**PASS (RUN 3 and RUN 4).**

F04 preflight (RUN 4 shown; RUN 3 was identical):

```text
runtime_service_running       = true
runtime_port_11740_listening  = true
gateway_port_1217_listening   = true
credentials_available         = true   (source: CODESYS_USER/CODESYS_PASSWORD, process env only)
tcp_502_free_before_deploy    = false  (old application running in the runtime)
tcp_502_owner_pid             = 24204  = runtime_service_pid 24204
replace_runtime_app_consent   = true   -> old runtime application replaced by the download
elevated                      = false
```

F05 deploy sequence, all through documented ScriptEngine calls in `CODESYS.exe --noUI`:

```text
open generated project -> set_simulation_mode(False) -> gateway "Gateway-1" + 127.0.0.1
-> set_default_credentials -> create_online_application -> login(Never, delete_foreign_apps=True)  [download]
-> start() -> application_state = run -> read_values -> create_boot_application (on runtime) -> logout
```

| Field | RUN 3 | RUN 4 |
|---|---|---|
| simulation_mode | false | false |
| gateway | Gateway-1 | Gateway-1 |
| logged_in | true | true |
| application_state after start | `run` | `run` |
| online read-back of generated variables | `Mb_Command=WORD#0`, `Mb_Status=WORD#0`, `StartCommand=FALSE`, `FanRunning=FALSE` | same |
| runtime boot application | created | created |
| duration | 52.3 s | 48.0 s |

No login prompt blocked the `--noUI` session, and no runtime user was created; the existing `CODESYS_USER` account was used.

The pre-login `application_state` reads `none` in both runs. That value reflects the not-yet-connected online object, not the device contents, so the old application was **not enumerated**. Its replacement is established by the `delete_foreign_apps=True` download and by the post-download checks in RUNTIME.

## RUNTIME

**PASS (RUN 3 and RUN 4).** F05b ran after the download, before any Modbus traffic:

```text
application_state            = run
generated_variables_online   = true   (PLC_PRG.Mb_Command and PLC_PRG.Mb_Status exist online -> generated app)
tcp_502_listening            = true
tcp_502_owner_pid            = 24204 = runtime_service_pid 24204
```

The application answering on port 502 is the generated S1-FIX app. Its own image variables are present online, the full download replaced any foreign application, and the Modbus behaviour below matches the generated logic.

## MODBUS

**PASS (RUN 3 and RUN 4).** Tested with pymodbus 3.15 `ModbusTcpClient` on 127.0.0.1:502, unit 1 (`phase0/s1fix/probe/modbus_probe.py`).

| Step | RUN 3 | RUN 4 |
|---|---|---|
| TCP connect / pymodbus connect | PASS / PASS | PASS / PASS |
| Baseline HR0 / IR0 | 0 / 0 | 0 / 0 |
| **START:** write HR0=1 | accepted (`WriteSingleRegisterResponse ... registers=[1]`), HR0 read-back 1 | accepted, HR0 read-back 1 |
| IR0 after START | **3** (first poll, about 20 ms) | **3** (first poll) |
| **STOP:** write HR0=2 | accepted, HR0 read-back 2 | accepted, HR0 read-back 2 |
| IR0 after STOP | **0** (first poll) | **0** (first poll) |
| Cleanup | HR0=0 written; final HR0/IR0 = 0/0 | same |

IR0=3 means FanCommand (bit 0) and FanRunning (bit 1) are set. IR0=0 after STOP means the fan was stopped by StopCommand.

## VERIFICATION

**PASS.** In both runs, all 8 acceptance checks of the probe were true:
- tcp_connect and pymodbus_connect
- start_write_accepted, start_hr_readback and start_ir_reached_3
- stop_write_accepted, stop_hr_readback and stop_ir_reached_0

The informational `baseline_hr0_ir0_zero` check was also true.

Only after those checks passed did the probe set `verified:true` on the HR0 and IR0 registers in `engineering/modbus_mapping.json`. The REAL variables remain UNMAPPED.

### RUN 3

| Step | process_exit_code | operation_status | Duration |
|---|---|---|---|
| F01 generate | 0 | PASS | 1.6 s |
| F02 CODESYS create + Modbus server + mapping + build | 0 | PASS | 60.6 s |
| F03 fresh-process verify | 0 | PASS | 42.2 s |
| F04 deploy preflight | – | PASS | – |
| F05 deploy (login/download/start) | 0 | PASS | 52.3 s |
| F05b runtime verify | – | PASS | – |
| F06 pymodbus probe | 0 | PASS | 2.0 s |

### RUN 4

| Step | process_exit_code | operation_status | Duration |
|---|---|---|---|
| F01 generate | 0 | PASS | 1.3 s |
| F02 CODESYS create + Modbus server + mapping + build | 0 | PASS | 49.2 s |
| F03 fresh-process verify | 0 | PASS | 39.9 s |
| F04 deploy preflight | – | PASS | – |
| F05 deploy (login/download/start) | 0 | PASS | 48.0 s |
| F05b runtime verify | – | PASS | – |
| F06 pymodbus probe | 0 | PASS | 1.9 s |

RUN 4 rebuilt everything in a fresh staging folder and downloaded again over the RUN 3 application, so the Modbus test was run twice against two independent downloads.

### RUN 3 / RUN 4 semantic comparison

**DETERMINISTIC.** Source: `docs/phase0/S1_FIX_comparison_run3_run4.json`, 0 differences across 24 semantic items.

The comparison covers:
- Generated ST hashes, `modbus_mapping.json` (including `verified:true`) and `codesys_plan.json`
- Create and verify device tree, server parameters, I/O mappings, build/rebuild results and check vectors
- **Deployment status**, **probe status**, **`modbus_probe.checks`**, and the full step vector (step, operation_status, process_exit_code) including F05b

The `.project` and `.app` byte hashes differ. They are informational only; byte equality is not required.

Evidence:
- Staging: `C:\AI_BMS_PHASE0\s1fix\run{3,4}\{generated,engineering,logs,evidence}`
- Repo copy: `docs/phase0/s1fix_evidence/run{3,4}/` (logs, `deployment_result.json`, `modbus_probe.json`, mapping and plan, generated ST, `harness_run{3,4}.json`; no binaries, no secrets)

## FINAL TABLE

| Item | Result | Evidence |
|---|---|---|
| Generated PLC | **PASS** | F01; ST hashes identical in RUN 3/4 |
| Modbus TCP Server | **PASS** | F02/F03 device tree `Ethernet → Modbus_TCP_Server [115]` |
| HR0 mapping | **PASS** | `Holding Registers[0] → Application.PLC_PRG.Mb_Command`; `verified:true` |
| IR0 mapping | **PASS** | `Input Registers[0] → Application.PLC_PRG.Mb_Status`; `verified:true` |
| Build | **PASS** | 0 errors / 0 warnings, creation build and rebuild |
| Deployment | **PASS** | F05: logged_in, download with delete_foreign_apps, boot app created |
| Runtime started | **PASS** | application_state `run`; generated variables read online |
| Port 502 | **PASS** | F05b: listening, owned by runtime pid 24204 running the generated app |
| pymodbus START | **PASS** | HR0=1 accepted, read-back 1 |
| HR0=1 → IR0=3 | **PASS** | IR0=3 on first poll, RUN 3 and RUN 4 |
| pymodbus STOP | **PASS** | HR0=2 accepted, read-back 2 |
| HR0=2 → IR0=0 | **PASS** | IR0=0 on first poll, RUN 3 and RUN 4 |
| RUN3/RUN4 semantic comparison | **PASS** | DETERMINISTIC, 0 differences, runtime and Modbus included |

## REMAINING ITEMS (not blockers for S1-FIX)

| # | Item | Classification |
|---|---|---|
| R-1 | Starting or restarting the SoftPLC service needs Administrator. The agent session is not elevated, and in this test the service was already running. Unattended pipelines need the service running beforehand, or an elevated operator. | ENVIRONMENT (precondition) |
| R-2 | Deployment replaces whatever application is on the target (`delete_foreign_apps=True`). It is gated by explicit consent (`S1FIX_REPLACE_RUNTIME_APP=1`). | PROCESS (by design) |
| R-3 | REAL values are unmapped (REAL32 encoding deliberately not attempted). | PRODUCT (deferred scope) |
| R-4 | The runtime boot application now holds the generated S1-FIX app, so the previous runtime application will not come back after a restart. | ENVIRONMENT (state change, consented) |

## RECOMMENDATION

S1-FIX is a **Full PASS**:
- **BL-1** (Modbus image in the generated PLC) is closed with evidence.
- **BL-2** (agentless Ethernet/Modbus_TCP_Server) is closed with evidence.
- **BL-3** (agentless deploy → runtime → real Modbus) is closed with evidence.

S3 was **not** started, as instructed.

## History: RUN 1 / RUN 2 (Minimum PASS)

RUN 1 and RUN 2 reached F01–F03 PASS. F04 was BLOCKED because credentials were not available and tcp/502 was held by a foreign runtime application without consent to replace it, so F05 and F06 were NOT_RUN. Those runs were semantically DETERMINISTIC (`docs/phase0/S1_FIX_comparison.json`). Their evidence remains in `docs/phase0/s1fix_evidence/run{1,2}/`.

The device and API discovery behind the Modbus server creation is in `docs/phase0/s1fix_evidence/discovery/discovery.json`. It was a one-time, read-only discovery step that came before the clean-runtime work, and it is not part of the RUN 3/RUN 4 deployment.
