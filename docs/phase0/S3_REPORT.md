# S3 — MODBUS TYPE & MAPPING ENGINE — REPORT

## S3 RESULT

**PASS.** Both final runs, `run1` and `run2`, passed every harness stage (F00…F08) for both profiles, `types` and `ahu`. 18 signal mappings were verified against the real local SoftPLC (CODESYS Control Win V3 x64, 3.5.22.30) using external pymodbus reads and writes plus PLC-side online read-back. `compare_s3.py run1 run2` reports **DETERMINISTIC**: 94 semantic items, 0 differences.

| Step | types | ahu |
|---|---|---|
| F01 generate (validate → allocate → ST/mapping/plan) | PASS | PASS |
| F02 CODESYS create + map + build (0 errors / 0 warnings) | PASS | PASS |
| F03 fresh-reopen verify (tree, channels, mappings, ST, rebuild) | PASS | PASS |
| F04 deploy preflight | PASS | PASS |
| F05 deploy (clean SoftPLC, app replaced, RUN) | PASS | PASS |
| F05b runtime verify (RUN, tcp/502 owned by runtime) | PASS | PASS |
| F06 S1 regression (HR0=1 → IR0=3, HR0=2 → IR0=0) | PASS | PASS |
| F07 type/mapping verification | PASS (12 signals) | PASS (6 signals) |
| F07a PLC online bridge | PASS | PASS |

The global steps also passed in both runs: F00 preflight (INFO), F00b engine self-test (PASS, 26 tests) and F08 post-run state (INFO).

The harness records each step's process exit code (`process.exit_code`) separately from its operation result (`operation.status`). No step was marked PASS on exit code alone; every PASS comes from the step's own result JSON and checks.

## TYPES

| Canonical type | PLC type | Registers | Signedness | Verified in |
|---|---|---|---|---|
| BOOL | BOOL | bit | — | COIL (write), DISCRETE_INPUT (read) |
| INT16 | INT | 1 | signed, two's complement | HR (write), IR (read) |
| UINT16 | UINT | 1 | unsigned | HR (write), IR (read) |
| WORD | WORD | 1 | unsigned bit field | HR (write), IR (read); S1 Command/Status bits |
| REAL32 | REAL | 2 | IEEE-754 binary32 | HR (write, READ_WRITE), IR (read) |

Values tested. All were decoded from Modbus and compared with the PLC online value.

| Type | Read path: PLC → Modbus → decode | Write path: Modbus → PLC online read-back |
|---|---|---|
| INT16 | −1234 (raw 64302), 1234, −32768, 32767 | −1234, 1234, −32768, 0 |
| UINT16 | 1234, 65535, 0, 40000 | 1234, 54321, 65535, 0 |
| WORD | 42330, 1, 65535, 32768 | 0xBEEF, 0x0F0F, 0xFFFF, 0 |
| REAL32 | 21.5, 22.0, 18.25, 123.456 | 21.5, 18.25, 123.456, 22.0 |
| BOOL | TRUE, FALSE, TRUE, FALSE (DI) | TRUE, FALSE, TRUE, FALSE (coil) |

## AREAS

| Area | Function codes | Direction | Status |
|---|---|---|---|
| COIL | FC1 read, FC5/FC15 write | WRITE | verified |
| DISCRETE_INPUT | FC2 | READ | verified |
| HOLDING_REGISTER | FC3 read, FC6/FC16 write | WRITE / READ_WRITE | verified |
| INPUT_REGISTER | FC4 | READ | verified |

These platform facts were measured, not assumed. Discovery evidence is in `C:\AI_BMS_PHASE0\s3\discovery\` and the dev runs.

- **Register capacity:** the ModbusTCP Server Device 4.6.0.0 in this project exposes 10 holding registers and 10 input registers. HR10 and coil 160 return Modbus exception 2.
- **Coils and discrete inputs share register memory** (DistinctBitAreas = FALSE). Coil *n* is a bit of holding register *n*//16, and discrete input *n* is a bit of input register *n*//16. The PLC bit is ((n % 16) + 8) % 16, so the two bytes are swapped. Evidence: writing coil 0 made HR0 = 256, and coil 8 → HR0 = 1. Run evidence: writing TestCoil (coil 144) gave `overlay_register_raw` [256] on HR9, mapped to HR9 bit 8.
- **Bit-area placement:** the allocator gives bit areas whole registers, taken from the top register downwards (register 9 first). This keeps them clear of register signals, which are allocated from the bottom.

## REAL32 BYTE ORDER

Big-endian within each 16-bit register (the Modbus standard).

## REAL32 WORD ORDER

**CDAB: the low word comes first.** The register at the lower address holds the least-significant 16 bits of the IEEE-754 value.

## REAL32 REGISTER ORDER

register[n] = low word and register[n+1] = high word, with big-endian bytes in each register.

How the order was determined:
- The generator copies the REAL's two in-memory words into two WORD image variables mapped to consecutive registers.
- The verifier decodes every sample with all four candidate orders: ABCD, CDAB, BADC and DCBA.
- It keeps only the orders that reproduce the PLC's float32 bit pattern exactly, and takes the intersection across all samples. The result had to be unique, otherwise the run stops.
- In both runs and both profiles the intersection was exactly `["CDAB"]`.

Evidence samples:

| Value | Registers [n, n+1] | float32 bits |
|---|---|---|
| 21.5 | [0, 16812] | 41AC0000 |
| 22.0 | [0, 16816] | 41B00000 |
| 18.25 | [0, 16786] | 41920000 |
| 123.456 | [59769, 17142] | 42F6E979 |
| 50.0 (FanSpeed) | [0, 16968] | 42480000 |
| 100.0 (HeatingValve) | [0, 17096] | 42C80000 |
| 21.0 (SupplyTemp) | [0, 16808] | 41A80000 |

Writes use the measured order (FC16). For example, Setpoint 23.5 → [0, 16828] was read back as REAL#23.5 on the PLC.

## TOLERANCE

**Bit-exact float32.** Each check requires the Modbus-decoded float32 to equal the PLC REAL value, and both to equal float32(intended decimal). No epsilon is used.

The values 21.5, 22.0, 18.25, 20.0 and 23.5 are exactly representable. 123.456 is compared as float32(123.456) = 123.45600128173828 on all three sides.

INT16, UINT16, WORD and BOOL use exact integer or boolean equality. Scale is 1.0 for every mapped signal.

## WRITE TEST

**PASS.** Each case recorded four checks:
1. The pymodbus write was accepted (FC5, FC6 or FC16).
2. The Modbus read-back equalled the written registers or bit.
3. The PLC online read-back (`PLC_PRG.<var>` through the CODESYS online API bridge) equalled the intended value.
4. The PLC value settled: it was polled until the intended value appeared, then confirmed by a second read.

Write acceptance alone never produces a PASS.

## READ TEST

**PASS.** For each case:
1. The bridge injected a value into the PLC variable (`set_prepared_value` / `write_prepared_values`).
2. The verifier waited until the PLC online value showed it.
3. pymodbus read the register or bit (FC2 or FC4), and the result was decoded with the canonical codec.
4. The decoded value had to equal the PLC value.

The PLC was then re-read to confirm the value was stable. Values computed by the PLC program itself were also checked: AHU SupplyTemp, FanSpeed and HeatingValve, and the S1 Status bits.

## PLC READ-BACK

**PASS.** The online bridge (`plc_online_bridge.py`, ScriptEngine) logs in with `OnlineChangeOption.Never`, so it never re-downloads. Each run used 36–37 requests for the types profile and 19 for the ahu profile, all answered.

The CODESYS online value cache can briefly lag behind a write. The verifier therefore polls (6 s timeout, 0.25 s interval) and requires two consecutive agreeing reads. The number of polling requests can vary between runs; that is expected and not part of the determinism comparison.

## PYMODBUS TEST

**PASS.** pymodbus 3.15 against 127.0.0.1:502, device_id 1. In each run:
- types profile: 5 initial reads + 15 injected reads, 20 writes (each with an observe pass afterwards), and the S1 regression;
- ahu profile: 4 initial reads, 3 Setpoint writes (20.0, 23.5, 22.0), and checks after each write.

The AHU heating behaviour matched on both the PLC side and the Modbus side:

| SupplyTemp | Setpoint | Expected HeatingValve | PLC | Modbus |
|---|---|---|---|---|
| 21.0 | 20.0 | 0.0 | 0.0 | 0.0 |
| 21.0 | 23.5 | 100.0 | 100.0 | 100.0 |
| 21.0 | 22.0 | 100.0 | 100.0 | 100.0 |

## DETERMINISM

**DETERMINISTIC** (`docs/phase0/S3_comparison_run1_run2.json`). The 94 semantic items compared include:
- engine self-test;
- model sha256 and allocation;
- generated ST (sha256);
- `allocation.json`, `codesys_plan.json`, and `modbus_mapping.json` including the verified flags and measured orders;
- CODESYS devices, server parameters, channel counts, I/O mappings and build;
- the fresh-verify device tree, ST and rebuild;
- deploy state;
- S1 regression checks;
- every typed case (intended, raw registers, decoded value, PLC value, checks), REAL32 samples and candidates, measured ordering, behaviour table, per-signal verdicts and tolerance;
- the step status vector.

Stage paths are normalised to `<STAGE>`, and timestamps and durations are dropped. The `.project` and `.app` binaries differ byte for byte; that is informational only and not required to match.

Allocator determinism is also covered by `test_engine.py`: the allocation is identical across 20 shuffled signal orders.

## RUN1

PASS for every step in both profiles: types 12/12 signals verified, ahu 6/6, S1 regression PASS. Evidence: `C:\AI_BMS_PHASE0\s3\run1\`, with a copy in `docs/phase0/s3_evidence/run1/`.

## RUN2

PASS for every step in both profiles, identical semantics to run1. Evidence: `C:\AI_BMS_PHASE0\s3\run2\`, with a copy in `docs/phase0/s3_evidence/run2/`.

Two earlier run2 attempts were set aside and kept, but they are not counted:
- `run2_aborted`: a duplicated shell invocation was killed after F03. It never reached deployment.
- `run2_blocked`: the harness ran with the credential environment variables missing. F04 correctly reported BLOCKED and F05–F07 reported NOT_RUN.

The counted run2 was a fresh, clean staging.

---

## VERIFIED

`verified:true` was set by F07 (and by F06 for Command/Status) only after a real runtime test. The verifier writes `engineering/modbus_mapping.json` in each profile's stage folder.

| Profile | Tag | Type | Direction | Area | Address | Registers / overlay | Cases per run |
|---|---|---|---|---|---|---|---|
| types / ahu | Command | WORD (bits 0 Start, 1 Stop) | WRITE | HR | 0 | [0] | S1 regression |
| types / ahu | Status | WORD (bits 0 FanCommand, 1 FanRunning, 2 FanFault) | READ | IR | 0 | [0] | S1 regression |
| types | TestInt16Write | INT16 | WRITE | HR | 1 | [1] | 4 |
| types | TestReal32Write | REAL32 | WRITE | HR | 2 | [2, 3] | 4 |
| types | TestUInt16Write | UINT16 | WRITE | HR | 4 | [4] | 4 |
| types | TestWordWrite | WORD | WRITE | HR | 5 | [5] | 4 |
| types | TestInt16Read | INT16 | READ | IR | 1 | [1] | 8 |
| types | TestReal32Read | REAL32 | READ | IR | 2 | [2, 3] | 8 |
| types | TestUInt16Read | UINT16 | READ | IR | 4 | [4] | 8 |
| types | TestWordRead | WORD | READ | IR | 5 | [5] | 8 |
| types | TestCoil | BOOL | WRITE | COIL | 144 | HR9 PLC bit 8 | 4 |
| types | TestDiscreteInput | BOOL | READ | DISCRETE_INPUT | 144 | IR9 PLC bit 8 | 8 |
| ahu | Setpoint | REAL32 | READ_WRITE | HR | 1 | [1, 2] | 3 |
| ahu | FanSpeed | REAL32 | READ | IR | 1 | [1, 2] | 4 |
| ahu | HeatingValve | REAL32 | READ | IR | 3 | [3, 4] | 4 |
| ahu | SupplyTemp | REAL32 | READ | IR | 5 | [5, 6] | 4 |

In REAL mode the AHU values are the PLC program's own values: SupplyTemp 21.0, FanSpeed 50.0, and HeatingValve computed by the S1 logic. Nothing was injected for the AHU signals; only s3_test signals were injected.

## GENERATED

The generator (`phase0/s3/generator/generate.py`) produces these from the canonical model (`phase0/s3/model/s3_model.json`) for each profile:
- `generated/PLC_PRG_decl.st`, `PLC_PRG_impl.st`, `PLC_PRG.st`
- `engineering/allocation.json`
- `engineering/modbus_mapping.json` (schema `s3.modbus_mapping.v1`; written with `verified:false` and orders `UNVERIFIED`)
- `engineering/codesys_plan.json`

The pipeline order is fixed: validate, then allocate, then generate. The validator runs before any CODESYS step, and a validation failure stops the run before F02.

Validator rules (each covered by a unit test):
- missing datatype, area, tag or direction is invalid;
- duplicate tags or PLC variables are invalid;
- BOOL in a register area is invalid unless it is a bit of a bit-packed WORD;
- non-BOOL types in a bit area are invalid;
- direction must match the area (DI and IR are read-only);
- REAL32 must have length 2; length 1 is invalid;
- duplicate or overlapping addresses are invalid, including a REAL32 overlapping another signal;
- addresses beyond the measured capacity are invalid;
- scale is only allowed on INT16/UINT16;
- byte order, word order and register order in the model are rejected, because they are measured, never declared.

Allocator: there are no magic addresses. Signals are sorted by tag. Pinned signals are placed first (the S1 Command/Status words at HR0/IR0, kept compatible with S1). The rest are auto-allocated into the lowest free run of registers. Bit areas take whole registers from the top down. Output order is (area, address, tag), independent of the model's ordering.

Generator rules that came from measurement:
- Every Modbus channel is mapped to an image variable (`Mb_<tag>` or `Mb_<tag>_W0/_W1`) that PLC_PRG references. CODESYS only refreshes I/O-mapped variables that a task actually uses, so unused mapped variables were never updated (dev2 evidence).
- REAL32 is moved between the REAL's memory and the two WORD images through `POINTER TO ARRAY[0..1] OF WORD`, so no conversion is applied.
- A READ_WRITE REAL is copied into the PLC variable only when its registers change. This lets the PLC keep its own value until a Modbus client writes.

## UNMAPPED

- Profile `types`: SupplyTemp, Setpoint, FanSpeed and HeatingValve are deliberately left out of this profile. They are mapped and verified in profile `ahu`, because the 10-register capacity per area doesn't allow both sets in one project.
- Profile `ahu`: nothing; all AHU variables in the model are mapped.

## UNSUPPORTED

These were measured and recorded in `platform.unsupported` in the mapping:
1. **DistinctBitAreas = TRUE (separate coil and discrete-input areas).** ScriptEngine stores the parameter, but the coil and discrete-input channels are never generated, even after save and reopen.
2. **More than 10 registers per area.** Changing the assembly-size parameters through ScriptEngine does not regenerate channels, and `device.update()` resets them.
3. **A PLC-originated value of a READ_WRITE holding register being visible to FC3.** UpdateableHolding output channels aren't generated through ScriptEngine, so FC3 returns the last value a client wrote. Setpoint is therefore verified as WRITE (Modbus → PLC); its PLC initial value 22.0 is not readable through FC3 before the first write.
4. **Scale ≠ 1.0, and BOOL bit-packed into INPUT_REGISTER outside a WORD.** The validator supports these, but no signal uses them, so they are not runtime-verified.

## FILES CHANGED

New (`phase0/s3/`):
- `model/s3_model.json`: canonical model with platform facts, variables, signals and profiles
- `engine/canonical.py`: datatypes, areas, validator, allocator, REAL32/INT16 codec
- `engine/test_engine.py`: 26 engine unit tests
- `generator/generate.py`: ST, mapping, allocation and CODESYS plan generator
- `codesys/plc_online_bridge.py`: ScriptEngine online read/write bridge (no download)
- `codesys/discover_server.py`, `discover_reopen.py`, `discover_update.py`: one-off measurements of the Modbus server device, run in a scratch folder only
- `probe/s1_regression.py`: F06
- `probe/typed_verify.py`: F07
- `harness/run_s3.ps1`: stages F00…F08
- `harness/compare_s3.py`: semantic run comparison

Modified, backward-compatible with S1-FIX (S1 regression PASS in both runs):
- `phase0/s1fix/codesys/create_project.py` and `verify_project.py`: optional `bit_index` for bit-channel mapping, and an optional `channel_counts` check

Docs and evidence:
- `docs/phase0/S3_REPORT.md`
- `docs/phase0/S3_comparison_run1_run2.json`
- `docs/phase0/s3_evidence/run1/`, `run2/`, plus the non-counted `dev1`…`dev4` and `run2_blocked`

Not touched: `/ahu`, the existing AHU HMI, `C:\AI_BMS_POC`, MasterSCADA, Windows security and firewall settings. No MCP, LLM API, GUI automation or mouse/keyboard automation was used.

## LIMITATIONS

- **Capacity:** 10 HR and 10 IR per project, with coils and discrete inputs sharing those registers. A larger point list needs another way to configure the device; the scripting interface can't change the size.
- **Coil and discrete-input bits sit in the high byte first** (PLC bit offset 8). The allocator places them in dedicated registers so they never collide with register signals.
- **READ_WRITE holding registers are effectively write-only** for PLC-originated values (see UNSUPPORTED 3).
- **Runtime availability:** the SoftPLC appears to run in demo mode. The service stopped about 2 hours after it started (between 13:15 and 13:20) and had to be restarted by an Administrator. A full S3 run takes about 9 minutes. The agent did not try to restart or elevate on its own.
- **Credentials:** the agent's shell lost `CODESYS_USER`/`CODESYS_PASSWORD` when its session was restored. The counted run2 therefore set them in the same process that ran the harness and cleared them afterwards.
  - They were never written to repo files, logs, evidence or reports. A binary-inclusive scan of the repo, `docs/` and `C:\AI_BMS_PHASE0\s3` found no matches.
  - The command line that set them may be kept in the local IDE terminal history (outside the repo). Consider rotating the password.
- **Online values:** the PLC online cache refreshes asynchronously, which the verifier handles by polling. HMI or SCADA consumers that use the CODESYS online API must allow for the same lag.

## NEXT: S6

S3 is complete. S6 has not been started, and S2 and S7 have not been touched.
