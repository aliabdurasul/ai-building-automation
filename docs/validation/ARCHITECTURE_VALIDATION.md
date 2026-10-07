# AI-BMS — Architecture Validation (Phase 0 öncesi)

| Alan | Değer |
|---|---|
| Tarih | 2026-10-05 |
| Kaynak | `C:\AI_BMS_POC\simple_ahu_demo\docs\` Knowledge Pack (00–14, KNOWLEDGE_PACK_INDEX, architecture, hmi_tags, modbus_mapping, plc_model, research/masterscada4d_automation_research) — snapshot 2026-10-03 |
| Yöntem | Tüm dosyalar okundu ve birbirleriyle çapraz kontrol edildi. Ham log/evidence dosyaları **bu çalışmada yeniden açılmadı**; Knowledge Pack'in kendi iddiaları değerlendirildi. |
| Amaç | "Kod yazmak" değil, **neyi güvenle kodlayabileceğimizi kanıtlamak**. |
| Kapsam dışı | Implementation. Bu rapor bitince implementation başlatılmayacak. |

## 0. Okuma kuralları

Durum etiketleri (Knowledge Pack `00_PROJECT_CONTEXT.md` tanımı, bu raporda daha sıkı uygulandı):

| Etiket | Bu rapordaki anlamı |
|---|---|
| `CONFIRMED` | Knowledge Pack'te somut evidence yolu gösterilen, çalıştırılmış test. **Tek örnek (1 AHU, tek makine, localhost) üzerinde.** Genelleme içermez. |
| `PROBABLE` | Dolaylı kanıt, kısmi çalıştırma, veya kanıt var ama yorum/genelleme şüpheli. Tekrar doğrulanmalı. |
| `UNKNOWN` | Test edilmemiş. |
| `FAILED` | Denenmiş, kök nedeni anlaşılmış şekilde çalışmamış. |
| `BLOCKED` | Mevcut araç/yetki ile manuel veya harici adım olmadan yapılamıyor. |
| `DEPRECATED` | Daha iyi bir sonuçla geçersiz kalmış; kullanılmayacak. |

Önemli ilke: **POC'de "çalıştı" ≠ ürün için "kanıtlandı".** Her POC sonucu tek bir örnek, tek bir makine, ajan gözetiminde tek (çoğu zaman) koşu üzerindedir.

---

## 1. Current proven system

### 1.1 POC'nin gerçekten kanıtladığı şey (tek cümle)

> CODESYS 3.5.22.30 / MasterSCADA 4D 1.2.18.32894 kurulu **tek bir Windows makinesinde, localhost üzerinde**, zinciri oluşturan **her bir bağlantının ayrı ayrı** GUI'de elle mühendislik yapmadan (script/API ile) kurulabildiği ve **INT16 tipinde 1 komut + 1 durum** değerinin CODESYS ↔ Modbus TCP ↔ MasterSCADA runtime ↔ üretilmiş MasterSCADA HMI arasında iki yönde taşınabildiği.

Kanıtlanmayan şey: Bu zincirin **tek bir girdiden, tek bir koşuda, ajan olmadan, tekrarlanabilir şekilde** üretilebildiği.

### 1.2 Link-by-link yeniden sınıflandırma

| # | Yetenek | Pack iddiası | Bu raporun değerlendirmesi | Gerekçe |
|---|---|---|---|---|
| L1 | CODESYS projesi headless create/build (ScriptEngine `--noUI`) | CONFIRMED | **CONFIRMED** | C1, C2, C3; exit code ile. |
| L2 | JSON model → deterministik ST üretimi → build 0 error | CONFIRMED | **CONFIRMED (build seviyesinde)** | C3. **Fakat bu üretilmiş kod PLC'ye hiç indirilmedi/çalıştırılmadı** (C5: "not executed on PLC"). |
| L3 | Canlı PLC'de çalışan V2 programı | CONFIRMED | **CONFIRMED, ama generator çıktısı değil** | `_plc_decl.txt` / `_plc_impl.txt` elle/ajan tarafından yazıldı, `pou.set_text` ile yüklendi. |
| L4 | Ethernet + ModbusTCP Server Device ekleme (explicit id) | CONFIRMED | **CONFIRMED** | C13, C14. |
| L5 | Modbus I/O mapping 15/15 | CONFIRMED (fragile) | **PROBABLE (reproducible yol için)** | C15 kanıtı `%TEMP%` altındaki **yamalı** mcptoolkit handler ile alındı. Saf ScriptEngine yolu Q3'te hâlâ açık soru. |
| L6 | Online login/download/start/read/write | CONFIRMED | **CONFIRMED, manuel ön koşulla** | Gateway active path IDE'de elle (BLOCKED), servis start elevation ister (BLOCKED). Sadece mcptoolkit ile; ScriptEngine login FAILED. |
| L7 | pymodbus ile HR/IR okuma-yazma (V2 probe) | CONFIRMED | **CONFIRMED** | M5. |
| L8 | MasterSCADA proje create/save, Modbus modül + kanal, fresh-process verify | CONFIRMED | **CONFIRMED** | S5, S8, S9, S14. **Sadece 2 kanal** (FanCommand HR0, FanStatus IR0), INT16. |
| L9 | MasterSCADA headless runtime ↔ CODESYS read/write | CONFIRMED | **CONFIRMED (debug EmulatorSession)** | S16. Üretim runtime'ı (`mplc_service`) UNKNOWN. |
| L10 | MasterSCADA HMI üretimi + persist (76/76) | CONFIRMED | **CONFIRMED** | H9, H10. 1 pencere, 2 aktif kontrol. |
| L11 | HMI okuma (CODESYS → HMI) | CONFIRMED | **CONFIRMED** | H4, H11. |
| L12 | HMI yazma (HMI → CODESYS HR0) | CONFIRMED (v3) | **CONFIRMED, dar kapsam** | H11. Tek kontrol tipi (NumericUpDown), tek değer çifti (1/2), LREAL→INT dönüşümüne örtük güven. Kesirli/aralık dışı değer davranışı UNKNOWN. |
| L13 | Tüm zincir tek canonical modelden | NOT IMPLEMENTED | **UNKNOWN** | Yok. Sinyaller 4-5 ayrı spec'te elle tekrar tanımlandı (AF1). |
| L14 | AI ile doküman/çizim analizi | NOT IMPLEMENTED | **UNKNOWN** | `bms_web` engineering engine bir fixture. |
| L15 | FUXA HMI | PROBABLE | **DEPRECATED (ürün için)** | Yan deney, UI write kanıtsız; ürün hedefi değil. |
| L16 | Zincirin tek koşuda uçtan uca çalışması | (örtük CONFIRMED) | **UNKNOWN** | Bağlantılar farklı projelerde/oturumlarda ispatlandı: CODESYS (simple_ahu_demo), MS Modbus (api_poc / runtime_integration_test), HMI (hmi_api_poc, ayrı builder). |

### 1.3 Gerçekten kalıcı (ürüne taşınabilir) teknik bilgi

Aşağıdakiler **bilgi** olarak güvenilir; **kod** olarak değil:

- CODESYS ScriptEngine çağrı kalıbı + exit code + watchdog (K1, K2).
- Cihazların explicit type/id/version ile eklenmesi (K3).
- Modbus yön semantiği: Holding Register = PLC input (`%IW`), Input Register = PLC output (`%QW`) (K5).
- Scaled-INT16 shadow değişken katmanı; bit-packed, edge-triggered komut kelimesi (K6, K7).
- MasterSCADA x64 .NET 4.x host bootstrap, `IUIService` zorunluluğu, save-before-dispose (K10, K11).
- MasterSCADA setting ID'leri ve enum değerleri (K13).
- HMI yazma mimarisi: control → typed server parameter → `SetLink` → channel Output (K17).
- Fresh-process verifier kalıbı; "API ack ≠ applied" dersi (K14, AF6).

### 1.4 Dosyalar arası çelişkiler ve tutarsızlıklar

| ID | Çelişki | Dosyalar | Sonuç |
|---|---|---|---|
| X-01 | "Full chain proven" iddiası, ama bağlantılar ayrı projelerde/oturumlarda kanıtlanmış; tek koşu yok. | INDEX §3, 01 vs 00 tablo, 04, 05, 09 | Zincir **bağlantı bazında** CONFIRMED, **bütün olarak** UNKNOWN. |
| X-02 | Deterministik generator "kanıtlandı" algısı; canlı PLC'de çalışan kod ise generator çıktısı değil (elle/ajan yazımı V2). Generator çıktısı hiç indirilmedi. | INDEX §8, AF2, 02 §6 vs 02 §5, 09, C5 | "Generator → çalışan PLC" yolu **UNKNOWN**. |
| X-03 | AF2: builders "identical verifiable results" üretti. Kanıt: verify sayıları (71/72/76). Aynı girdiyle iki koşu + diff yok. | 11 AF2 vs 07 | Determinizm/tekrarlanabilirlik **UNKNOWN**. Ayrıca `.fdb` için byte-stable çıktı muhtemelen imkânsız (DB, GUID, timestamp) — semantik eşitlik gerekir. |
| X-04 | I/O mapping K4 "CONFIRMED" ve 01 #5 "CONFIRMED", ama Q3 saf ScriptEngine mapping'in temiz projede çalışıp çalışmadığını açık soru olarak tutuyor. Kanıt yamalı `%TEMP%` handler'dan. | 10 K4, 01 #5 vs 12 Q3, 02 §7.3, 09 | Algoritma bilgisi CONFIRMED; **ajansız, yamasız mapping PROBABLE**. |
| X-05 | Coil: 03 "mapped but writes had no effect → FAILED"; 08 F7 kök neden UNKNOWN, "o sırada mapping/area size 0 olması PROBABLE"; 03 §1 area size Coils 16 diyor. | 03 §1-2 vs 08 F7 | Test **sonuçsuz**. Coil için doğru etiket **UNKNOWN**, FAILED değil. |
| X-06 | "REAL-on-register FAILED" genel bir kural gibi sunuluyor; test aslında 32-bit REAL'i **tek 16-bit word'e** map etmiş — bu beklenen bir hata. 2-word REAL hiç denenmedi. | INDEX §4, 03 §3 vs 08 F6 | "REAL tek word'e FAILED" CONFIRMED; **"REAL Modbus üzerinden" UNKNOWN**. |
| X-07 | Güvenlik kısıtı "sadece FanCommand 1/2 yazıldı" (00, D14); ama `bms_web` connect anında HR4=1, HR3=1, HR1=70, HR2=220 seed ediyor; M5/M6 setpoint (FanSpd 40) yazdı. | 00, 13 D14 vs 06 §4, plc_model, 03 §4 | Kısıt POC içinde **ihlal edilmiş**. Ayrıca "HMI bağlanınca PLC'ye yazma" ürüne taşınmaması gereken tehlikeli bir davranış. |
| X-08 | Durum sözlüğü tutarsız: `NOT DONE`, `NOT IMPLEMENTED`, `CONFIRMED_STATIC`, `FAILED->fixed`, `CONFIRMED (fixture only)`, `CONFIRMED (tool)`, `CONFIRMED (fragile tooling)`. HMI v1/v2 "BLOCKED" etiketli ama tanıma göre FAILED + DEPRECATED. | 00 vs 01, 05, 07, 14 | HMI v1/v2 → **FAILED / DEPRECATED** (v3 ile geçersiz). |
| X-09 | HMI E2E testinde PLC'nin hangi uygulamayı çalıştırdığı belgelenmemiş: 06 "HMI testleri sırasında bir kullanıcı AHU runtime'ı çalışıyordu", H11 deps "user PLC running". HR0=1 → IR0=3 davranışı V1 veya V2 ile uyumlu. | 06 §1, 07 H11 | HMI E2E sonucu CONFIRMED, ama **test ortamı provenance'ı PROBABLE**. Independent verification ihtiyacının örneği. |
| X-10 | FanSpdSet aralığı: PLC validasyonu 1..100 (02 §5), mapping dokümanları 0..100 (03 §4, modbus_mapping). | 02 vs 03, modbus_mapping | Tek kaynak yok — tam da canonical model gerekçesi. |
| X-11 | Demo license: 01 "BLOCKED" listesinde, 14 "UNKNOWN". | 01 §manual vs 14 | Doğru etiket **UNKNOWN** (limitler bilinmiyor). |
| X-12 | "API output == GUI output structure" (04 §8) bir verifier ile, fails=2 "hardcoded beklenti" diye açıklanarak çıkarılmış. | 04 §8, S11 | **PROBABLE**. |
| X-13 | `research/masterscada4d_automation_research.md` (2026-10-02): headless StoreService UNKNOWN, enum sayıları UNKNOWN, "MasterSCADA servisi yok". 04 bunları geçersiz kılıyor. | research vs 04 | research verdict'leri **DEPRECATED**; envanter bilgisi geçerli. |
| X-14 | `architecture.md` "Upload → Analyze → Model → Generate → Run" sayfasını yetenek gibi gösteriyor; arkasında fixture var. | architecture.md vs 01 #18, M9 | Yanıltıcı; ürün kanıtı **değil**. |

---

## 2. Agent dependency analysis

POC'de Cursor/Cline/Claude ajanı sadece "script çalıştıran" değil, **mühendis, entegratör, hata ayıklayıcı ve test operatörü** rolünü üstlendi. Bu rollerin hiçbiri ürüne ajan olarak taşınmamalı.

Sütunlar: POC'de ajanın yaptığı → üretimdeki karşılığı → türü (D = deterministic kod, L = LLM, H = human).

| # | POC agent behavior | Production replacement | Tür |
|---|---|---|---|
| A1 | V2 PLC ST kodunu (sequence, ramp, thermal model) yazdı ve `pou.set_text` ile yükledi | Mühendis tarafından yazılmış, review edilmiş, versiyonlu **template library** + deterministik generator. Kontrol mantığı ile plant simülasyonu ayrı. | H (template yazımı) + D (üretim) |
| A2 | Register haritasını seçti (HR0..HR4, IR0..IR6) | Canonical model'den **deterministik address allocator**; tahsis kalıcı bir lock dosyasında saklanır (revizyonda adresler kaymaz). | D |
| A3 | Aynı sinyalleri 4-5 farklı spec'te tekrar tanımladı | Tek canonical engineering model; diğer tüm artifact'ler türetilir. | D (+ H/L model yazımı) |
| A4 | Vendor API'lerini decompile, reflection, deneme-yanılma ile keşfetti | Geliştirme zamanı R&D; sonuç adapter koduna ve version gate'e gömülür. Runtime'da keşif yok. | H (dev time) |
| A5 | mcptoolkit çağrılarını farklı argüman şekilleriyle yeniden denedi (F8) | Tipli adapter API'si; girdi şemayla doğrulanır; "varyasyonla retry" yok. | D |
| A6 | Takılan CODESYS watcher'ı öldürüp yeniden başlattı, watchdog yönetti | Adapter supervisor: sabit timeout, sınırlı retry, tipli hata, temiz teardown. | D |
| A7 | mcptoolkit handler'ını `%TEMP%` içinde yamaladı (`map_io`) | Kendi ScriptEngine mapping operasyonu, versiyon kontrollü adapter içinde. | D |
| A8 | Port çakışmasında alternatif port seçti (`/ea:7` → 30757, nginx 8143) | Konfigürasyonda port ataması + preflight port kontrolü; çakışmada **dur ve raporla**, kendiliğinden port değiştirme yok. | D + H (config) |
| A9 | Kullanıcıya gateway path'i elle ayarlatıp, servisi elevated başlattırdı | Commissioning runbook + otomatik preflight kontrolleri (gateway set mi, servis çalışıyor mu). | H + D (check) |
| A10 | Hataları log okuyarak teşhis etti (type 5, `HasBackward`, ExpressionParserException) | Hata taksonomisi, yapılandırılmış log, "stop and report". LLM en fazla log özetleyen **danışman** olabilir, karar vermez. | D + H (L opsiyonel, advisory) |
| A11 | HMI yazma mimarisini v1 → v2 → v3 deneme-yanılma ile buldu | v3 kuralı generator'a sabit kural olarak gömülür. Yeni pattern'ler R&D'de bulunur, runtime'da değil. | D |
| A12 | HMI'ı shadow-DOM `#incr/#decr` tıklamalarıyla test etti | Otomatik HMI test harness'ı (WriteData protokolü veya script'li browser testi) + bağımsız Modbus read-back. | D |
| A13 | Hangi değerlerin "güvenli" yazılabileceğine karar verdi | Modelde nokta başına safe value, aralık ve test planı; canlı yazma öncesi insan onayı. | D + H |
| A14 | Bozulan dosyaları kurtardı (UTF-16, truncation, `sanitize.py`) | Karşılığı yok. Normal VCS ve build disiplini. **Ürüne taşınmaz.** | — |
| A15 | Kopyalar üzerinde çalıştı, sandbox path guard'ları ekledi | Staging workspace yöneticisi: immutable girdi, staging'de build, verify, sonra publish. | D |
| A16 | "Başarılı" kararını verdi ve raporları yazdı | Verifier makine-okunur evidence üretir; release kararını insan verir. | D + H |
| A17 | Template sorunlarını düzeltti (`device.update`, duplicate Application) | Adapter Empty template + explicit device kullanır; Standard template yolu kapanır. | D |
| A18 | Çalışan proses temizliği (IWIN32, runtime stop, `stop.flag`) | Adapter proses sahipliği takibi + deterministik teardown. | D |
| A19 | `bms_web` "AI analysis" fixture'ını üretti | Gelecekte: LLM, dokümandan **taslak model** çıkarır → validator → insan onayı. Şu an kapsam dışı. | L + H |
| A20 | Scaling (x10), aralık, tip seçimini o anki ihtiyaca göre yaptı | Model nokta bazında scaling/tip tanımlar; validator INT16 sığmasını kontrol eder. | D (+ H yazım) |

**Sonuç:** Ajanın POC'deki en değerli işi (A4, A10, A11 — keşif ve teşhis) ürüne **bilgi** olarak girer, ajan olarak girmez. Ürün runtime'ında ajan veya MCP bağımlılığı olmamalı (PD8 ile uyumlu).

---

## 3. Production blockers

Ürün geliştirmeye başlamadan önce çözülmesi veya bilinçli bir kararla kapsam dışı bırakılması gereken konular:

| ID | Blocker | Neden kritik | Bağlı test |
|---|---|---|---|
| B1 | **Ajansız uçtan uca reprodüksiyon yok.** Zincir hiç tek girdiden, tek koşuda, ajan olmadan çalıştırılmadı. | Ürünün temel iddiası bu. Yoksa ürün "ajan + uzman" demek olur. | S1 |
| B2 | **Generator → çalışan PLC yolu kanıtsız.** Canlı kod elle yazıldı. | Ürünün değeri üretilmiş kodun çalışması. | S1, S7 |
| B3 | **I/O mapping yamalı `%TEMP%` handler'a bağımlı** (Q3). | Toolkit yeniden stage edildiğinde kaybolur; tekrarlanamaz. | S1 |
| B4 | **Veri tipi sözleşmesi tanımsız** (REAL/32-bit, BOOL/coil, discrete input). | Canonical model'in tip sistemi buna bağlı. Önce tip, sonra şema. | S3 |
| B5 | **Lisans ve hukuki durum belirsiz.** MasterSCADA otomasyonu dokümante edilmemiş iç API'lere, internal test DLL'ine (`UIServiceForTests`) ve decompile edilmiş vendor koduna dayanıyor. MasterSCADA Demo lisansı, CODESYS runtime lisansı üretim için netleşmedi. | Ticari ürün yasal/teknik olarak vendor'un iznine bağlı olabilir. Teknik test ile çözülemez. | S8 + vendor görüşmesi |
| B6 | **Üretim MasterSCADA runtime deployment'ı bilinmiyor** (Q7). Sadece debug EmulatorSession kanıtlı. | Ürün çıktısı müşteride çalışmalı. | (Phase 0 sonrası; GO kriterinde kapsam kararı) |
| B7 | **Revision/regeneration stratejisi bilinmiyor.** Proje dosyaları binary (CODESYS project, Firebird `.fdb`); elle yapılan mühendislik değişiklikleri yeniden üretimde kaybolur. | Gerçek projeler sürekli revize edilir. Mimarinin merkezi kararı. | S6 |
| B8 | **POC'de secret sızıntısı**: CODESYS kimlik bilgileri ~13 script, log ve `DEMO_REPORT.md` içinde hardcoded. | POC klasörleri paylaşılamaz; ürün reposuna kopyalanmamalı. | Housekeeping (test değil) |
| B9 | **Commissioning manuel adımları** (gateway active path, elevated servis start) script edilemiyor. | "Tam otomatik deploy" iddiası şu an yapılamaz. Ürün kapsamı buna göre tanımlanmalı. | S1 (dokümante edilmiş ön koşul olarak) |

---

## 4. Architecture risks

| ID | Risk | Tür | Olasılık / Etki | Not |
|---|---|---|---|---|
| R1 | **Vendor internal API bağımlılığı (MasterSCADA)**: dokümante edilmemiş object model, internal test sınıfı, Rusça default isimler, 1.2.18.32894'e pinli. Upgrade'de kırılabilir; vendor desteklemeyebilir. | Teknik + hukuki | Yüksek / Yüksek | En büyük tekil risk. |
| R2 | **Tek örnekten genelleme**: 1 AHU, 2 MasterSCADA kanalı, 1 yazılabilir HMI kontrolü, 1 veri tipi (INT16). | Kanıt | Kesin / Yüksek | Tüm "CONFIRMED"lar bu dar tabanda. |
| R3 | **Üretilmiş PLC kodunun güvenliği**: gerçek ekipmanı süren kod. POC'deki PLC mantığı bir plant simülatörüydü; gerçek bir kontrol stratejisi kütüphanesi **hiç yok**. | Ürün + güvenlik | Yüksek / Çok yüksek | Ürünün asıl değeri tamamen yazılmamış durumda. |
| R4 | **Regeneration ile manuel düzenlemelerin çatışması** (binary proje formatları, diff/merge yok). | Mimari | Yüksek / Yüksek | S6. |
| R5 | **Commissioning otomasyonu sınırı** (gateway, elevation). | Ürün kapsamı | Kesin / Orta | Runbook ile yönetilebilir. |
| R6 | **Lisans**: Demo limitleri bilinmiyor; üretim runtime/tag lisansları, headless/otomatik kullanımın lisans koşulları. | İş | Bilinmiyor / Yüksek | |
| R7 | **Üretim runtime deployment** sadece debug modda kanıtlı. | Teknik | Orta / Yüksek | Q7. |
| R8 | **Ölçek ve performans**: CODESYS IDE spin-up 45–54 sn, proje başına `.fdb` ~58 MB, proje başına tek proses, Modbus area 10 word (POC). | Teknik | Orta / Orta | S4. |
| R9 | **Veri tipi kapsamı**: REAL/32-bit word order, BOOL, discrete input bilinmiyor; LREAL→INT dönüşümü kesirli/aralık dışı değerlerde tanımsız. | Teknik + güvenlik | Yüksek / Yüksek | S3. |
| R10 | **LLM güvenilirliği**: hiç test edilmedi. Yanlış çıkarılmış bir nokta (yön, scaling, aralık) sahada yanlış komut demektir. | Ürün + güvenlik | Bilinmiyor / Yüksek | S9; LLM sadece taslak model üretir. |
| R11 | **Güvenlik yüzeyi**: Modbus TCP'de kimlik doğrulama yok; HMI web erişim kontrolü belirsiz; embedded Firebird vendor default kimlik bilgileri; POC'de hardcoded secret. | Güvenlik | Yüksek / Yüksek | |
| R12 | **Müşteri verisi / gizlilik**: proje çizimleri, IP adresleri, tesis topolojisi; LLM'e gönderim; decompile edilmiş vendor kodu repoda. | Hukuki | Orta / Yüksek | |
| R13 | **Platform kilidi**: Windows, .NET Framework 4.6.1, x64 host + 32-bit CODESYS IDE, belirli SP. | Teknik | Kesin / Orta | |
| R14 | **Kanıt kalitesi**: testler çoğunlukla tek koşu; test ortamı provenance'ı eksik (X-09); "ack ≠ applied" (v2) zaten bir kez yanılttı. | Süreç | Kesin / Orta | Independent verification gerekçesi. |
| R15 | **Otomatik yazma davranışları**: POC istemcisinin connect anında setpoint seed etmesi (X-07). | Güvenlik | Orta / Yüksek | Ürün kuralı: yazma sadece açık operatör aksiyonu veya onaylı commissioning testi ile. |

### 4.1 İstenen konuların tek tek değerlendirmesi

| Konu | Durum | Kanıt | Eksik olan |
|---|---|---|---|
| Agentless build | **UNKNOWN** (parçalar PROBABLE) | Bağlantılar scriptable (C1, C3, C13, S8, H9) | Ajansız tek koşu; yamasız mapping; manuel adımlar BLOCKED |
| Deterministic generation | **PROBABLE** | ST generator build 0 error (C3); spec-driven MS/HMI builder'lar | Aynı girdi → aynı çıktı testi; generator çıktısının PLC'de çalışması |
| Repeatability | **UNKNOWN** | — | İki temiz koşu + semantik diff |
| Canonical model | **UNKNOWN** (yok) | 4-5 ayrı spec (AF1) | Şema, tek kaynak |
| Schema validation | **UNKNOWN** (yok) | — | Hepsi |
| Modbus datatype handling | **CONFIRMED (INT16 signed, x10 scale, INT16 bitfield)** | M5, S16, H11 | Diğer tüm tipler |
| REAL / 32-bit | **UNKNOWN** (tek word'e map FAILED) | F6, M4 | 2-word REAL, CODESYS ↔ MasterSCADA word/byte order (settings 4/9) |
| BOOL / coil | Coil **UNKNOWN** (sonuçsuz test, X-05); discrete input **UNKNOWN**; INT16 içinde bit **CONFIRMED (PLC ↔ pymodbus)** | M1, F7, M2, M5 | Coil'in açık mapping ile tekrar testi; MasterSCADA'da tek bit çıkarma |
| Address collision | **UNKNOWN** | Adresler elle atandı | Allocator + validator kontrolü; area kapasitesi (POC 10 word) |
| Multiple equipment types | **UNKNOWN** | Sadece AHU | İkinci ekipman tipi |
| PLC behavioral testing | **PROBABLE (teknik olarak)** | M5 probe sequence'i kontrol etti | Kontrol mantığından ayrı plant simülasyonu; test çerçevesi |
| Alarm handling | **UNKNOWN** | MS'de "Event Alarm" AddItem sadece listelendi; PLC demo alarm bitleri (IR5) var | MS alarm nesnesi oluşturma + runtime tetikleme |
| Trend / history | **UNKNOWN** | "Data archive" listelendi; `InsertCreateChannel(historySupport)` parametresi görüldü | Oluşturma + veri yazıldığının kanıtı |
| Revision / regeneration | **UNKNOWN** | — | S6 |
| Rollback | **UNKNOWN** | Sadece elle alınmış yedekler (`_V2_BACKUP`, `_RECOVERED_*`); online change UNKNOWN | Versiyonlu artifact + geri dönüş testi |
| Project isolation | **PROBABLE** | Kopyalar üzerinde çalışma, ayrı EmulatorSession (D10, D11) | Aynı makinede çoklu proje; port çakışması gözlendi (F26) |
| Scaling | **UNKNOWN** | 15 mapping, 2 MS kanalı | S4 |
| CODESYS version dependency | **CONFIRMED risk** | SP22 API'de gateway yok; template versiyon pin'leri (F2, F5) | Diğer versiyonlar UNKNOWN |
| MasterSCADA version / API dependency | **CONFIRMED risk** | Internal API, test DLL, 1.2.18 pin (04 §10) | Upgrade davranışı UNKNOWN; vendor desteği UNKNOWN |
| License / runtime dependency | **UNKNOWN** | MS Demo; CODESYS runtime lisans durumu kayıtlı değil | Vendor cevabı; limit testi |
| Security / secrets | POC'de **FAILED** | Hardcoded credentials (02 §8, AF13) | Secret store, log redaction, Modbus/HMI erişim modeli |
| Customer data / privacy | **UNKNOWN** | Gerçek müşteri verisi kullanılmadı | Veri sınıflandırma, LLM'e gönderim politikası |
| LLM reliability | **UNKNOWN** | Pipeline'da hiç LLM yok; fixture | S9 |
| Human approval | **UNKNOWN** | POC onayları sohbet içi kısıtlardı | Onay noktaları ve kaydı |

### 4.2 30 başarısız deneyden çıkan kalıcı kurallar

Bunlar ürün mimarisine **kural** olarak girer (ajan davranışı olarak değil):

| Kural | Kaynak | Kural metni |
|---|---|---|
| PR-01 | F6, F23 | Bir mantıksal değer, kendi bit genişliğine uygun sayıda register'a map edilir. 32-bit değer tek 16-bit word'e asla map edilmez. Desteklenmeyen tip validator'da reddedilir. |
| PR-02 | F7, X-05 | Kanıtlanmamış Modbus alanları (coil, discrete input) S3 geçene kadar validator'da yasaktır. |
| PR-03 | F4, F5 | Vendor cihaz/kütüphane nesneleri isimle değil, explicit type/id/version ile referanslanır; pinli bir katalogdan gelir. Standard template kullanılmaz. |
| PR-04 | F1, F2, F3, F9 | Manuel/privileged ön koşullar (gateway path, servis elevation, kurulum tespiti) adapter içinde preflight check olarak kontrol edilir; eksikse işlem başlamadan net hata ile durur. Hiçbir adapter bir dialogu veya hang'i "bekleyerek" çözmeye çalışmaz. |
| PR-05 | F8, F10 | Adapter'lar tipli, şema-doğrulamalı arayüz sunar. Argüman şekli denemesi yapılmaz. |
| PR-06 | F11, F12, F16 | Vendor host bootstrap tek, test edilmiş bir başlangıç rutinidir; eksik servis (ör. `IUIService`) ile asla devam edilmez. |
| PR-07 | F13, F18, F27 | GUI/dialog/koordinat tabanlı otomasyon ürün yolunda kullanılmaz. Sadece API. |
| PR-08 | F15, AF12 | Vendor projeleri staging kopyasında üretilir; kalıcılık açık bir save adımıyla sağlanır; yayın verify sonrası yapılır. Kullanıcı projeleri asla doğrudan açılmaz. |
| PR-09 | F14, F21, F22, AF6 | Bir API'nin başarı dönmesi (ör. `{"code":0}`) başarı kanıtı değildir. Her yazma işlemi bağımsız bir kanaldan (PLC register read-back) doğrulanır. |
| PR-10 | F20, F21, D12 | HMI yazma yolu: control → tipli server parameter → server link → channel Output. Doğrudan control → Modbus Output linki üretilmez. |
| PR-11 | F24 | Link oluşturma yönü (pin tarafından `SetLink`) generator kuralıdır; deneme ile bulunmaz. |
| PR-12 | F26, A8 | Port ve kaynak tahsisi konfigürasyondan gelir; çakışmada sistem durur ve raporlar, kendiliğinden alternatif seçmez. |
| PR-13 | F28, F29, F30 | Ajan-ortamı hataları (dosya truncation, encoding, shell quoting) ürün gereksinimi değildir; ürün kodunda bunlara özel workaround bulunmaz. Tüm üretilmiş metin UTF-8, NUL içermez — bu bir verifier kontrolüdür. |
| PR-14 | X-07, D14 | Hiçbir istemci bağlantı anında PLC'ye yazmaz. Yazma sadece açık operatör aksiyonu veya onaylanmış commissioning testi ile yapılır. |
| PR-15 | F19 | Trafik/dosya izleme gibi teşhis araçları ürün pipeline'ının parçası değildir; sadece destek araçlarıdır. |

---

## 5. Validation matrix

Tüm testlerin durumu: **NOT RUN**. Test ID'leri Phase 0 senaryolarına (S1–S9) bağlıdır.

| Test ID | Risk | Test | Input | Expected result | Pass criteria | Failure decision | Status |
|---|---|---|---|---|---|---|---|
| V-S1.1 | B1, B2 | Ajansız uçtan uca build | Mevcut AHU POC girdileri (yeni yazılmış tek bir spec dosyası), temiz makine durumu, yazılı runbook | CODESYS projesi + MS projesi + HMI script'lerle üretilir, deploy edilir, çalışır | Ajan/LLM müdahalesi 0; runbook dışı manuel adım 0; tüm adımlar exit code ile | Hangi adımın ajan gerektirdiği kaydedilir; o adım çözülmeden ürün başlamaz | NOT RUN |
| V-S1.2 | B3 | Yamasız I/O mapping (Q3) | Temiz CODESYS projesi, saf ScriptEngine mapping script'i | 15/15 mapping, build 0 error, Modbus probe geçer | `%TEMP%` yaması yok; mcptoolkit `map_io` yok | Mapping için kendi adapter operasyonu bulunamazsa CODESYS adapter mimarisi yeniden değerlendirilir | NOT RUN |
| V-S1.3 | B2 | Generator çıktısının PLC'de çalışması | Generator'dan üretilmiş ST (elle yazılmış değil) | İndirilir, RUN durumuna geçer, Modbus probe beklenen davranışı gösterir | Üretilmiş kod ile elle yazılmış kodun interface davranışı eşit | Generator yaklaşımı (text ST) gözden geçirilir; PLCopen XML gibi alternatif araştırılır | NOT RUN |
| V-S1.4 | R14 | Tekrarlanabilirlik | Aynı girdi, iki temiz koşu | CODESYS: aynı ST metni + aynı mapping dump; MS: aynı item tree / settings read-back | Semantik diff = 0 (byte diff beklenmez) | Determinizmi bozan alan (GUID, sıra, timestamp) tespit edilir; normalize edilemezse verify semantiği değişir | NOT RUN |
| V-S3.1 | R9, B4 | REAL 32-bit (2 word) | CODESYS REAL → 2 IR word; MS ValueType 2, byte order setting 4 = varyasyonlar | MS ve pymodbus aynı float değeri okur | ±0 bit hata, en az 5 değer (negatif, 0, büyük, küçük, kesirli) | REAL desteklenmez; tüm analoglar scaled INT16 kuralına bağlanır (validator kuralı) | NOT RUN |
| V-S3.2 | R9 | BOOL / coil | Açık mapping ile coil + discrete input; MS ValueType 1 | Coil yazma PLC değişkenini değiştirir; DI okunur | Her yön için read-back eşleşir | Coil/DI yasak kalır; BOOL = INT16 içinde bit (CONFIRMED pattern) | NOT RUN |
| V-S3.3 | R9 | MasterSCADA'da INT16'dan bit çıkarma | IR0 status word | MS'de bit-level sinyal (alarm/HMI) doğru | Her bit için doğru değer | BOOL'lar ayrı register'a taşınır (adres maliyeti kabul edilir) | NOT RUN |
| V-S3.4 | R9, R15 | LREAL→INT dönüşüm sınırları (HMI yazma yolu) | Server parameter'a 1.5, -1, 40000 yazma | Davranış belgelenir (yuvarlama/kesme/red) | Davranış deterministik ve belgeli; aralık dışı değer PLC'ye ulaşmaz veya PLC reddeder | HMI tarafına aralık sınırlaması zorunlu üretim kuralı olur | NOT RUN |
| V-S6.1 | B7, R4 | Regeneration: nokta ekleme | Model rev1 → rev2 (+1 nokta) | Yeni proje üretilir; mevcut noktaların adresleri değişmez | rev1 noktalarının adresleri ve isimleri birebir korunur | Allocation lock zorunlu; yoksa mimari değişir | NOT RUN |
| V-S6.2 | B7, R4 | Regeneration: manuel değişikliğin akıbeti | rev1 projesinde MS GUI'de elle bir değişiklik + regenerate | Değişikliğin kaybolduğu/korunduğu tespit edilir | Davranış belgelenir; tespit mekanizması (drift detection) mümkün mü? | "Üretilmiş projeye elle dokunulmaz" kuralı + drift verifier | NOT RUN |
| V-S6.3 | Rollback | Önceki revizyona dönüş | rev2 → rev1 artifact'leri | rev1 tekrar deploy edilir ve doğrulanır | Verify rev1 ile eşleşir | Rollback = "eski artifact'i yeniden deploy" olarak tanımlanır; online change kapsam dışı | NOT RUN |
| V-S2.1 | R2 | İkinci ekipman tipi | AHU + farklı bir tip (ör. pompa veya fan coil), aynı model formatı | Her iki ekipman tek pipeline ile üretilir | Adapter kodunda değişiklik yok; sadece template + model | Model/template ayrımı yeniden tasarlanır | NOT RUN |
| V-S2.2 | Address collision | Çoklu ekipman adres tahsisi | 2+ ekipman, aynı controller | Çakışmasız adresler | Validator kasıtlı çakışmayı yakalar; allocator çakışma üretmez | Allocator tasarımı düzeltilir | NOT RUN |
| V-S5.1 | Alarm | MS alarm nesnesi API ile oluşturma | Bir bit/eşik için Event Alarm | Alarm oluşur, persist olur, runtime'da tetiklenir | Fresh-process verify + runtime tetikleme kanıtı | Alarmlar kapsam dışı / manuel; ürün değeri yeniden değerlendirilir | NOT RUN |
| V-S5.2 | Trend | MS Data archive / history | Bir analog kanal | Arşive veri yazılır, okunur | Zaman damgalı N örnek okunur | Trend kapsam dışı | NOT RUN |
| V-S7.1 | R3 | PLC davranış testi (ayrı plant sim) | Template kontrol mantığı + ayrı simülasyon modülü | Senaryo testleri (start, stop, fault, aralık dışı setpoint) geçer | Her senaryo için beklenen state/çıkış; kontrol kodu simülasyon içermez | Davranış testi CODESYS'te yapılamıyorsa harici test yaklaşımı araştırılır | NOT RUN |
| V-S7.2 | R3, R15 | Güvenli durum davranışı | Comms kaybı, geçersiz komut, fault | PLC güvenli duruma geçer | Belgelenmiş safe state'e ulaşılır | Template kabul edilmez | NOT RUN |
| V-S4.1 | R8, R6 | Ölçek | N ekipman (ör. 10 → 50), ~500+ nokta | Build/verify süresi ve başarı ölçülür | Süreler kayıtlı; Demo lisans limiti tespit edilir; hata yok | Ölçek sınırı ürün kapsamına yazılır veya mimari (proses başına proje) değişir | NOT RUN |
| V-S4.2 | Isolation | Aynı makinede iki projenin paralel build'i | 2 farklı model | Birbirini etkilemez | Port/dosya/proses çakışması yok | Seri kuyruk (tek worker) zorunlu olur | NOT RUN |
| V-S8.1 | R1, R13 | Version gate | Farklı CODESYS SP / MasterSCADA build (mümkünse) | Adapter versiyonu tespit eder; desteklenmeyende durur | Verify suite pinli versiyonda geçer; diğerinde net hata | Tek versiyon desteği ürün koşulu olur | NOT RUN |
| V-S8.2 | R1 | `UIServiceForTests` bağımsızlığı (Q13) | Kendi `IUIService` implementasyonu | Aynı build + verify | 76/76 eşdeğeri | Internal test DLL bağımlılığı kabul edilen risk olarak belgelenir | NOT RUN |
| V-S8.3 | B5, R6 | Vendor/lisans teyidi (teknik değil) | MPS SOFT / CODESYS'e yazılı soru | Otomatik/headless kullanım ve runtime lisansları netleşir | Yazılı cevap | NO-GO veya kapsam değişikliği | NOT RUN |
| V-S9.1 | R10 | LLM → canonical model | Bilinen cevaplı test dokümanları (ör. AHU nokta listesi) | LLM taslak model üretir | Validator geçer; ground truth'a karşı precision/recall ölçülür; hiçbir taslak insan onayı olmadan ilerlemez | LLM sadece öneri aracı kalır veya kapsam dışı | NOT RUN |
| V-SEC.1 | R11, B8 | Secret taraması | Ürün reposu + POC'den taşınacak her dosya | Secret bulunmaz | Tarama 0 bulgu | Taşıma durdurulur | NOT RUN |

---

## 6. Recommended Phase 0

Önem sırası (ürün kararını en çok etkileyen ve en ucuz yanlışlanabilen testler önce):

| Sıra | Senaryo | Neden bu sırada | Bağlı test ID'leri |
|---|---|---|---|
| 1 | **S1 Agentless Build** | Ürünün varlık sebebi. Başarısız olursa diğer testlerin anlamı yok. Aynı zamanda B2, B3 ve tekrarlanabilirliği ölçer. | V-S1.1 – V-S1.4 |
| 2 | **S3 REAL / BOOL / Coil Mapping** | Canonical model'in tip sistemi buna bağlı. Şemadan **önce** bilinmeli. Ucuz ve hızlı. | V-S3.1 – V-S3.4 |
| 3 | **S6 Revision / Regeneration** | Mimarinin merkez kararı (full regenerate + allocation lock vs. incremental). Yanlış seçilirse sonradan değiştirmek pahalı. | V-S6.1 – V-S6.3 |
| 4 | **S2 Multiple Equipment Types** | Tek örnekten genelleme riskini (R2) kırar; model/template ayrımını test eder. S3 ve S6'dan sonra anlamlı. | V-S2.1, V-S2.2 |
| 5 | **S7 PLC Behavioral Testing** | Ürünün güvenlik temeli (R3). Template yaklaşımının test edilebilir olduğunu kanıtlamalı. | V-S7.1, V-S7.2 |
| 6 | **S5 Alarm / Trend / Archive** | BMS için temel özellik, ama MS API'sinde tamamen bilinmiyor. Sonuç ürün kapsamını belirler, temel mimariyi değil. | V-S5.1, V-S5.2 |
| 7 | **S8 Version Compatibility** | Kısa vadede "tek versiyona pin" ile yönetilebilir. Vendor/lisans teyidi (V-S8.3) ise **hemen, paralel** başlatılmalı. | V-S8.1 – V-S8.3 |
| 8 | **S4 Scale Test** | Pipeline ajansız ve tipli olmadan ölçek ölçmenin anlamı yok. Demo lisans limitleri sonuçları bozabilir. | V-S4.1, V-S4.2 |
| 9 | **S9 LLM Input → Canonical Model** | Model ve validator olmadan test edilemez. LLM opsiyonel bir giriş katmanı; ürünün çekirdeği değil. | V-S9.1 |

Paralel ve teknik olmayan işler (Phase 0 boyunca):

- Vendor / lisans sorusu (V-S8.3) — teknik test değil, ama sonucu NO-GO olabilir.
- POC secret temizliği (B8) — POC'den ürün reposuna **hiçbir dosya** bu yapılmadan taşınmaz.

---

## 7. GO / NO-GO criteria

### 7.1 GO — ürün geliştirmeye başlamak için **hepsi** gerekli

| # | Koşul | Kanıt |
|---|---|---|
| G1 | AHU zinciri, yazılı bir runbook ile, **ajan/LLM olmadan** sıfırdan iki kez üretilip deploy edildi. Runbook dışı manuel adım 0. | V-S1.1 evidence |
| G2 | Modbus I/O mapping, yamalı `%TEMP%` handler olmadan çalıştı. | V-S1.2 |
| G3 | **Generator'dan üretilmiş** PLC kodu indirildi, çalıştı ve Modbus probe'dan geçti. | V-S1.3 |
| G4 | İki koşunun semantik verify çıktıları eşit. | V-S1.4 |
| G5 | Desteklenen veri tipi listesi **kanıtla** donduruldu (her tip için CONFIRMED veya validator'da açıkça yasak). | V-S3.x |
| G6 | Regeneration stratejisi kanıta dayanarak seçildi; revizyonda mevcut adresler korunuyor. | V-S6.1, V-S6.2 |
| G7 | Vendor/lisans konusunda, ticari kullanımı engellemeyen yazılı bir cevap var **veya** bilinçli olarak kabul edilmiş, belgelenmiş bir risk kararı var. | V-S8.3 |
| G8 | POC'den taşınacak hiçbir dosyada secret yok. | V-SEC.1 |

### 7.2 NO-GO — herhangi biri ürünü durdurur

| # | Koşul |
|---|---|
| N1 | Zincirdeki herhangi bir adım ajan veya LLM yönlendirmesi olmadan tamamlanamıyor ve deterministik bir karşılığı bulunamıyor. |
| N2 | Generator'dan üretilmiş PLC kodu, elle yazılmış kodla aynı interface davranışını gösteremiyor. |
| N3 | Vendor lisansı headless/otomatik MasterSCADA veya CODESYS kullanımını açıkça yasaklıyor ve alternatif hedef yok. |
| N4 | Regeneration mevcut adres/isimleri koruyamıyor ve bunu çözen bir tahsis mekanizması kurulamıyor. |
| N5 | Aynı girdi farklı semantik çıktılar üretiyor ve fark normalize edilemiyor. |

### 7.3 Koşullu GO (kapsam daraltma ile)

Aşağıdakiler başarısız olursa ürün **durmaz**, kapsamı daralır:

- REAL başarısız → tüm analoglar scaled INT16 (validator kuralı).
- Coil/DI başarısız → BOOL'lar INT16 içinde bit.
- Alarm/trend API ile yapılamıyor → v1 kapsamında alarm/trend yok, belgelenir.
- Gateway/elevation script edilemiyor → commissioning runbook ürün parçası olur.
- Üretim MS runtime deployment bilinmiyor → v1 çıktısı "doğrulanmış MasterSCADA proje paketi" olur, deployment müşteri/entegratör adımı olarak kalır.

---

## 8. Recommended architecture

**Bu bölüm bir öneridir (PROPOSED). Hiçbir parçası implement edilmedi.**

```text
AI / LLM                         (opsiyonel, advisory)
      ↓  draft model
Canonical Engineering Model      (tek kaynak, versiyonlu)
      ↓
Validator                        (kabul kapısı)
      ↓  approved model + allocation lock
Deterministic Generators         (saf fonksiyonlar)
      ↓  artifact descriptors
Adapters                         (yan etkili, vendor'a özel)
      ↓
CODESYS / Modbus / MasterSCADA / HMI
      ↓
Independent Verification         (modelden beklenti türetir)
```

### 8.1 Her katmanın varlık sebebi

| Katman | Sorumluluk | Neden var (POC kanıtı) | Sorumlu OLMADIĞI şeyler |
|---|---|---|---|
| **AI / LLM** | Dokümandan **taslak** model önermek. | Hiç test edilmedi (fixture). Opsiyonel kalmalı, çünkü çekirdek pipeline onsuz çalışmalı. | PLC kodu, adres, vendor artifact, deploy, onay. |
| **Canonical Engineering Model** | Ekipman, nokta, tip, yön, aralık, scaling, safe value, template referansı. | Sinyaller 4-5 spec'te tekrarlandı; aralık çelişkisi (X-10). | Vendor-özel detaylar (setting ID, proje yolları). |
| **Validator** | Modelin generator'a girmesine izin veren tek kapı. | POC'de yoktu; desteklenmeyen tip (REAL→tek word) sahada hata olarak çıktı. | Vendor'a bağlanmak, artifact üretmek. |
| **Deterministic Generators** | Model → artifact descriptor (ST metni, register haritası, MS item spec, HMI spec). Saf, yan etkisiz. | `generate_st.py` deterministik ve test edilebilir olduğunu gösterdi. HMI v3 kuralı generator kuralı olmalı. | Dosya sistemi, proses, vendor API çağrısı. |
| **Adapters** | Descriptor'ları vendor araçlarına uygulamak; preflight; tipli hata; teardown. | Vendor erişimi kırılgan, versiyona bağlı, proses izolasyonu gerektiriyor (AF3, AF4). | İş kararı, adres tahsisi, varyasyonla retry, "çözüm bulma". |
| **Independent Verification** | Beklentiyi **modelden** türetip gerçek sistemden okunanla karşılaştırmak. | v2'de `{"code":0}` yazmanın uygulandığını göstermedi (AF6); X-09 provenance boşluğu. | Generator kodunu yeniden kullanmak (aynı hata iki yerde olmamalı). |

### 8.2 Canonical Model — minimum gerekli yapı

Sadece kanıtlanmış veya Phase 0'da kanıtlanacak alanlar. Alarm/trend alanları S5'e kadar **yok**.

```text
Project
  id, revision, created_by, approved_by, approved_at
  targets: { codesys_version, masterscada_version }      # version gate
  controllers[]
    id, kind (codesys_softplc), network { ip, port, unit_id }
    equipment[]
      id, type, template { id, version }
      points[]
        id                    # stabil, revizyonlar arası değişmez
        name                  # IEC 61131 + MasterSCADA isim kurallarına uygun
        role                  # command | setpoint | status | measurement
        direction             # to_plc | from_plc
        eng_type              # int16 | bitfield16 | (S3 sonrası: bool, real32)
        unit, range { min, max }, scale
        safe_value            # to_plc noktaları için zorunlu
        operator_writable     # HMI yazma izni
        hmi { visible, label }
        provenance { source: human|llm|import, ref }

Allocation (ayrı, generator tarafından yönetilen lock dosyası — insan yazmaz)
  point_id → { modbus_area, address, bit?, plc_var, ms_channel, ms_parameter? }
```

Tasarım notları:

- **Adresler modelde yazılmaz**, allocator üretir ve lock dosyasında tutar (A2, V-S6.1).
- `point.id` ile `name` ayrı tutulur; yeniden adlandırma adresi kaydırmaz.
- `provenance` LLM kaynaklı alanların insan onayından geçtiğini izlemek için var.
- Vendor-özel bilgi (setting ID 20/21/2, cihaz type/id) model değil, adapter kataloğudur.

### 8.3 Validator — ilk sorumluluklar

Öncelik sırasıyla:

1. **Şema geçerliliği** (zorunlu alanlar, enum değerleri).
2. **Kimlik bütünlüğü**: benzersiz id'ler, geçerli referanslar (template, controller).
3. **Tip whitelist'i**: sadece kanıtlanmış tipler (bugün: `int16`, `bitfield16`). Diğerleri S3 kanıtlanana kadar **red**.
4. **Scaling/aralık sığması**: `range × scale` INT16 sınırları (−32768..32767) içinde olmalı.
5. **Yön tutarlılığı**: `command` / `setpoint` → `to_plc` → Holding; `status` / `measurement` → `from_plc` → Input.
6. **Güvenlik alanları**: her `to_plc` noktasında `safe_value` ve `range` zorunlu; `safe_value` aralık içinde.
7. **Adres tahsisi**: çakışma yok; area kapasitesi aşılmıyor (kapasite controller konfigürasyonundan); önceki revizyonun tahsisleri korunuyor.
8. **İsim kuralları**: IEC 61131 identifier (uzunluk, karakter, reserved word), MasterSCADA isim kısıtları, benzersizlik.
9. **Hedef versiyon**: model, desteklenen ve pinlenmiş versiyon dışında bir hedef istiyorsa red.
10. **Provenance**: `source = llm` olan ve onaylanmamış nokta varsa red.

Validator'ın şimdilik **yapmayacağı** şey: HVAC mühendislik doğruluğu (ör. "bu AHU'da damper olmalı mı?").

### 8.4 Adapter sınırları

| Adapter | Girdi | Yaptığı | Yapmadığı | İzolasyon |
|---|---|---|---|---|
| **CODESYS Engineering** | ST descriptor, cihaz ağacı spec'i, mapping tablosu | Proje create (Empty template + explicit device), POU yazma, task, Modbus server device, I/O mapping, build, read-back dump | Kod üretmek, adres seçmek, online işlem | Ayrı proses (ScriptEngine `--noUI`), watchdog, exit code |
| **CODESYS Deploy** (ayrı) | Build edilmiş proje | Preflight (gateway, servis), login/download/start | Gateway ayarlamak, servisi elevation ile başlatmak | Commissioning zamanı; insan onayı ile |
| **Modbus** | — | **Adapter değil; sözleşme.** Register haritası generator çıktısıdır; Modbus istemcisi sadece verification aracıdır. | Değer uydurmak (D16), bağlantıda yazmak (PR-14) | — |
| **MasterSCADA Project** | MS item spec (protokol, modül, kanal, setting) | Bootstrap, staging'de create, item'lar, save, read-back dump | Kullanıcı projelerini açmak, SQL, GUI | Ayrı x64 .NET 4.x prosesi, version gate |
| **MasterSCADA HMI** (aynı proses, ayrı modül) | HMI spec (pencere, kontrol, link kuralları) | Pencere/kontrol/link üretimi, v3 yazma kuralı | Layout kararı (generator'ın işi) | Aynı proses (aynı proje kilidi) |
| **MasterSCADA Runtime Test** | Staging proje kopyası | Debug EmulatorSession ile runtime doğrulama | Üretim deployment | Sadece verification; ayrı port konfigürasyonu |

### 8.5 Independent Verification

1. **Statik read-back** (fresh process): CODESYS ve MasterSCADA projeleri ayrı bir proseste açılır, yapı ve ayarlar modelden türetilen beklentiyle karşılaştırılır.
2. **Protokol seviyesi**: Modbus istemcisi (pymodbus benzeri, vendor'dan bağımsız) register haritasını **modelden + allocation'dan** okur; güvenli değerler yazar, cevapları ölçer.
3. **Çapraz sistem**: MasterSCADA runtime'ın gösterdiği değer ile doğrudan Modbus okuması aynı mı?
4. **Davranışsal**: PLC template'leri, kontrol kodundan ayrı bir plant simülasyonuna karşı senaryo testleri (S7).
5. **Kurallar**: ack ≠ applied (PR-09); verifier generator kodunu import etmez; her koşu test ortamı provenance'ını kaydeder (hangi uygulama, hangi versiyon, hangi proje kopyası) — X-09'un tekrarını önlemek için.

---

## 9. What NOT to build yet

| Özellik | Neden erken |
|---|---|
| LLM doküman/çizim analizi | Model ve validator yok; hiç test edilmedi; güvenlik riski (R10). |
| Web UI / operatör arayüzü / `bms_web` genişletme | Çekirdek pipeline kanıtlanmadı; MasterSCADA HMI zaten hedef. |
| Alarm ve trend üretimi | MasterSCADA API'sinde UNKNOWN (S5). |
| REAL, coil, discrete input desteği | S3 öncesi validator'da yasak. |
| Incremental / online change / canlı güncelleme | Regeneration stratejisi (S6) seçilmedi; online change UNKNOWN. |
| Rollback sistemi | Önce "eski artifact'i yeniden deploy" yeterli mi görülmeli. |
| Çoklu PLC, uzak ağ, çoklu controller | Sadece tek localhost PLC kanıtlı. |
| BACnet, OPC UA, diğer protokoller | Sadece listelendi. |
| Çoklu vendor hedefi (CODESYS/MasterSCADA dışı) | Mevcut iki hedef bile tek örnekte. |
| Genel HVAC kontrol stratejisi kütüphanesi | Önce tek template'in test edilebilirliği (S7) kanıtlanmalı. |
| Üretim deployment orkestrasyonu | Gateway/elevation BLOCKED; üretim MS runtime UNKNOWN. |
| MCP entegrasyonu / Cursor kaydı | Ürün ajan bağımsız olmalı (PD8). |
| FUXA | DEPRECATED. |
| Multi-tenant / cloud / kullanıcı yönetimi | Tek makine tek proje bile kanıtlanmadı. |
| Plugin / extension sistemi | Erken soyutlama. |
| HMI layout motoru | Önce birden fazla kontrol tipinin yazma davranışı (Q4) kanıtlanmalı. |

---

## 10. Next exact step

**S1 / V-S1.1 + V-S1.2 — POC AHU zincirinin ajansız reprodüksiyonu.**

Ne demek:

- Bir insan operatör, **yazılı bir runbook** ile ve **sadece mevcut POC script'lerini** kullanarak (ajan yok, LLM yok, `%TEMP%` yaması yok, sohbet içinde kod düzenleme yok), AHU zincirini temiz bir başlangıç durumundan **iki kez** üretir ve çalıştırır.
- I/O mapping saf ScriptEngine script'i (`codesys_ahu_v2_plc_map.py`) ile yapılır (Q3).
- Her adım için şunlar kaydedilir: komut, exit code, süre, manuel müdahale (runbook içinde mi, dışında mı), evidence dosyası.
- Çıktı: hangi adımların bugün **gerçekten** ajansız çalıştığını, hangilerinin ajan bilgisine/müdahalesine ihtiyaç duyduğunu gösteren tek bir evidence raporu.

Neden bu adım:

- B1, B3 ve kısmen B2'yi en düşük maliyetle test eder; yeni ürün kodu gerektirmez.
- Sonucu, canonical model ve adapter tasarımının **gerçek** başlangıç noktasını belirler.
- Başarısız olursa, ürün kodu yazılmadan önce öğrenilmiş olur.

Bu adım bitene kadar implementation başlatılmaz.
