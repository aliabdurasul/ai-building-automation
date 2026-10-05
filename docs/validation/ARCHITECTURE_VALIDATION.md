# AI-BMS Architecture Validation Report

**Snapshot:** 2026-10-05  
**Scope:** Knowledge Pack cross-validation (POC `C:\AI_BMS_POC\`, 2026-10-01 .. 2026-10-03)  
**Purpose:** Determine what the POC actually proved, what must not be carried to production, and what must be validated before implementation begins.  
**Rule:** Nothing is `CONFIRMED` unless backed by executed test evidence in the Knowledge Pack.

---

## Status vocabulary (used throughout)

| Status | Meaning |
|---|---|
| **CONFIRMED** | Executed test with log/screenshot/JSON evidence on the POC machine |
| **PROBABLE** | Strong indirect evidence; not end-to-end verified |
| **UNKNOWN** | Not verified |
| **FAILED** | Tried; did not work (see §Cross-check contradictions) |
| **BLOCKED** | Cannot be done with current tooling/permissions without manual or external step |
| **DEPRECATED** | Superseded; do not rely on it |

---

## Cross-check: contradictions and alignment

The Knowledge Pack (`00`–`14`, index) is internally consistent on core facts. Older POC notes (`architecture.md`, `modbus_mapping.md`, `plc_model.md`, `hmi_tags.md`) align with the pack on register mapping and data flow; the index correctly states they are **superseded where they conflict**. No material factual contradiction was found on proven chain items.

| Topic | Pack A | Pack B | Resolution |
|---|---|---|---|
| Canonical model drives all artifacts | `01` link #17 NOT IMPLEMENTED | `14` NEXT step 1 | **Consistent** — not done |
| Coils as command path | `03` FAILED | `08` F7 root cause UNKNOWN | **Minor gap** — failure is CONFIRMED; root cause remains PROBABLE (no mapping / area size 0) |
| Modbus I/O mapping without patch | `02` CONFIRMED (fragile, patched handler) | `12` Q3 HIGH priority | **Consistent tension** — mapping works in POC but depends on fragile `%TEMP%` patch; clean ScriptEngine-only path not re-verified |
| HMI write path | `05` v1/v2 BLOCKED, v3 CONFIRMED | `08` F20–F21 | **Consistent** |
| FUXA | `01` PROBABLE, UI write NOT proven | `07` M10/M11 | **Consistent** |
| MasterSCADA early verdicts | `04` DEPRECATED for `deep_re`, `runtime_poc_modbus` E2E | `07` S13 DEPRECATED | **Consistent** — later `api_poc` + `runtime_integration_test` supersede |
| CODESYS runtime state during HMI tests | `06` service listed Stopped in one inspection | `01` HMI tests ran with PLC active | **Environmental inconsistency** — re-check runtime before any test; not a logic contradiction |
| Agent / Cursor dependency | `02` Cursor MCP config empty | `11` AF7 | **Consistent** — mcptoolkit used by Python scripts, not Cursor agent at runtime |
| `13` decisions PD1–PD11 | marked PROPOSED | `14` NEXT | **Not yet approved** — production architecture is recommendation only |

**Critical separation (POC ≠ product):**

- POC register map (`HR0=FanCommand`, values 1/2/3) is **POC mapping**, not product requirement (`03`, `10` P1).
- V2 PLC sequence/ramps/thermal model is **demo plant simulation**, not control strategy (`02` §5, `10` P2).
- `bms_web` engineering/AI pipeline is a **fixture**, not real AI (`07` M9, `14`).
- Agent tooling artifacts (`recovery/`, UTF-16 fixes, shell one-liner truncation) are **environment defects**, not architecture (`08` F28–F30).

---

## 1. Current proven system

### What the POC actually proved (CONFIRMED)

On **one machine**, **one AHU equipment type**, **localhost** topology, **CODESYS 3.5.22.30** + **MasterSCADA 4D 1.2.18.32894** + **Demo license**:

```
[Manual once: gateway path in IDE; elevated SoftPLC service start]
        ↓
CODESYS headless engineering (ScriptEngine --noUI AND mcptoolkit MCP)
        ↓
AI_BMS_SIMPLE_AHU.project — build 0 errors, download, SoftPLC RUN
        ↓
Modbus TCP Server 127.0.0.1:502 — HR=PLC inputs, IR=PLC outputs
        ↓
External clients read/write (pymodbus, bms_web, MasterSCADA runtime)
        ↓
MasterSCADA project generated via vendor .NET API (x64 host, no GUI)
        ↓
MasterSCADA headless runtime (EmulatorSession / StartDriver) ↔ CODESYS
        ↓
MasterSCADA HMI generated via API (v3: server parameter write path)
        ↓
HMI web read + write confirmed (HR0 1/2, IR0 3/0)
```

### Link-by-link evidence summary

| Layer | Proven capability | Status | Key constraint |
|---|---|---|---|
| CODESYS offline engineering | create, device tree, POU text, task, build | CONFIRMED | ScriptEngine + mcptoolkit both work |
| CODESYS online ops | login, download, start, read, write | CONFIRMED | **After manual gateway setup**; mcptoolkit only (ScriptEngine login FAILED) |
| Modbus server + mapping | 15/15 I/O map, INT16 read/write | CONFIRMED | Patched handler fragile; REAL direct map FAILED; coils FAILED |
| Modbus clients | pymodbus V2 full probe all true | CONFIRMED | Single unit id 1 used; device param shows 0 |
| Web BMS (`bms_web`) | REAL mode read/write, graceful offline | CONFIRMED | POC adapter; not production HMI |
| MasterSCADA project gen | create/save, Modbus module/channels, verify fails=0 | CONFIRMED | Hardcoded spec; version-pinned internals |
| MasterSCADA runtime | read/write vs CODESYS registers | CONFIRMED | Debug EmulatorSession only; Demo license |
| MasterSCADA HMI | build 76/76, runtime read+write | CONFIRMED | **v3 only** (server param → channel Output) |
| Deterministic ST from JSON | `ahu01.json` → ST → build 0 errors | CONFIRMED | Simple model; not canonical |
| One model → all artifacts | — | **NOT DONE** | Each POC had its own spec |
| Real AI from drawings | — | **NOT DONE** | Fixture only |

### Technical facts reusable beyond POC (CONFIRMED)

- Modbus direction: **Holding Registers = PLC inputs (commands)**; **Input Registers = PLC outputs (status)** (`03` K5).
- Scaled INT shadow variables work; **REAL on single register word reads 0** (`03` K6).
- Bit-packed HR command word with edge detection works (`03`, `08` F6).
- MasterSCADA bootstrap requires `IUIService`, `SetDllDirectory(bin)`, save-before-dispose (`04` K10–K11).
- HMI write requires: **control → LREAL server parameter → SetLink → INT channel Output** (`05` K17).
- HMI read: **channel Input → control** direct link (`05` K18).
- Verification must use **fresh-process read-back + PLC register probe**; API `code:0` ≠ applied (`11` AF6, v2 failure).

### What is NOT proven

- Multiple equipment types, multiple PLCs, remote networks.
- Production MasterSCADA runtime (`mplc_service.exe`), license limits, long-run stability.
- Alarms, trends/archives, OPC UA, other protocols via API.
- REAL/32-bit cross-vendor word order.
- Other HMI control types for write (only NumericUpDown tested).
- Revision/regeneration, rollback, project isolation at scale.
- Agentless full pipeline (manual gateway + elevation remain).
- Real LLM → canonical model extraction.

---

## 2. Agent dependency analysis

The POC used **coding agents** (Cursor/Cline/Claude) for exploration, scripting, and recovery. **mcptoolkit MCP was invoked by Python test scripts**, not by Cursor (`02`: `.cursor/mcp.json` empty). The product must not depend on either at runtime.

| POC agent / human behavior | Production replacement | Class |
|---|---|---|
| Reverse-engineer MasterSCADA .NET API (decompile, static analysis) | One-time adapter design doc + version-pinned integration tests; no runtime RE | **Deterministic** (dev-time only) |
| Iterate HMI architecture v1→v2→v3 by trial | Encode v3 rule in generator spec upfront; validator rejects v1/v2 patterns | **Deterministic** |
| Write hardcoded C# builders (`Modbus.cs`, `HmiBuilder.cs`) per experiment | Model-driven generator from canonical schema | **Deterministic** |
| Patch `%TEMP%` mcptoolkit `device_h.py` for map_io | Own ScriptEngine I/O-mapping operation in CODESYS adapter | **Deterministic** |
| Python/PowerShell orchestration scripts (`run_*.py`) | CI pipeline invoking adapters with explicit CLI | **Deterministic** |
| Watchdog kill hung CODESYS (90 s login hang) | Adapter preflight checks + bounded timeouts + fail-fast | **Deterministic** |
| Manual IDE: gateway/active path setup | Commissioning runbook + preflight gate ("gateway configured?") | **Human** (+ future API if Q1 resolved) |
| Elevated SoftPLC service start | Admin/service-account provisioning in deployment runbook | **Human / ops** |
| DOM click / coordinate click HMI test workarounds | Automated test harness using documented WriteData protocol | **Deterministic** |
| Agent file encoding recovery (UTF-16, truncated C#) | Normal dev tooling; not product concern | **DEPRECATED** (do not replicate) |
| Shell one-liner file rewrite (F28 truncation) | Standard editor/CI; code review | **DEPRECATED** |
| "Engineering analysis" fixture in bms_web | LLM-assisted **model draft** with schema validation + human approval | **LLM + Human** |
| Signal/point extraction from PDF/DWG | LLM or CV pipeline → proposed canonical model fields only | **LLM + Human** |
| Equipment/control strategy decisions | Human engineer + certified templates | **Human** |
| Register address assignment | Deterministic allocator from canonical model | **Deterministic** |
| PLC control logic (sequence, ramps, thermal sim) | Certified template library + generator; **not** free-form LLM code | **Deterministic** |
| Choosing Modbus vs other fieldbus | Human + model configuration | **Human** |
| MasterSCADA `UIServiceForTests` via reflection | Encapsulate in adapter; evaluate own IUIService (Q13) | **Deterministic** |
| GUI UIA for ProjectEditor verification | Optional smoke test; primary = API verifier | **Deterministic** (optional **Human** spot-check) |
| Retry loops when Modbus/PLC offline | Adapter retry policy with explicit limits | **Deterministic** |
| Credential handling in scripts/logs | Secret store / env only; log redaction | **Deterministic** + **Human** (rotation) |

**Summary:** ~85% of POC "agent work" was **exploration and glue**. Production replaces exploration with **canonical model + validators + generators**. LLM belongs **only upstream of the canonical model**, never in PLC code generation or runtime orchestration.

---

## 3. Production blockers

Must resolve or explicitly accept before product implementation:

| ID | Blocker | Status | Impact |
|---|---|---|---|
| B1 | **No canonical model schema** — same signals declared 4–5 times in POC | UNKNOWN | Cannot build unified generators |
| B2 | **CODESYS gateway/active path not scriptable** (SP22) | BLOCKED | Full unattended deploy impossible |
| B3 | **SoftPLC service requires elevation** | BLOCKED | CI/local automation fragile |
| B4 | **Modbus I/O mapping depends on patched temp handler** | PROBABLE fix exists (SE script) but not clean-verified (Q3) | Fragile CODESYS adapter |
| B5 | **Single AHU only** — no multi-equipment generator proof | UNKNOWN | Product scope unvalidated |
| B6 | **MasterSCADA pinned to 1.2.18.32894 + internal test DLLs** | CONFIRMED risk | Upgrade breaks adapter silently |
| B7 | **Production runtime deployment unknown** (only debug EmulatorSession) | UNKNOWN | Cannot promise ops model |
| B8 | **Demo license limits unknown** | UNKNOWN | Runtime may stop in field |
| B9 | **REAL/32-bit mapping unproven** | FAILED (single word) | Analog strategy locked to INT scale until tested |
| B10 | **Alarms/trends/archives not tested via API** | UNKNOWN | Core BMS features missing |
| B11 | **HMI write proven for NumericUpDown only** | PARTIAL | General HMI generator unsafe |
| B12 | **No revision/regeneration/rollback strategy tested** | UNKNOWN | Engineering change workflow undefined |
| B13 | **Hardcoded credentials in POC scripts/logs** | CONFIRMED defect | Security debt if POC reused |
| B14 | **PD1–PD11 not user-approved** | PROPOSED | Architecture decisions not ratified |

**Acceptable deferrals (not blockers for Phase 0, blockers for GA):** FUXA, real AI extraction, multi-PLC, OPC UA, coils, online change.

---

## 4. Architecture risks

### Technical risks

| Risk | Severity | Basis |
|---|---|---|
| **Version coupling** — MasterSCADA internals, CODESYS SP22 API surface | High | CONFIRMED (`04` §10, `11` AF14) |
| **False success** — API returns OK but PLC unchanged (v2 HMI) | High | CONFIRMED (`08` F21, `11` AF6) |
| **Manual commissioning steps** break CI/CD | High | BLOCKED gateway + elevation |
| **Register map drift** across CODESYS / MS / HMI without single model | High | CONFIRMED (`11` AF1) |
| **INT scaling limits** — precision/range errors if REAL deferred too long | Medium | CONFIRMED INT works; REAL UNKNOWN |
| **HMI type mismatch** — LREAL control vs INT channel | Medium | CONFIRMED v3 workaround |
| **I/O mapping tooling loss** on mcptoolkit re-stage | Medium | CONFIRMED (`02` §7, `10` P6) |
| **Project file locking** — concurrent open corrupts state | Medium | CONFIRMED (`04`, `11` AF12) |
| **Coils/discrete false assumption** | Low–Medium | FAILED in POC |

### Product / operational risks

| Risk | Severity | Basis |
|---|---|---|
| **LLM hallucinated points/addresses** in model draft | High | No real AI test (`14`) |
| **Customer data in LLM prompts** (drawings, specs) | High | UNKNOWN policy |
| **Demo license in production** | High | UNKNOWN limits |
| **Single-vendor lock-in** (CODESYS + MasterSCADA) | Medium | CONFIRMED scope |
| **Engineer handover** — generated project GUI editability partially unknown | Medium | UNKNOWN property grid, v3 PE open |
| **Scaling to many AHUs / sites** — no performance test | Medium | UNKNOWN |
| **Security** — Modbus cleartext, localhost-only tested | Medium | CONFIRMED localhost |

### Process risks

| Risk | Severity | Basis |
|---|---|---|
| **POC demo logic mistaken for product control strategy** | High | Explicit in pack (`02` §5) |
| **Agent exploration patterns copied into product** | High | F28–F30, patched handlers |
| **Skipping validator** under schedule pressure | High | AF6 lesson |

---

## 5. Validation matrix

| Test ID | Risk | Test | Input | Expected result | Pass criteria | Failure decision | Status |
|---|---|---|---|---|---|---|---|
| V-001 | False success on generation | Fresh-process verifier after MasterSCADA build | Canonical model v0.1 (1 AHU) | fails=0; all settings/channels match spec | 100% check pass in new process | Block merge; fix generator | NOT RUN |
| V-002 | PLC not actually written | Modbus probe after HMI WriteData | HMI write FanCommand 1 then 2 | HR0=1→2, IR0=3→0 within 2 s | Register match + timing | Block HMI generator release | CONFIRMED (POC v3 only) |
| V-003 | Gateway not configured | CODESYS adapter preflight | Project without gateway path | Login fails with known error | Preflight detects before pipeline | Stop; surface runbook step | CONFIRMED (failure mode) |
| V-004 | Service not elevated | Start SoftPLC without admin | net start command | Access denied | Catch error 5; document elevation | Block unattended claim | CONFIRMED (BLOCKED) |
| V-005 | REAL mapping silent zero | Map REAL to single register | REAL process variable | Non-zero Modbus read | Non-zero or explicit fail | Keep INT shadow strategy | CONFIRMED FAIL |
| V-006 | Coil command no-op | Write coil with mapping | coil 0 = TRUE | PLC variable changes | Observable effect | Do not use coils for commands | CONFIRMED FAIL |
| V-007 | Address collision | Generate 2 equipment types | 2 AHUs in one model | Unique HR/IR ranges | Zero overlap in verifier | Fix allocator | NOT RUN |
| V-008 | Model drift | Single model → CODESYS + MS + HMI | One YAML/JSON file | Same point names/addresses everywhere | Cross-artifact diff = 0 | Block E2E | NOT RUN |
| V-009 | I/O map without patch | ScriptEngine-only map_io | Fresh project | 15/15 map + Modbus probe | All points reachable | Remove temp patch dependency | NOT RUN (Q3) |
| V-010 | HMI write generality | Button/CheckBox via server param | Extended HMI spec | WriteData + HR change | Same as NumericUpDown | Limit control palette | NOT RUN (Q4) |
| V-011 | Version upgrade break | Run verifier on new MS/CODESYS | Pin + candidate version | Same pass rate | ≥ baseline | Pin version; schedule adapter work | NOT RUN |
| V-012 | Production runtime | Deploy via mplc_service | Generated project | Stable 24 h + R/W | No demo stop | Document ops path | NOT RUN (Q7) |
| V-013 | License limit | Long-run runtime | Demo/prod license | No silent tag/runtime stop | Documented headroom | License procurement | UNKNOWN |
| V-014 | Regeneration idempotency | Run generator twice same model | Unchanged input | Byte-identical or semantically identical output | Deterministic diff | Fix generator | NOT RUN |
| V-015 | Regeneration with change | Add one point to model | v1 → v2 model | New channel only added; no orphan | Verifier + diff report | Manual migration rules | NOT RUN |
| V-016 | PLC behavioral test | Start/stop/setpoint sequence | HR0/HR1/HR2 writes | Documented IR transitions | Match template spec | Fix PLC template | CONFIRMED (POC AHU only) |
| V-017 | Alarm point | Create Event Alarm via API | Model with alarm | Alarm fires in runtime | Observable event | Defer alarm feature | NOT RUN |
| V-018 | Trend/archive | Create Data archive via API | Analog point | History queryable | Data persisted | Defer trend feature | NOT RUN |
| V-019 | Multi-PLC | 2 Modbus modules different IP | 2 SoftPLC instances | Independent R/W | Both pass probe | Architecture for N devices | NOT RUN |
| V-020 | LLM model draft | PDF → proposed JSON | Sample drawing | Valid against schema | Schema pass + human review | LLM cannot bypass validator | NOT RUN |
| V-021 | Secret leak | Scan logs/artifacts | Pipeline run | Zero credentials | grep clean | Block release | CONFIRMED FAIL (POC) |
| V-022 | Scale test | 50 equipment / 500 points | Large model | Generate+verify < TBD | No crash; verifier pass | Performance phase | NOT RUN |
| V-023 | Boot persistence | Restart SoftPLC service | Running PLC | App restarts RUN | State recovered | Runbook for download | NOT RUN |
| V-024 | Unit id mismatch | Modbus unit 0 vs 1 vs 7 | Same server | Consistent or explicit filter | Documented behavior | Explicit unit config | PROBABLE only |

---

## 6. Recommended Phase 0

Phase 0 goal: **prove what we can safely code** — not build the product.

### Priority order (S1–S9)

| Priority | ID | Test | Why first | Depends on | Status |
|---|---|---|---|---|---|
| **1** | **S1** | **Agentless Build** | Core product claim; exposes B2, B3, B4 immediately | Manual gateway once; elevation | PARTIAL — offline CONFIRMED; online BLOCKED |
| **2** | **S3** | **REAL / BOOL / Coil Mapping** | Locks fieldbus datatype strategy (INT vs REAL vs coils) | Running PLC | PARTIAL — INT CONFIRMED; REAL/coils FAILED |
| **3** | **S2** | **Multiple Equipment Types** | Single AHU is the largest generalization gap | Canonical model v0.1 draft | NOT RUN |
| **4** | **S7** | **PLC Behavioral Testing** | Separates template logic from demo sim; needs test harness | S1 PLC deploy | PARTIAL — POC AHU only |
| **5** | **S6** | **Revision / Regeneration** | Engineering change is daily work | S1 + S2 | NOT RUN |
| **6** | **S8** | **Version Compatibility** | Pin vs upgrade path before adapter investment | Vendor installs | NOT RUN |
| **7** | **S4** | **Scale Test** | De-risk allocator and host performance | S2 | NOT RUN |
| **8** | **S5** | **Alarm / Trend / Archive** | BMS completeness; can defer past first E2E | MS API research | NOT RUN |
| **9** | **S9** | **LLM Input → Canonical Model** | Product differentiator but highest risk; must not block deterministic core | Schema from Q19 | NOT RUN |

### Phase 0 deliverables (no product code)

1. **Canonical model schema v0.1** — minimum fields for CODESYS Modbus iface + MS channel + HMI point (addresses generated, not hand-entered).
2. **Schema validator** (standalone) — JSON Schema / custom rules; no generators yet.
3. **Test harness scripts** — Modbus probe + fresh-process verify pattern extracted from POC.
4. **Commissioning runbook draft** — gateway, elevation, license, copy-isolation.
5. **Phase 0 test report** — S1–S9 results filling §5 matrix.

### S1 Agentless Build — detailed acceptance

| Step | Agentless? | POC status |
|---|---|---|
| Generate ST/POU from model | Yes (deterministic) | CONFIRMED |
| CODESYS build headless | Yes | CONFIRMED |
| Modbus device add + map | Yes (fragile) | CONFIRMED |
| Gateway configure | **No** | BLOCKED |
| SoftPLC start | **No** (elevation) | BLOCKED |
| Download/start | Yes via mcptoolkit **after** manual steps | CONFIRMED |
| MasterSCADA build/verify | Yes | CONFIRMED |
| MasterSCADA runtime test | Yes (debug session) | CONFIRMED |
| HMI build/verify/runtime | Yes | CONFIRMED |

**S1 pass criteria for Phase 0:** Single command runs **build + verify** for CODESYS artifact + MasterSCADA artifact from one model file, with **explicit preflight failure** when gateway/elevation missing — not silent agent retry.

---

## 7. GO / NO-GO criteria

### GO — start **implementation** (canonical model + adapters + generators) when ALL of:

| # | Criterion | Rationale |
|---|---|---|
| G1 | **Canonical model schema v0.1 approved** (human sign-off) | AF1 foundation |
| G2 | **S1 passed** for offline build + verify from one model (CODESYS + MS artifacts) | Proves deterministic core |
| G3 | **S3 passed** for INT16 + bit commands; REAL/coils either **proven** or **explicitly rejected** in schema | Datatype strategy locked |
| G4 | **Q3 resolved** — I/O mapping works without `%TEMP%` patch | CODESYS adapter not fragile |
| G5 | **V-008 passed** — zero cross-artifact address/name drift | Single source of truth works |
| G6 | **PD1–PD8 ratified** by product owner (`13`) | Decisions not just proposed |
| G7 | **Commissioning runbook accepted** for gateway + elevation (or Q1/Q2 resolved) | Ops reality documented |
| G8 | **POC credentials rotated / sanitized** if POC repo shared | Security |

### NO-GO — do **not** start implementation if:

| # | Condition |
|---|---|
| N1 | Team plans to **copy POC scripts** as production base (`10` §B, `09` Replace) |
| N2 | **LLM generates PLC logic** directly (`13` PD7 violation) |
| N3 | **Cursor/agent required at runtime** for build/deploy (`13` PD8) |
| N4 | **S1 agentless offline build** cannot be demonstrated from one model |
| N5 | **HMI generator** targets v1/v2 direct Output write patterns |
| N6 | **No validator** in pipeline (AF6) |

### GO — start **LLM-assisted model drafting** only when:

- Schema validator exists (G1).
- Human approval workflow defined.
- LLM output **cannot** bypass validator (PD7).

### Explicitly NOT required for first GO

- Alarms/trends (S5).
- Multi-site scale (S4).
- Production MasterSCADA service deploy (S8 subset).
- FUXA / bms_web as product UI.

---

## 8. Recommended architecture

```
AI / LLM (optional, upstream only)
      ↓  proposed model draft
Canonical Engineering Model  ← single source of truth, versioned
      ↓
Validator  ← schema + engineering rules + cross-reference checks
      ↓
Deterministic Generators  ← no free-form code generation
      ↓
Adapters  ← vendor-specific IO, isolated processes
      ↓
CODESYS / Modbus / MasterSCADA / HMI artifacts
      ↓
Independent Verification  ← fresh-process verify + Modbus probe + behavioral tests
```

### Component rationale

| Component | Why it exists | POC evidence |
|---|---|---|
| **AI / LLM** | Accelerate model creation from documents; **never** deploy PLC logic | Fixture only; PD7 |
| **Canonical Engineering Model** | Eliminate 4–5 duplicate specs; addresses are generated | AF1 CONFIRMED problem |
| **Validator** | Catch errors before vendor tools; block LLM hallucination | v2 false success; AF6 |
| **Deterministic Generators** | Repeatable, auditable artifacts; paired with verifiers | `generate_st.py`, 76/76 HMI checks |
| **Adapters** | Hide CODESYS ScriptEngine, mcptoolkit, .NET reflection, version pins | AF3, AF4 |
| **CODESYS artifact** | PLC logic + **Modbus interface POU** (INT shadows, bit commands) | AF9 CONFIRMED |
| **Modbus mapping** | Generated from model; direction semantics fixed | K4, K5 |
| **MasterSCADA artifact** | Project + channels + parameters + HMI | K10–K19 |
| **HMI artifact** | v3 write path baked into generator rules | K17 CONFIRMED |
| **Independent Verification** | Truth = PLC registers + fresh-process read-back, not API OK | AF6 CONFIRMED |

### Adapter boundaries

| Adapter | Owns | Does NOT own |
|---|---|---|
| **CODESYS adapter** | Project/device tree, POU text injection, I/O mapping, build, download/start, online R/W | Control strategy semantics (comes from certified templates); gateway configuration |
| **Modbus spec generator** | HR/IR allocation, scaling, bit packing, collision detection | PLC internal variables beyond interface POU |
| **MasterSCADA adapter** | x64 .NET host, bootstrap, AddItem tree, settings, save/verify, runtime test hook | SCADA runtime production deployment (ops) |
| **HMI generator** | Windows, controls, links, server parameters, layout templates | Custom web UI (bms_web is separate experiment) |
| **Verification harness** | Probes, diff, reports | Fixing failed builds |

### Control logic separation (AF10)

```
[Certified control template]  ← equipment-type specific, human-reviewed
[Modbus interface POU]        ← generated, INT shadows, commands — AF9
[Plant simulator POU]         ← optional, test/commissioning only — NOT production control
```

---

## 9. What NOT to build yet

| Feature | Reason |
|---|---|
| Full AI agent orchestrating build/deploy | AF7, PD8 — POC used scripts, not Cursor |
| Free-form LLM PLC code generation | AF8 — all working PLC was templated |
| Copying `%TEMP%` patched mcptoolkit handlers | P6 — fragile |
| bms_web as primary operator UI | POC experiment; MasterSCADA HMI path proven |
| FUXA integration | PROBABLE only; write unproven |
| Coils/discrete until re-tested | FAILED |
| REAL Modbus until word-order proven | FAILED single-word |
| Alarms/trends/archives | UNKNOWN API behavior |
| Multi-PLC / multi-site orchestration | UNKNOWN |
| Production `mplc_service` deployment automation | UNKNOWN |
| Online change / hot-fix PLC | UNKNOWN |
| Full equipment library (chiller, boiler, VAV…) | S2 not passed |
| Customer-facing SaaS / multi-tenant | Out of POC scope |
| Rollback / blue-green deploy | S6 not passed |
| GUI automation (UIA) as primary verify | Unreliable; API verifier preferred |
| Agent recovery tooling (sanitize.py, encoding fixes) | Environment artifact |
| Register map constants in product (`HR0=FanCommand`) | P1 POC-only |

---

## 10. Next exact step

**Define and review Canonical Engineering Model schema v0.1** — nothing else.

Concrete actions:

1. Consolidate fields from `demo/model/ahu01.json`, `hmi_api_poc/specs/ahu_01_test_v3.json`, `bms_web/config/ahu.json`, and `docs/modbus_mapping.md` into **one draft schema**.
2. Mark each field **CONFIRMED required** vs **PROBABLE** vs **defer**.
3. Add validator rules: generated addresses only, no manual HR/IR input, datatype enum (INT16-scaled default), direction enum, HMI binding type (read / write-v3).
4. **Human review** of draft schema — no generator, no adapter, no UI code.

This is the minimum prerequisite for S2, S6, S9, and G1.

---

## Appendix A — POC failed experiments → permanent rules

From `08_FAILED_EXPERIMENTS.md` (30 entries):

| Rule | Source |
|---|---|
| Never headless ScriptEngine `online.login()` without gateway + dialog guard | F1 |
| Never MCP login before gateway configured | F2 |
| Never assume non-elevated SoftPLC start works | F3 |
| Always add CODESYS devices by explicit type/id/version | F4 |
| Always `device.update` after Standard template | F5 |
| Never map REAL directly to 16-bit register word | F6 |
| Do not use coils for commands until explicitly mapped and tested | F7 |
| Follow mcptoolkit schemas (`confirm:true`, login modes, object-shaped writes) | F8 |
| Set `CODESYS_EXE` + `CODESYS_PROFILE` if APInstaller times out | F9 |
| pymodbus: keyword args, `device_id=` | F10 |
| MasterSCADA: full bootstrap + IUIService always | F11, F12 |
| Never `InsertFromList` headless | F13 |
| Runtime write: child `Value` or `(Value:=n)` struct literal | F14 |
| Always `SaveProject` before `Dispose` on new projects | F15 |
| MasterSCADA host: `SetDllDirectory` + cwd = bin | F16 |
| No COM / ProjectEditor CLI / MasterPLCAPI for project gen | F17 |
| HMI: no bidirectional link to Modbus Output (v1) | F20 |
| HMI: no direct LREAL control → INT Output (v2) | F21 |
| HMI write: server parameter + pin-side SetLink only (v3) | F21, F24 |
| Do not change channel ValueType to double to fix HMI | F23 |
| fcgi port conflicts: use `/ea:N` | F26 |
| Do not copy agent shell one-liner file edits | F28 |
| Verify file encoding after agent writes | F29 |

---

## Appendix B — Topic evaluation (requested checklist)

| Topic | Assessment | Status |
|---|---|---|
| Agentless build | Offline yes; full deploy no (gateway, elevation) | PARTIAL |
| Deterministic generation | ST + MS + HMI builders proven separately | CONFIRMED (per-artifact) |
| Repeatability | Verifiers 76/76, 15/15, fails=0 | CONFIRMED (same spec) |
| Canonical model | Not implemented | NOT DONE |
| Schema validation | Not implemented | NOT DONE |
| Modbus datatype handling | INT16 scaled proven | CONFIRMED |
| REAL / 32-bit values | Single-word FAILED; 2-word UNKNOWN | FAILED / UNKNOWN |
| BOOL / coil handling | Coil write no effect | FAILED |
| Address collision | Single AHU only | UNKNOWN |
| Multiple equipment types | Not tested | UNKNOWN |
| PLC behavioral testing | AHU V2 sequence manually observed | CONFIRMED (n=1) |
| Alarm handling | Bits in IR5 only; no MS alarm API test | PARTIAL POC / UNKNOWN MS |
| Trend/history | Not tested | UNKNOWN |
| Revision/regeneration | Not tested | UNKNOWN |
| Rollback | Not tested | UNKNOWN |
| Project isolation | Work-on-copies rule proven | CONFIRMED |
| Scaling | Not tested | UNKNOWN |
| CODESYS version dependency | SP22 Patch 3 only | CONFIRMED pin |
| MasterSCADA version/API dependency | 1.2.18.32894 + test DLLs | CONFIRMED pin |
| License/runtime dependency | Demo mode; limits unknown | UNKNOWN |
| Security/secrets | Env vars work; hardcoded in POC | CONFIRMED defect |
| Customer data/privacy | Not addressed | UNKNOWN |
| LLM reliability | Not tested (fixture only) | NOT DONE |
| Human approval | Implicit in POC; not formalized | PROPOSED |

---

## Appendix C — Minimum canonical model structure (PROPOSED, not implemented)

Based on cross-pack consolidation — **requires human approval (G1)**:

```yaml
# Illustrative — NOT a implemented schema
model_version: "0.1"
project:
  name: string
  target_codesys: { version: "3.5.22.30", device_id: "0000 0004" }
  target_masterscada: { version: "1.2.18.32894" }

equipment[]:
  id: string
  type: enum [AHU, ...]           # S2 expands
  controller_ref: string

points[]:
  id: string
  equipment_id: string
  semantic_role: string            # e.g. FanCommand, SupplyTemp
  direction: enum [command, setpoint, status, measurement, alarm]
  datatype: enum [INT16, BOOL, REAL, BITFIELD]
  scaling: { factor: number, offset: number } | null
  modbus: GENERATED                # allocator output, not hand input
  masterscada:
    access: enum [Input, Output]
    param_type: enum [holding, input_register]
  hmi:
    widget: enum [NumericUpDown, TextOutput, Button, ...]
    writable: bool
    write_pattern: enum [direct_read, server_parameter_v3]  # v3 required if writable
  alarms[]: optional              # defer until S5

validation_rules:
  - no_manual_modbus_address
  - writable_hmi_must_use_server_parameter_v3
  - REAL_must_have_two_word_mapping_or_forbidden
  - unique_point_id
  - unique_generated_address
```

---

*This document is the gate before implementation. Update status columns in §5 as Phase 0 tests execute.*
