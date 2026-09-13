# PRISADKA MES — Andon monitor

Prisadka (qo'shimcha/additiv) stanogining signal ustunini o'qib, stanok holatini,
to'xtash vaqtlarini va detal sikllarini MES tizimiga uzatuvchi qurilma.

**Til:** kod izohlari va hujjatlar — o'zbekcha. O'zgaruvchi/funksiya nomlari — inglizcha.

---

## 1. Hozirgi holat

| Qism | Holat |
|---|---|
| Pico firmware (`firmware/`) | ✅ Yozilgan, simulyatsiyada tekshirilgan, temirda sinalmagan |
| USB-serial transport | ✅ `link_serial.py` + `mes/serial_bridge.py` (Wi-Fi'siz Pico uchun) |
| Testlar (`tests/`) | ✅ 45 ta test: fsm (14), link (8), bridge (10), serial (13) |
| MES prototipi (`mes/`) | ✅ Broker + SQLite + veb, stdlib'dan boshqa hech narsa kerak emas |
| Operator ekrani (sabab tanlash) | ✅ `http://localhost:8080` → "To'xtashlar" |
| Pico simulyatori (`sim/`) | ✅ Haqiqiy firmware kodi bilan, temirsiz sinov |
| Temirda sinov | 🟡 Qisman — Pico W'siz plataga MicroPython v1.29 o'rnatildi, firmware yuklandi, USB transport va MES→Pico buyruq yo'li tekshirildi. **Chiroq simlari hali ulanmagan** — qolgan sinovlar: `docs/tz.md` 12-bo'lim |
| Ishga tushirgich | ✅ `start.py` / `start.bat` — MES + ko'prik + Chrome bitta buyruqda |
| Mustaqil `.exe` | ✅ `build_exe.py` → `dist/PrisadkaMES.exe` (~9 MB), Python talab qilmaydi |
| Ishlab chiqarish brokeri (Mosquitto) + PostgreSQL | ❌ Yo'q — prototip SQLite/Python broker'da |
| MES PRO ga yozish | ⏳ Muhandislardan javob kutilmoqda — so'rov: `docs/mes-pro-integration.md` |

**Texnik topshiriq: `docs/tz.md`** — uskuna, ulash, mantiq, shartnoma,
qabul sinovlari. Yangi odam shu fayldan boshlaydi.

---

## 2. Uskuna va **buzib bo'lmaydigan** cheklovlar

- Raspberry Pi Pico (RP2040), MicroPython. **Bizdagi plata Wi-Fi'siz** —
  shuning uchun standart transport USB-serial (`TRANSPORT = "serial"`).
  Pico W bo'lsa `TRANSPORT = "wifi"` qilinadi, qolgan kod bir xil.
- Chiroq liniyalari **24 V DC**. Har biri PC817 optopara + 4.7 kΩ / 1 W rezistor
  orqali GPIO ga keladi. **24 V hech qachon GPIO ga to'g'ridan-to'g'ri ulanmaydi.**
- Chiroq yoniq → optopara ochiladi → **GPIO = 0** (`ACTIVE_LOW = True`).
- 24 V GND va Pico GND **ulanmaydi** (galvanik izolyatsiya).
- Pinlar: **GP1 = qizil, GP5 = sariq, GP9 = yashil**.

### Kod yozishda diqqat qilinadigan narsalar

- **Watchdog 8 s** (`WDT(timeout=8000)`, RP2040 maksimumi). Asosiy tsiklda
  1–2 sekunddan uzoq bloklovchi chaqiruv qo'yilmaydi. Uzoq kutish kerak bo'lsa
  ichida `wdt.feed()` chaqiriladi (`link.py` da `self.feed` shu uchun bor).
- **DNS ishlatilmaydi.** `MQTT_HOST` faqat IP. DNS so'rovi soketni bloklab,
  watchdog reset'ga olib keladi.
- **RAM cheklangan.** Asosiy tsiklda (har 2 ms) yangi lug'at/ro'yxat yaratilmaydi.
  `LampReader.update()` ataylab bitta va o'sha lug'atni qaytaradi.
- **Flash resursi.** `settings.json` faqat qiymat haqiqatan o'zgarganda yoziladi.
- `umqtt.simple` ning `check_msg()` soketni non-blocking qoldiradi — keyin
  bloklovchi rejim qaytarilishi shart. `link.py` da `sock.settimeout(...)`
  qo'yiladi: rejim tiklanadi, lekin osib qolgan soket watchdog reset qilmaydi.
  Olib tashlamang.
- **`link.pump()` bloklamaydi.** Wi-Fi ulanishi holat mashinasi ko'rinishida
  (`_wifi_ready`), 15 sekundlik kutish yo'q — aks holda o'sha paytda chiroqlar
  o'qilmay, holat o'zgarishlari yo'qolardi.
- **MQTT soketiga timeout shart** (`MQTT_SOCKET_TIMEOUT_S`, `link.py` dagi
  `_TimedSocket`). `umqtt` soketni o'zi yaratadi va timeout qo'ymaydi; broker
  javob bermasa `connect()` o'n soniyalab bloklaydi. `connect()` da uchta
  bloklovchi bosqich bor (TCP + CONNACK + SUBACK), shuning uchun timeout
  8 s / 3 dan kichik bo'lishi kerak.
- **NTP faqat IP** (`NTP_HOST = MQTT_HOST`). `ntptime` moduli ishlatilmaydi —
  ba'zi buildlarda soketga timeout qo'ymaydi va javob kelmasa cheksiz bloklaydi;
  `link._ntp_query()` o'z so'rovini yuboradi. Muvaffaqiyatsiz urinishdan keyin
  60 s kutiladi, aks holda har tsiklda qayta urinilardi.
- **Retained snapshot buferda to'planmaydi:** `link.enqueue(retain=True)` shu
  topikdagi eski yozuvni almashtiradi. Aks holda oflayn paytda har 30 sekundlik
  snapshot RAM ni to'ldirib (MemoryError → reset), haqiqiy eventlarni siqib
  chiqarardi.
- Vaqt hisobi faqat `time.ticks_ms()` / `ticks_diff()` orqali (overflow xavfsiz).
  `time.time()` faqat NTP dan keyin, event timestamp'i uchun.

---

## 3. Domen mantiqi — 4 buyruq

Bu loyihaning asosiy bilimi. Kodni o'zgartirishdan oldin shuni tushunish shart.

| Signal | Holat | Ma'nosi |
|---|---|---|
| Qizil (yoniq **yoki** miltillash) | `FAULT` | Avariya. MES da **sabab tanlanishi shart**. |
| Yashil **miltillash** | `AWAIT_PART` | QR chek skanerlandi, detal kutilmoqda. |
| Yashil **doimiy** | `PROCESSING` | Detal stanokka kirdi, ishlov berilmoqda. |
| Sariq | `IDLE` | Kutish rejimi. |
| Sariq, limitdan uzoq | `STOPPED` | **O'chiq** deb qayd etiladi. Sabab talab qilinadi. |
| **Hammasi o'chiq** | `OFF` | **Stanok o'chirilgan.** Sabab talab qilinadi. |

Prioritet: **qizil > yashil > sariq**.

### Kutish limiti

Sariq chiroq `idle_timeout_s` (standart 900 s = 15 daqiqa) dan uzoq yonsa,
holat avtomatik `IDLE` → `STOPPED` ga o'tadi. Limit ikki joydan boshqariladi:
`config.py` (boshlang'ich) va MQTT `cmd` topigi (ishlab turgan holda, `settings.json` ga saqlanadi).

**Nozik jihat:** `fsm.py` da `_idle_since` sariq **uzluksiz yonayotgan** vaqtni
alohida sanaydi, `state_at` dan foydalanmaydi. Sababi: `STOPPED` ga o'tgandan keyin
`state_at` yangilanadi va agar hisob undan olinsa, holat `IDLE` ga qaytib,
cheksiz aylanib qoladi. Bu joyni soddalashtirmang.

### QR skan navbati (MES tomonida)

QR skaner **Pico ga ulanmagan** — chek MES tizimida o'qiladi va parallel
ravishda stanok progasiga ham ketadi. Pico faqat chiroqni ko'radi.

Operator **ishlov ketayotgan paytda** keyingi detalning chekini skanerlab
qo'yishi mumkin: chiroq doimiy yashil qolaveradi, ishlov tugashi bilan
darhol miltillashga o'tadi. Hech narsa skanerlanmagan bo'lsa — sariq yonadi.

Shundan kelib chiqadigan uchta qoida (`mes/bridge.py`):

1. Navbat **FIFO** — `AWAIT_PART` eng eski bog'lanmagan skanni oladi.
2. Oyna **uzun** (4 soat) — skan `AWAIT_PART` dan daqiqalar oldin bo'lishi mumkin.
3. `PROCESSING/AWAIT_PART → IDLE/STOPPED/OFF` — stanok "navbat bo'sh" deb
   aytmoqda → qolgan skanlar eskiradi. Bu hisobni o'zi-o'zidan to'g'rilaydi:
   o'qilgan-u solinmagan chek keyingi detalga yopishib qolmaydi.

Testlar: `test_scan_during_processing_binds_to_next_part`,
`test_scan_queue_is_fifo`, `test_yellow_lamp_expires_stale_scans`.

### Miltillash boshlanishi — eng nozik joy

Yashil chiroq miltillay boshlaganda **birinchi yarim davr doimiy yoniq bo'lib
ko'rinadi**: `lamps.py` ikkita qirra ko'rmaguncha "blink" deya olmaydi.
Shuning uchun `MIN_STATE_MS` miltillashning yarim davridan **katta** bo'lishi
shart (hozir 1200 ms, `BLINK_WINDOW_MS = 2000` ga mos). Kichik bo'lsa, har QR
skanda soxta `PROCESSING` qayd etiladi va **ortiqcha detal sanaladi**.

Bu xato simulyatsiyada topilgan. Test: `test_blink_onset_not_counted_as_processing`.

Ikkinchi himoya: `MIN_PROCESS_MS` (5 s) dan qisqa ishlov detal deb sanalmaydi.

`fsm._commit` da vaqt **nomzod paydo bo'lgan paytdan** olinadi (`_cand_at`),
commit paytidan emas. Shu tufayli `MIN_STATE_MS` ni oshirish davomiyliklarni
buzmaydi. Buni o'zgartirmang.

### Stanok o'chirilgan (`OFF`)

Uchchala chiroq ham o'chiq bo'lsa stanok o'chirilgan — bu ham to'xtash
yozuvi ochadi va sabab talab qiladi (smena tugadi / elektr uzildi / ta'mir).

**Nozik jihat:** PLC bir chiroqni o'chirib ikkinchisini yoqguncha oraliqda
hamma chiroq o'chiq bo'lib qolishi mumkin. Shu sababli `OFF` boshqa
holatlardan farqli — `OFF_CONFIRM_MS` (5 s) tasdiqlanadi, `MIN_STATE_MS`
(1.2 s) emas. Test: `test_short_all_dark_gap_is_not_machine_off`.

**Uskuna oqibati:** Pico chiroqlardan mustaqil quvvatlanishi shart, aks
holda stanok bilan birga o'chib, bu hodisani xabar qila olmaydi. USB
transportda bu shart o'z-o'zidan bajariladi (`docs/tz.md` 3.5-bo'lim).

### To'xtash yozuvi (downtime)

`FAULT`, `STOPPED` va `OFF` — sabab talab qiladigan holatlar. Eventda:

- yangi to'xtash ochilsa — `downtime_id` + `reason_required: true`;
- ochiq to'xtash yopilsa — `closes_downtime_id`.

**Nozik jihat:** `STOPPED → FAULT` o'tishida bitta event ikkalasini ham olib
keladi. `fsm._commit` da yopish va ochish `elif` bilan bog'lanmagan — bog'lansa,
STOPPED yozuvi MES da abadiy ochiq qolib, "sababsiz to'xtashlar" ro'yxatiga
umuman tushmaydi. Bu joyni birlashtirmang.

`downtime_id` = `<MACHINE_ID>-<session>-<seq>`, masalan `PRISADKA-01-a3f19c-142`.
`session` — har yuklanishda yangilanadigan tasodifiy 6 belgili id
(`fsm.new_session()`). U shuning uchun kerakki, `seq` reboot'dan keyin noldan
boshlanadi: sessiyasiz `downtime_id` lar va MES dagi yagona kalitlar
(`machine_id, session, seq`) to'qnashib, ma'lumot yo'qolardi. Ataylab flash'ga
yozilmaydi — qurilma reset tsikliga tushsa, hisoblagich flash resursini yerdi.

### Detal sikli

```
QR skan → yashil miltillaydi → yashil doimiy → keyingi QR
          └── wait_s ───────┘   └─ process_s ─┘
```

Sikl yopilish qoidalari (`fsm._commit` da):
- `PROCESSING` → `FAULT` — sikl **uzilmaydi**, `_proc_ms` saqlanadi, avariyadan
  keyin ishlov davom etadi.
- `PROCESSING` → `AWAIT_PART` — yangi QR kelgan, oldingi detal tugagan → sikl yopiladi.
- `AWAIT_PART` → `IDLE`/`OFF` — detal ishlovsiz olingan → `completed: false`,
  detal hisobiga qo'shilmaydi.

---

## 4. Fayl tuzilishi

```
firmware/
  config.py    Barcha sozlamalar. Odatda faqat shu fayl tahrirlanadi.
  lamps.py     GPIO o'qish, debounce (50 ms), miltillash aniqlash (2 s oyna).
  fsm.py       Holat mashinasi, kutish eskalatsiyasi, sikl hisobi. ← asosiy mantiq
  scanner.py   UART QR skaner (ixtiyoriy, SCANNER = None bo'lsa o'chiq).
  settings.py  MQTT orqali o'zgartiriladigan va flash'ga saqlanadigan sozlamalar.
  link.py      Wi-Fi + MQTT (faqat Pico W). `network` ni import qiladi!
  link_serial.py  USB-serial transport (Wi-Fi'siz Pico). Bir xil interfeys.
  main.py      Asosiy tsikl. Transportni `cfg.TRANSPORT` bo'yicha tanlaydi.
tests/
  test_fsm.py   FSM ni soxta vaqt bilan sinash (python3 tests/test_fsm.py).
  test_link.py  Bufer/Wi-Fi mantiqi, soxta network + umqtt bilan.
mes/               Vaqtinchalik MES (prototip). Faqat Python stdlib.
  broker.py        MQTT 3.1.1 broker (Mosquitto o'rniga).
  client.py        Sinxron MQTT klient.
  db.py            SQLite sxema + hisobot so'rovlari.
  bridge.py        MQTT → baza, QR skanni siklga bog'lash.
  web.py + ui.html Monitor, operator ekrani, hisobot, sinov paneli.
  server.py        Hammasini bitta jarayonda: python -m mes.server
  serial_bridge.py Pico USB → MQTT ko'prigi (stanokdagi kompyuterda).
  export.py        CSV/JSON chiqarish. Keyinchalik MES PRO ga yozadigan joy.
sim/
  pico_sim.py      Pico simulyatori — haqiqiy fsm.py/lamps.py bilan.
start.py           Ishlab chiqish uchun: qismlarni alohida jarayonlarda ochadi.
app.py             .exe kirish nuqtasi: hammasi bitta jarayonda, oqimlar bilan.
build_exe.py       PyInstaller bilan mustaqil .exe quradi.
tests/
  test_fsm.py      Holat mashinasi.
  test_link.py     Bufer, qayta ulanish (soxta network + umqtt).
  test_bridge.py   MES ko'prigi, QR bog'lanishi, dublikatlar.
  test_serial.py   USB transport: Pico tomoni + ko'prik tomoni.
docs/
  tz.md            ⭐ Texnik topshiriq — asosiy hujjat.
  mes-pro-integration.md  MES PRO muhandislariga so'rov: maydonlar, savollar.
  hardware.md      Ulash sxemasi, detallar ro'yxati, o'rnatish, sinov.
  mes-schema.sql   PostgreSQL jadvallari (ishlab chiqarish uchun).
```

### Ishga tushirish

```bash
python start.py              # MES + USB ko'prik + Chrome (hammasi)
python start.py --sim-demo   # Pico o'rniga simulyator, smena ssenariysi
python start.py --kiosk      # sex monitori uchun to'liq ekran
python start.py --autostart  # kompyuter yoqilganda o'zi ishga tushsin
python stop.py               # hammasini to'xtatish
```

Alohida qismlar kerak bo'lsa:

```bash
python -m mes.server                  # broker + baza + veb (localhost:8080)
python -m mes.serial_bridge           # Pico USB -> MQTT
python sim/pico_sim.py --mode demo    # simulyator
```

### Temirga yuklash (mpremote)

```bash
python -m mpremote connect COM4 fs cp firmware/config.py firmware/lamps.py     firmware/fsm.py firmware/link_serial.py firmware/scanner.py     firmware/settings.py firmware/main.py :
python -m mpremote connect COM4 reset
```

Watchdog tufayli qurilmani ushlash qiyin bo'lsa: yuklanish paytidagi 3 s
oynada Ctrl-C, yoki **GP22 ni GND ga** qisqartirib xavfsiz rejim.

---

## 5. MQTT shartnomasi

Topiklar: `mes/andon/<MACHINE_ID>/{event,state,online,cmd}`

**`event`** — ikki xil xabar, `type` maydoni bilan ajraladi:

```json
{"type": "state", "session": "a3f19c", "seq": 142, "ts": 1757490231,
 "state": "FAULT", "prev_state": "PROCESSING", "prev_duration_s": 90,
 "lamps": {"green":"off","yellow":"off","red":"on"}, "part_id": "QR-8834021",
 "downtime_id": "PRISADKA-01-a3f19c-142", "reason_required": true}
```

```json
{"type": "cycle", "session": "a3f19c", "seq": 143, "ts": 1757490350,
 "part_id": "QR-8834021", "wait_s": 40, "process_s": 120,
 "completed": true, "part_count": 517}
```

- `downtime_id` ni **Pico beradi**. To'xtash tugaganda `closes_downtime_id`
  maydonida o'sha id keladi — MES shu yozuvni yopadi. **Bitta event ikkala
  maydonni ham olib kelishi mumkin** (`STOPPED → FAULT`).
- `ts: 0` → NTP hali sinxronlanmagan, server o'z vaqtini qo'yadi.
- `seq` uzluksiz, lekin faqat bitta `session` ichida. Bo'shliq → xabar yo'qolgan;
  yangi `session` → qurilma qayta yuklangan (seq yana 1 dan boshlanadi).
- `part_count` boot'dan beri hisoblanadi — MES detallarni o'z jadvalidan sanasin.
- `state` topigi retained snapshot (har 30 s), `online` esa LWT (`1`/`0`).

**`cmd`** (MES → Pico): `{"idle_timeout_s": 600}`, `{"idle_timeout_enabled": false}`,
`{"reset_counter": true}`, `{"reboot": true}`.

---

## 6. Ochiq savollar

Bularga javob bo'lmaguncha tegishli kodni "tuzatish" kerak emas:

1. **PLC chiqishi PNP (sourcing) mi, NPN (sinking) mi?** Optopara qutbi shunga bog'liq.
2. **Yashil qanday tezlikda miltillaydi?** Hozirgi kod 2 s oynada ishlaydi
   (`BLINK_WINDOW_MS`). Chiroq 0.5 Hz dan sekin miltillasa, oynani oshirish kerak,
   aks holda miltillash doimiy yoniq deb o'qiladi.
3. ~~QR skaner qayerga ulangan?~~ **Javob olindi:** skaner MES tizimiga
   ulangan, nakleyka o'qilganda ma'lumot MES ga va stanok progasiga parallel
   ketadi. Pico da skaner yo'q → `SCANNER = None`, detal raqamini MES
   `AWAIT_PART` eventiga vaqt bo'yicha bog'laydi (`mes/bridge.py`).
4. **Ishlab chiqarish brokeri.** Prototipda o'zimizning Python broker
   (`mes/broker.py`) ishlaydi. Doimiy ish uchun Mosquitto + PostgreSQL kerak.

---

## 7. Keyingi qadamlar

1. **Temirda sinov** — `docs/tz.md` 12-bo'limdagi qabul sinovlari.
   Undan oldin ikki narsani aniqlash: PLC chiqishi PNP/NPN va miltillash tezligi.
2. **Ishlab chiqarish stegi:** Mosquitto + PostgreSQL. Sxema tayyor
   (`docs/mes-schema.sql`), ko'prik mantiqi `mes/bridge.py` dan ko'chiriladi.
3. **Autentifikatsiya:** prototipda MQTT paroli va veb kirishi yo'q.
4. **Smena bo'yicha hisobot:** hozir 24 soatlik oyna.
5. Ko'p stanok: `MACHINE_ID` ni har bir Pico da o'zgartirish, qolgani bir xil.

---

## 8. Ishlash tartibi

- Kod o'zgartirilsa, to'rttala test ham ishga tushirilsin — **alohida jarayonda**
  (har biri `sys.modules["time"]` ni almashtiradi):
  `python tests/test_fsm.py; python tests/test_link.py;`
  `python tests/test_bridge.py; python tests/test_serial.py`
  Yangi holat qoidasi qo'shilsa, testga ham ssenariy qo'shiladi.
- Firmware mantiqi o'zgarsa, simulyatorda ham tekshirilsin:
  `python -m mes.server` + `python sim/pico_sim.py --mode demo`.
- `config.py` ga real parol/IP yozilgan bo'lsa, uni commit qilmang
  (`.gitignore` da `firmware/config.py` bor, `config.example.py` dan nusxa oling).
- Mantiq o'zgarsa, shu fayldagi 3-bo'lim ham yangilansin — keyingi seans shu
  fayldan boshlanadi.
