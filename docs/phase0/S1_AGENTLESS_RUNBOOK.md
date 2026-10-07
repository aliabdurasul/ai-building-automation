# S1 — Agentless Reproduction Runbook

Bu runbook, AI-BMS POC AHU zincirinin **ajan, MCP ve LLM olmadan**, sadece mevcut POC scriptleri ile yeniden üretilip üretilemediğini test eder. Operatörün Cursor/Claude'u veya POC geçmişini bilmesi gerekmez.

## 0. Kurallar (operatör için)

1. Hiçbir POC scriptini **düzenleme**. Tek izin verilen değişiklik: staging kopyalarında hardcoded kök yolun (`C:\AI_BMS_POC\...`) staging yoluyla **literal string değiştirilmesi**. Bunu harness otomatik yapar ve kaydeder.
2. MCP (`mcptoolkit-for-codesys`), `%TEMP%\mcptoolkit-for-codesys` içindeki dosyalar, Cursor/Claude/Cline, LLM API, browser veya GUI/koordinat otomasyonu **kullanılmaz**.
3. `C:\AI_BMS_POC\simple_ahu_demo\AI_BMS_SIMPLE_AHU.project` ve MasterSCADA kullanıcı projeleri **açılmaz**.
4. Bir adım başarısız olursa: **STOP → RECORD → REPORT**. Workaround uygulanmaz, script düzeltilmez.
5. Port 502'de bir PLC dinliyorsa ve bu PLC'ye generator çıktısı bu runbook ile indirilmediyse, o PLC **bilinmeyen kaynaklı** kabul edilir. Modbus probe adımı atlanır.

## 1. Ön koşullar

| Öğe | Değer |
|---|---|
| OS | Windows 10/11 x64, PowerShell 5.1 |
| CODESYS | 3.5.22.30 (`C:\Program Files (x86)\CODESYS 3.5.22.30\CODESYS\Common\CODESYS.exe`), profil `CODESYS V3.5 SP22 Patch 3` |
| MasterSCADA | 4D 1.2.18.32894, `C:\Program Files\MPSSoft\MasterSCADA 4D 1.2` |
| Python | 3.11 + `pymodbus` 3.x (`python` PATH'te) |
| POC | `C:\AI_BMS_POC\` (salt okunur kullanılır) |
| Harness | `<repo>\phase0\s1\harness\run_s1.ps1` |
| Açık olmaması gerekenler | CODESYS IDE, MasterSCADA ProjectEditor, IWIN32/mplc |

Staging yolları (harness oluşturur, önceden **var olmamalı**):

| Amaç | Yol | Neden |
|---|---|---|
| CODESYS staging | `C:\AI_BMS_PHASE0\s1\<run>\codesys` | POC demo scriptleri kök yolu hardcode ediyor; kopyalar buraya taşınır |
| MasterSCADA staging | `C:\AI_BMS_POC\master_scada_research\hmi_api_poc\phase0_s1\<run>` | `AiBmsHmiPoc.exe` bu sandbox dışındaki konumları reddediyor (`REFUSE: outside sandbox`). Mevcut dosyalara dokunulmaz; yeni alt klasör oluşturulur |
| Evidence | `<repo>\docs\phase0\evidence\<run>` | stdout/stderr, loglar, harness JSON |

## 2. Çalıştırma

```powershell
cd "<repo>"
powershell -ExecutionPolicy Bypass -File phase0\s1\harness\run_s1.ps1 -Run run1
# RUN 1 tamamlandıktan sonra, ikinci temiz koşu:
powershell -ExecutionPolicy Bypass -File phase0\s1\harness\run_s1.ps1 -Run run2
```

Harness her adım için `timestamp`, `command`, `exit_code`, `duration`, `timed_out`, stdout/stderr dosyası ve oluşturulan/değiştirilen dosyaları `docs\phase0\evidence\<run>\harness_<run>.json` içine yazar. **PASS/FAIL kararı vermez**; karar, aşağıdaki "Expected result" ve "Failure condition" sütunlarına göre evidence'dan verilir.

## 3. Adımlar

| STEP | PURPOSE | COMMAND (harness içinde) | EXPECTED RESULT | FAILURE CONDITION | OUTPUT |
|---|---|---|---|---|---|
| S00 | Preflight | Port 502, IDE/IWIN32 prosesleri, SoftPLC servis durumu, elevation | Kayıt alınır | Staging klasörü zaten varsa harness durur | `harness_<run>.json` |
| S01 | Temiz staging + path relocation | POC dosyalarını kopyala; `C:\AI_BMS_POC\demo`, `...\simple_ahu_demo\AI_BMS_SIMPLE_AHU.project`, `...\simple_ahu_demo\logs` stringlerini staging yollarıyla değiştir | Her kopya için kaynak/hedef SHA256 ve substitution listesi | Substitution dışında içerik farkı | `harness_<run>.json` (S01) |
| S02 | Deterministik ST üretimi | `python <stage>\codesys\generator\generate_st.py` | exit 0; `generated\PLC_PRG_decl.st`, `PLC_PRG_impl.st`, `PLC_PRG.st` | exit ≠ 0 veya dosya yok | `S02_generate_st.stdout.txt`, `generated\*.st` |
| S03 | CODESYS proje + build | `CODESYS.exe --culture=en --profile="CODESYS V3.5 SP22 Patch 3" --noUI --runscript=<stage>\codesys\scripts\codesys_generate_ahu.py` (timeout 300 s) | exit 0; `logs\generate_result.txt` içinde `build_error_count=0`, `STATUS=OK` → **BUILD PASS** | exit ≠ 0, timeout, `build_error_count>0` → **BUILD FAIL** | `logs\generate_result.txt`, `AI_BMS_AHU_DEMO.project` |
| S04 | Reopen + sembol kontrolü | aynı CODESYS komutu, `codesys_verify.py` (timeout 180 s) | exit 0; `STATUS=OK all required symbols present` | exit ≠ 0, `MISSING:` | `logs\verify_result.txt` |
| S05 | Temiz Modbus I/O mapping (MCP'siz, yamasız) | aynı CODESYS komutu, `codesys_map_modbus_io.py` (timeout 300 s) | `logs\modbus_io_map.json` içinde `map_results` ok | `"error": "Modbus_TCP_Server not found"` veya mapping 0 → **Clean mapping FAIL** | `logs\modbus_io_map.json` |
| S06 | Online login / download denemesi | aynı CODESYS komutu, `codesys_runtime.py` (timeout 150 s) | `logs\runtime_result.txt` içinde `STATUS=OK simulation login+read` | timeout (hang), `STATUS=PARTIAL ... online_blocked`, `STATUS=FAIL` → **PLC download FAIL/BLOCKED** | `logs\runtime_result.txt`, `generated\AI_BMS_AHU_DEMO.app` |
| S07 | SoftPLC servis başlatma (elevated değil) | `Start-Service "CODESYS Control Win V3 - x64"` | Servis Running, 502 dinliyor | Access denied → **BLOCKED (manuel/elevated ön koşul)** | `harness_<run>.json` (S07) |
| S08 | Dış Modbus doğrulama | `python <stage>\codesys\scripts\modbus_v2_probe.py` (502 boşsa) | `logs\modbus_v2_probe.json` içinde `connect=true`, `start_ir0_running=true`, `stop_clears=true` | `connect=false` veya testler false | `logs\modbus_v2_probe.json` |
| S09 | MasterSCADA proje oluşturma | `AiBmsHmiPoc.exe create <ms_stage>\projects AHU_S1 <log>` (cwd = sandbox) | exit 0; `CreateProject OK`, `SaveProject OK`; `.fdb` + `info.xml` | exit ≠ 0, `REFUSE`, exception | `S09_ms_create.log` |
| S10 | Workstation + Modbus TCP modül + kanallar | `AiBmsHmiPoc.exe modbus <ms_stage>\projects AHU_S1 <log>` | exit 0; IP 127.0.0.1 / port 502 / unit 1; FanCommand (HR0, Output, INT16), FanStatus (IR0, Input, INT16); `SaveProject OK` | exit ≠ 0 | `S10_ms_modbus.log` |
| S11 | Fresh-process Modbus verify | `AiBmsHmiPoc.exe verify <ms_stage>\projects AHU_S1 <log>` | exit 0; `fails=0` | exit ≠ 0 veya `fails>0` | `S11_ms_verify.log` |
| S12 | HMI üretimi | `AiBmsHmiPoc.exe hmibuild <ms_stage>\projects AHU_S1 <ms_stage>\ahu_01_test_v3.json <log>` | exit 0; pencere, kontroller, parametre, linkler, save | exit ≠ 0 | `S12_hmi_build.log` |
| S13 | HMI persistence verify | `AiBmsHmiPoc.exe hmiverify <...> <evidence.json> <log>` | exit 0; tüm kontroller PASS (POC'de 76/76) | exit ≠ 0 veya fail > 0 | `S13_hmi_verify_evidence.json` |
| S14 | Runtime için byte kopya | `Copy-Item projects\AHU_S1 rt_copy\AHU_S1 -Recurse` | kopya mevcut | — | — |
| S15 | MasterSCADA runtime (debug EmulatorSession) | `AiBmsHmiPoc.exe runtime <ms_stage>\rt_copy AHU_S1 <events.jsonl> <log>` (timeout 480 s) | `wait_config_loaded=true`; `summary read_ok=true write_ok=true` (PLC 502'de çalışıyorsa) | config yüklenmez; PLC yoksa read/write doğrulanamaz → **MasterSCADA runtime read/write FAIL/BLOCKED** | `S15_ms_runtime_events.jsonl` |
| S16 | HMI runtime (HTML5 üretimi) | `AiBmsHmiPoc.exe hmiruntime <ms_stage>\rt_copy_hmi AHU_S1 20 7 <events.jsonl> <log>` | `wait_config_loaded=true`; `htdocs_found` (index.html) | config yüklenmez / htdocs yok | `S16_hmi_runtime_events.jsonl`, `rt_copy_hmi\AHU_S1\..\rt_work\Debug_1\htdocs` |
| S17 | Son durum | 502, kalan IWIN32/CODESYS prosesleri, servis | Kalan proses yok | Proses kaldıysa kayıt | `harness_<run>.json` |

## 4. Bu runbook'ta bulunmayan adımlar (ve nedeni)

| Adım | Neden yok |
|---|---|
| CODESYS projesine Ethernet + ModbusTCP Server Device ekleme | POC'de sadece MCP scriptleri (`run_mcp_modbus_runtime.py` vb.) yapıyor. Ajansız eşdeğer script yok. |
| Gerçek SoftPLC'ye login/download/start | POC'de sadece MCP (`run_ahu_v2_start.py`, `run_ahu_v2_deploy.py`). Ayrıca gateway active path IDE'de elle ayarlanmalı. |
| HMI üzerinden yazma (web kontrolüne tıklama) | POC'de ajan browser DOM tıklamasıyla yapıldı. Script yok. |
| nginx ile HMI'yı servis etme | POC'de elle başlatıldı (`nginx -p .\` + sandbox conf). `hmiruntime` nginx başlatmıyor. |

Bu adımlar runbook'a eklenirse yeni kod veya ajan davranışı gerekir; S1 kapsamında yasaktır.

## 5. Determinism karşılaştırması

İki koşu bittikten sonra:

```powershell
python phase0\s1\harness\compare_s1.py
```

Çıktı: `docs\phase0\S1_comparison.json`. Timestamp, GUID, PID, port ve run-özgü yollar normalize edilir; kalan farklar raporlanır.

## 6. Temizlik

- IWIN32 veya CODESYS prosesi kaldıysa: `Get-Process IWIN32,CODESYS | Stop-Process` (sadece bu testin başlattıkları).
- Staging klasörleri evidence olarak **silinmez**.
