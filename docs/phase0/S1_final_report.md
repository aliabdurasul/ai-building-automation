# S1 — Agentless Reproduction & Repeatability Test: Final Report

Date: 2026-10-05 · Test window: 09:59–10:21 (+03:00) · Runs: 2 · Supporting files: `S1_environment.json`, `S1_AGENTLESS_RUNBOOK.md`, `S1_run1.json`, `S1_run2.json`, `S1_comparison.json`, `S1_evidence.md`

**Executor note.** The runbook steps were executed by a Cursor agent acting strictly as a runbook operator. It ran shell commands only. No MCP server, LLM API, GUI or coordinate automation, `%TEMP%` patch or POC code edit was used inside any step. The harness (`phase0/s1/harness/run_s1.ps1`) only measures. Every PASS/FAIL below was assigned afterwards from read-back evidence.

---

## 1. Executive Summary

**The AHU chain cannot be reproduced end-to-end without agents.** Both runs stopped at the same two points:

1. **Modbus mapping in CODESYS.** The generated project has no Modbus TCP slave device, and the POC has no agentless way to add one. The clean mapping script reports `Modbus_TCP_Server not found`.
2. **PLC download/start.** The SoftPLC service cannot be started without Administrator rights. The only agentless online path (`codesys_runtime.py`) fails login with "Invalid user authentication on the target". No agentless download script exists.

Independently of these two blockers, **the generated PLC program has no Modbus interface** (no shadow variables, no command word). The runbook's HR0=1 → IR0=3 behaviour is therefore impossible by design, even if download had worked.

**What does work agentlessly, twice, with the same result:**

- ST generation, CODESYS project creation and build (0 errors), and CODESYS read-back verify.
- MasterSCADA project creation, Modbus configuration, and HMI build. These are design-time only and confirmed by fresh-process read-back (Modbus `fails=0`, HMI `76 checks, 0 fails`).
- HTML5 HMI file generation by the MasterSCADA *debug* runtime (141 files, byte-identical across runs).

**Determinism:**

- Semantic and read-back artifacts are **DETERMINISTIC**.
- Binary containers (`.project`, `.app`, `.fdb`) are **NON-DETERMINISTIC** at byte level (same size, different hash).
- The exit-code vector is identical across runs.

**Clean mapping: FAIL.** **OVERALL: FAIL.** **Decision: NO-GO** for agentless end-to-end.

## 2. Environment

The full snapshot is in `S1_environment.json`. Facts that matter for the outcome:

| Item | Value |
|---|---|
| OS | Windows 11 Pro 10.0.22000 x64. The session was **not elevated**. |
| CODESYS | IDE and Control Win V3 x64 3.5.22.30. The SoftPLC service was **Stopped** (Manual) before, during and after both runs. Gateway V3 was running. |
| CODESYS credentials | The environment variables were **not set**. This contradicts the Knowledge Pack. |
| MasterSCADA 4D | 1.2.18.32894. No Windows service is registered. The runtime used was the debug `IWIN32` started by the host. |
| Python / pymodbus | 3.11.9 / 3.15.0 |
| .NET | 4.8 (533325). The x64 host `AiBmsHmiPoc.exe` was prebuilt. |
| tcp/502 | **Not listening** for the whole test. No PLC of any origin was running. |
| Staging | CODESYS in `C:\AI_BMS_PHASE0\s1\run{1,2}`. MasterSCADA in `C:\AI_BMS_POC\master_scada_research\hmi_api_poc\phase0_s1\run{1,2}`, a new subfolder forced by the host's sandbox guard. |

## 3. Run 1

Times are from 09:59:26 to 10:09:40, about 10.2 minutes.

| Step | Status | rc | Duration | Evidence summary |
|---|---|---|---|---|
| S01 staging | PASS (MI) | – | – | Literal path substitution needed (MI-01, MI-02) |
| S02 generate ST | PASS | 0 | 1.1 s | 3 ST files |
| S03 CODESYS create+build | PASS | 0 | 66.3 s | 0 errors, 0 warnings |
| S04 CODESYS verify | PASS | 0 | 49.3 s | Read-back DECL/IMPL equals generator output |
| S05 clean mapping | **FAIL** | 0 | 36.9 s | `Modbus_TCP_Server not found` |
| S06 boot app + login | **FAIL** | 4 | 78.9 s | `.app` built; login: invalid user authentication |
| S07 SoftPLC start | **BLOCKED** | – | – | Cannot open service (non-elevated) |
| S08 Modbus probe | **FAIL** | 0 | 4.7 s | `connect: false` (timeout) |
| S09 MS create | PASS | 0 | 43.8 s | `.fdb` + `info.xml` |
| S10 MS Modbus config | PASS | 0 | 39.4 s | Constants from `Modbus.cs` |
| S11 MS verify | PASS | 0 | 42.0 s | Fresh-process read-back, fails=0 |
| S12 HMI build | PASS | 0 | 46.7 s | fails=0 |
| S13 HMI verify | PASS | 0 | 44.0 s | 76 checks, 0 fails |
| S15 MS runtime R/W | **FAIL** | 1 | 16.2 s | 127.0.0.1:502 refused |
| S16 HMI runtime | **FAIL** (generation OK) | 0 | 131.4 s | htdocs 141 files; FanStatus BadOutOfService; PLC unreachable |

## 4. Run 2

Times are from 10:11:04 to 10:20:59, about 9.9 minutes. The status vector and exit codes were **identical to Run 1** for every step.

Durations differed: S03 took 45.3 s against 66.3 s, and S06 took 109.9 s against 78.9 s. The only content difference was the timing-dependent quality code of the first S16 sample: `BadWaitingForInitialData` in Run 2 against `BadOutOfService` in Run 1. Details are in `S1_run2.json`.

## 5. Determinism

Source: `S1_comparison.json`. The comparison normalizes run folder names, ISO and MasterSCADA timestamps, GUIDs, PIDs, ephemeral ports and durations.

| Category | Artifacts | Verdict |
|---|---|---|
| PLC source | `PLC_PRG_decl.st`, `PLC_PRG_impl.st`, `PLC_PRG.st` | **DETERMINISTIC** (raw byte-identical) |
| CODESYS read-back | generate/verify/mapping/runtime logs, S04 DECL/IMPL read-back, probe JSON | **DETERMINISTIC** (identical after normalization) |
| CODESYS binaries | `.project` (225104 B both), `.app` (97508 B both) | **NON-DETERMINISTIC** (hashes differ) |
| MasterSCADA read-back | S09/S10/S11 logs, `info.xml` | **DETERMINISTIC** (after normalization) |
| MasterSCADA binary | `AHU_S1.fdb` (61644800 B both) | **NON-DETERMINISTIC** (hash differs) |
| HMI read-back | S12 log, S13 log + evidence JSON (76 checks) | **DETERMINISTIC** (after normalization) |
| HMI generated HTML5 | htdocs, 141 files | **DETERMINISTIC** (raw byte-identical) |
| Runtime | S15 log identical; S16 log differs in the first quality code | **NON-DETERMINISTIC** (timing-dependent status; there was no PLC) |
| Exit codes | all executed steps | **DETERMINISTIC** |

Verdicts:

- Semantic determinism: **DETERMINISTIC**.
- Byte-level determinism: **NON-DETERMINISTIC**.

Binary containers cannot be normalized, so equality has to be judged by read-back, not by file hash.

The MasterSCADA configuration's determinism is partly trivial. The Modbus values are compile-time constants in `Modbus.cs`, not derived from the PLC.

## 6. CODESYS

- **Generation and build: PASS (both runs).** `codesys_generate_ahu.py` ran under ScriptEngine `--noUI`. It created the project, added device "CODESYS Control Win V3 x64" 3.5.22.30, created MainTask → PLC_PRG, saved and built. Result: "Compile complete -- 0 errors, 0 warnings".
- **Verify: PASS.** A fresh CODESYS process reopened the project. The read-back DECL (350 B) and IMPL (454 B) are identical to the generator output.
- A successful build does not show the program can be run or communicates. Those are covered in sections 8 and 9.

## 7. PLC Generation

- `generate_st.py` is deterministic: the ST SHA256 is identical across runs.
- **Generated content:** 9 variables (`StartCommand`, `StopCommand`, `FanCommand`, `FanRunning`, `FanFault`, `SupplyTemp`, `Setpoint`, `FanSpeed`, `HeatingValve`) and simple IF logic.
- **The generated content has no Modbus interface.** There are no HR/IR shadow variables and no command or status word. A program that maps HR0 to a command and returns IR0=3 cannot be produced by this generator. Only the hand-written V2 PLC in the POC had that interface, and it was excluded by the rules.

## 8. PLC Runtime Test

- **Download: FAIL.** No agentless download script exists. The POC used MCP (`run_ahu_v2_deploy.py`). `codesys_runtime.py` builds a boot app (`.app` 97508 B) and attempts login, which fails with "Invalid user authentication on the target" (exit code 4, STATUS=PARTIAL).
- **The "MANUAL REQUIRED / REASON: Access Denied" text in `runtime_result.txt` is a hardcoded string** in `codesys_runtime.py` (lines 121–122). It does not describe what happened in this run.
- **SoftPLC service: BLOCKED.** A non-elevated `Start-Service` failed with "Cannot open ... service".
- **Execution: UNKNOWN.** The generated program never ran.
- **PLC program running during the HMI tests: NONE.** tcp/502 was not listening at any point. No PLC of unknown provenance was used.

## 9. Modbus

- **Clean mapping: FAIL.** `codesys_map_modbus_io.py` opened the project and wrote `{"error": "Modbus_TCP_Server not found"}`. The generated project has no Modbus TCP slave device. Adding one in the POC required MCP plus the patched `%TEMP%` handler (`device_h.py`), both of which are banned.
- **Verification: FAIL.** The external pymodbus probe got "Connection to (127.0.0.1, 502) failed: timed out" and `{"connect": false}`. No register was read back. HR0=1 → IR0=3 was not observed and cannot be observed with this generator's output.
- **Exit codes are not reliable evidence.** The mapping script returned 0 on failure and the probe returned 0 on a failed connection.

## 10. MasterSCADA

- **Project generation: PASS (both runs).** This used the vendor .NET object model from `AiBmsHmiPoc.exe` (`create`, `modbus`). A fresh-process `verify` read back IP 127.0.0.1, port 502, unit 1, FanCommand (Address 0, Output) and FanStatus (Address 0, Input), with `fails=0`.
- **This is design-time persistence only.** The Modbus values are hardcoded in `Modbus.cs`. They are not derived from the CODESYS mapping, which does not exist.
- **Runtime: FAIL.** `runtime` mode (debug EmulatorSession, UDP 31201) stopped at its pre-read of HR0 with "actively refused 127.0.0.1:502" (exit code 1). No MasterSCADA → PLC write or read took place.
- **Runtime class:** debug `IWIN32` started by the host. **This is not a production runtime.** `mplc_service.exe` exists, but no service is registered, and it was not tested.
- **Dependency:** every MasterSCADA step registers `InSAT.Framework.TestBase.UIServiceForTests`, which is an internal test DLL.

## 11. HMI

- **HMI generation (design time): PASS.** `hmibuild` from spec v3, then a fresh-process `hmiverify` with 76 checks and 0 fails. Checked: the window, every control (type, position, size, text), the `FanCommandSP` parameter (initial value 2), the server link from channel to parameter, and connections=2.
- **HTML5 output: PASS-level fact.** The debug runtime with IncludeHMI generated `htdocs` (141 files). `index.html` and `generated/windefs.js` contain `AHU_01_TEST` and the control names. The output was byte-identical across runs. Producing files does not mean the HMI works.
- **HMI runtime: FAIL.** During the 20 s hold, FanStatus had quality `BadOutOfService` (or `BadWaitingForInitialData`), and CODESYS HR0/IR0 returned `SocketException` before, during and after.
- `ms_FanCommand = 2 (Good)` is the parameter's initial value inside MasterSCADA. **It is not a write that reached a PLC.**
- No nginx was started, no browser was opened, and there was no operator read/write. **No agentless path exists for an HMI operator write.** The POC did this by clicking in the browser.

## 12. Manual Interventions

Each item below marks a point where automation currently stops.

| ID | Step | Intervention | Type |
|---|---|---|---|
| MI-01 | S01 | POC scripts hardcode `C:\AI_BMS_POC\...`. Staging copies needed literal path substitution: generate_st ×1, generate_ahu ×1, verify ×2, runtime ×3, map_modbus_io ×3, probe ×1. No logic change. | Automation gap (non-relocatable scripts) |
| MI-02 | S09–S16 | The host refuses targets outside `hmi_api_poc\`, so staging had to be a new subfolder inside the POC tree. | Automation gap (sandbox guard) |
| MI-03 (needed, not performed) | S07 | Start the SoftPLC service as Administrator. | Environment prerequisite |
| MI-04 (needed, not performed) | S06 | Provide CODESYS runtime credentials and handle the device/gateway selection for login. | Environment prerequisite / missing automation |
| MI-05 (needed, not performed) | S05 | Add the Modbus TCP slave device to the generated project. The POC only did this with MCP and a patched handler. | Missing generator capability |
| MI-06 (needed, not performed) | S16 | Start nginx and use a browser for the operator write. The POC did this manually. | Missing automation |

MI-03 to MI-06 were deliberately not performed. Doing them would have meant elevation, MCP or browser use, or a PLC of unknown provenance.

## 13. Temporary / Patch Dependencies

| Dependency | Evidence | Status in S1 |
|---|---|---|
| `%TEMP%\...\device_h.py` (patched mcptoolkit handler) | Present, written 2026-10-01 19:10 (`S1_environment.json`) | Not used. Without it, Modbus device add and mapping have no path. |
| Hardcoded path constants in POC scripts | MI-01 substitution counts | Required substitution |
| Hardcoded Modbus constants (`Modbus.cs`, `modbus_v2_probe.py`) | Source read | Used as-is |
| Hand-written V2 PLC (`codesys_ahu_v2_plc_map.py`) | Source read | Excluded by the rules |
| Hardcoded "Access Denied" message in `codesys_runtime.py` | Lines 121–122 | Misleading log text |

## 14. Vendor / Internal API Dependencies

As instructed, this section lists DEPENDENCY, EVIDENCE, RISK and STATUS only. It proposes no solutions.

| Dependency | Evidence | Risk | Status |
|---|---|---|---|
| MasterSCADA `InSAT.Framework.TestBase.UIServiceForTests` (internal test DLL) | Line "IUIService registered: ..." in every S09–S16 log | Unsupported or internal. It may change or disappear between versions. | In use. Required by every MasterSCADA step. |
| MasterSCADA object model (`MasterSCADA.*` types, `TypesManager`, `ApplicationHlp.Initialize`) | S09–S16 logs | Undocumented API surface | In use |
| MasterSCADA debug runtime (`IWIN32`, `DebugControllerInstance` statics, EmulatorSession) | S15/S16 "RUNTIME statics" lines | Debug-only runtime. Its behaviour in production is unknown. | In use. Production runtime UNKNOWN. |
| CODESYS ScriptEngine (`--runscript`, `--noUI`) | S03–S06 | Documented vendor API. Login behaviour under `--noUI` is unclear. | In use. Works for create, build and verify. |
| mcptoolkit-for-codesys (MCP) | POC scripts `run_ahu_v2_*.py` | Agent tooling | Excluded. It was the only POC path for device add and download. |
| MasterSCADA license | `S1_environment.json`: "Demo (per Knowledge Pack; not re-checked here)" | The limits of a demo license for runtime and automation are unknown | UNKNOWN. Not measured in S1. |
| CODESYS runtime license | Not recorded | Runtime operating mode/time limit unknown | UNKNOWN. Not measured in S1, because the runtime never started. |

## 15. Agentless Capability

| Capability | Result | Basis |
|---|---|---|
| CODESYS project generation from model | Agentless, repeatable | S02–S04, both runs |
| CODESYS build | Agentless, repeatable | 0 errors both runs |
| CODESYS Modbus device + mapping | Not agentless | S05 FAIL |
| PLC download / start | Not agentless (needs elevation, credentials, and a download path) | S06/S07 |
| External Modbus verification | Not possible (no PLC) | S08 FAIL |
| MasterSCADA design-time config + HMI | Agentless, repeatable (with MI-02 and the internal DLL) | S09–S13 read-back |
| MasterSCADA runtime / HMI runtime | Started agentlessly (debug only), but communication FAIL | S15/S16 |

## 16. Blockers

| # | Blocker | Evidence | Category | Recommendation |
|---|---|---|---|---|
| BL-1 | The generated PLC has no Modbus interface (no shadow variables or command/status word), so HR0 → IR0 is impossible by design | S04 read-back DECL | **F** | FIX |
| BL-2 | No agentless way to add a Modbus TCP slave device to the generated project. The clean mapping script fails. | S05 `modbus_io_map.json` | **F** | FIX |
| BL-3 | No agentless PLC download step. The POC download existed only via MCP. | Script inventory; S06 | **A** | FIX |
| BL-4 | CODESYS runtime login under `--noUI` fails with "Invalid user authentication on the target". The credential environment variables are absent and how credentials get provided is undefined. | S06 | **G** | VENDOR QUESTION |
| BL-5 | The SoftPLC service needs Administrator to start. The service is set to Manual. | S07 | **G** | WORKAROUND |
| BL-6 | MasterSCADA automation depends on an internal test DLL (`UIServiceForTests`) | S09–S16 logs | **D** | VENDOR QUESTION |
| BL-7 | Only the debug runtime (IWIN32/EmulatorSession) can be exercised. The production runtime (`mplc_service`) is unregistered and untested. | `S1_environment.json`, S15/S16 | **C** | VENDOR QUESTION |
| BL-8 | No agentless HMI operator write or read path. The POC used browser clicks and a manually started nginx. | Script inventory, S16 | **A** | FIX |
| BL-9 | MasterSCADA Modbus configuration is hardcoded and not derived from the PLC mapping | `Modbus.cs`; S10/S11 | **A** | FIX |
| BL-10 | POC scripts can't be relocated, and the host sandbox guard pins its location | MI-01, MI-02 | **A** | FIX |
| BL-11 | Exit codes report success when the step failed (mapping rc 0, probe rc 0, hmiruntime rc 0 with bad quality) | S05, S08, S16 | **A** | FIX |
| R-1 (risk, not blocker) | Binary artifacts are not byte-deterministic (`.project`, `.app`, `.fdb`) | `S1_comparison.json` | **B/C** | WORKAROUND (judge equality by read-back) |

Licensing is listed only in section 14, without a recommendation, as instructed.

## 17. Evidence

The index is in `S1_evidence.md`. Primary sources:

- Raw per-step records: `evidence/run{1,2}/harness_run{1,2}.json`
- Per-step stdout and stderr: `evidence/run{1,2}/S*.txt` and `*.log`
- HMI read-back JSON: `S13_hmi_verify_evidence.json`
- Runtime events: `S15/S16 *_events.jsonl`
- Comparison: `S1_comparison.json`
- Generated artifacts, kept in the staging folders listed in section 2

## 18. GO / NO-GO

**NO-GO.** The agentless end-to-end AHU chain did not reproduce in either run. Three blockers in the critical path need either new generator capability or an environment prerequisite: BL-1, BL-2, and BL-3/BL-4/BL-5 together.

What S1 does prove, with evidence and repeatability:

- The model → ST → CODESYS project → build → verify path is agentless and deterministic in content.
- The MasterSCADA design-time project, Modbus configuration and HMI generation are agentless and deterministic in content. This comes with two caveats: the internal test DLL dependency, and Modbus values that are hardcoded rather than derived from the PLC.

What S1 does not prove: PLC download/execution, Modbus communication, MasterSCADA runtime read/write, HMI runtime, end-to-end behaviour, and any production runtime.

As instructed, no product development was started. The next phase is left to the user's decision.

---

```
AGENTLESS CAPABILITY

CODESYS generation:        PASS
CODESYS build:             PASS
PLC download:              FAIL
PLC execution:             UNKNOWN   (never reached; generated program also lacks a Modbus interface)
Modbus mapping:            FAIL      (Clean mapping: FAIL — "Modbus_TCP_Server not found")
Modbus verification:       FAIL      (no register read-back; tcp/502 never listening)
MasterSCADA generation:    PASS      (design-time, fresh-process read-back, both runs)
MasterSCADA runtime:       FAIL      (debug runtime only; 127.0.0.1:502 refused)
HMI generation:            PASS      (76/76 read-back checks; HTML5 htdocs generated, byte-identical)
HMI runtime:               FAIL      (BadOutOfService; no PLC; no operator write path)
End-to-end:                FAIL
Repeatability:             PASS      (scope: executed agentless steps S02–S16; identical status vector,
                                      semantic artifacts DETERMINISTIC, binaries NON-DETERMINISTIC)

OVERALL: FAIL — The AHU chain is NOT reproducible agentlessly. Only the design-time layers
(CODESYS generate/build/verify, MasterSCADA config + HMI build/verify) are agentless and repeatable;
every step that requires a running generated PLC (mapping, download, Modbus, runtime, HMI runtime)
fails or is blocked.
```
