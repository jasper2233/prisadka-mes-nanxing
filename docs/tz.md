# TEXNIK TOPSHIRIQ
## Prisadka stanogi — Andon monitor (Raspberry Pi Pico W)

**Versiya:** 1.0 · **Holat:** prototip sinovga tayyor, temirda sinalmagan

---

## 1. Maqsad

Prisadka (qo'shimcha/additiv) stanogining signal ustunidagi uchta chiroqni
o'qib, stanokning holatini, to'xtash vaqtlarini va detal sikllarini real
vaqtda MES tizimiga uzatish.

Qurilma stanok boshqaruviga **aralashmaydi**: faqat kuzatadi. Stanok
progasiga, PLC ga yoki elektr sxemasiga hech qanday o'zgartirish
kiritilmaydi — chiroq liniyalariga parallel ulanish qilinadi, xolos.

### Nimaga erishiladi

| Ko'rsatkich | Hozir | Qurilmadan keyin |
|---|---|---|
| Stanok qachon to'xtaganini bilish | og'zaki, smena oxirida | soniyaga aniq, real vaqtda |
| To'xtash sababi | qayd etilmaydi | operator MES da tanlaydi, Pareto chiqadi |
| Detal sikli vaqti | o'lchanmaydi | har bir detal uchun kutish + ishlov vaqti |
| Availability (OEE) | hisoblanmaydi | avtomatik, 24 soatlik va smenali |

---

## 2. Tizim arxitekturasi

```
  Signal ustuni (24 V DC)
   ┌─────────┐
   │ ● qizil │──[4.7 kΩ]──┐
   │ ● sariq │──[4.7 kΩ]──┤   PC817          Pico W          Wi-Fi
   │ ● yashil│──[4.7 kΩ]──┤  optopara   ┌──────────┐        ┌────────┐
   └─────────┘            └────────────►│ GP1/5/9   │───────►│  MQTT  │
                                        │  RP2040   │  USB    │ broker │
                                        │           │  yoki   │        │
                                        │           │  Wi-Fi  │        │
        24 V GND ─── (Pico GND ga       │ MicroPython│       └───┬────┘
                      ULANMAYDI)        └──────────┘            │
                                                                 ▼
   QR skaner ───► MES tizimi ◄──────────────────────────── MES backend
   (nakleyka)         │                                    (baza + ekran)
                      └──► stanok progasi (parallel, mavjud yechim)
```

**Muhim:** QR skaner **Pico ga ulanmaydi**. Nakleyka o'qilganda ma'lumot
MES tizimiga va stanok progasiga parallel ketadi (mavjud yechim,
muhandislar shunday qurishgan). Pico detal raqamini bilmaydi — MES uni
`AWAIT_PART` eventiga vaqt bo'yicha bog'laydi (7-bo'lim).
Shuning uchun `config.py` da `SCANNER = None`.

---

## 3. Uskuna talablari

### 3.1 Detallar (bitta stanok uchun)

| Detal | Miqdor | Izoh |
|---|---|---|
| Raspberry Pi Pico | 1 | Wi-Fi'siz → USB transport; Pico W bo'lsa Wi-Fi ham mumkin |
| USB kabel (micro-USB, ekranlangan) | 1 | faqat USB transportda, 3 m gacha |
| PC817 optopara (yoki 4-kanalli opto modul) | 3 | har chiroqqa 1 ta |
| Rezistor 4.7 kΩ / 1 W | 3 | opto LED ga ketma-ket |
| Diod 1N4148 | 3 | opto LED ga teskari parallel (himoya) |
| DC-DC 24 V → 5 V (MP1584 yoki Mean Well DR-15-5) | 1 | Pico VSYS (39-pin) ga |
| DIN korpus + klemmalar | 1 | shkafga o'rnatish |

**Rezistor hisobi:** `R = (24 V − 1.2 V) / 5 mA ≈ 4.5 kΩ` → standart 4.7 kΩ.
Quvvat `I²R ≈ 0.12 W`, lekin isishga zaxira uchun **1 W** oling.

### 3.2 Xavfsizlik — buzib bo'lmaydigan qoidalar

| ❗ | Nima uchun |
|---|---|
| 24 V **hech qachon** to'g'ridan-to'g'ri GPIO ga ulanmaydi | RP2040 maksimum 3.3 V, chip kuyadi |
| Chiroq simi **kesilmaydi**, parallel ulanadi | optopara ~5 mA oladi, chiroq ishlashiga ta'sir qilmaydi |
| 24 V GND Pico GND ga **ulanmaydi** | galvanik izolyatsiya buziladi |
| Shkafda ish oldidan quvvat uziladi (LOTO) | xavfsizlik talabi |

### 3.3 Ulash sxemasi (har bir chiroq uchun)

```
Chiroq signali (+24 V) ──[4.7 kΩ 1W]──► PC817 anod (1)
Chiroq umumiy (0 V)    ─────────────► PC817 katod (2)   (1N4148 teskari parallel)

PC817 kollektor (4) ───────────────► Pico GP1 / GP5 / GP9
PC817 emitter   (3) ───────────────► Pico GND
```

Mantiq: **chiroq yoniq → optopara ochiq → GPIO = 0** (`ACTIVE_LOW = True`).
Pico da ichki pull-up yoqiladi, tashqi rezistor kerak emas.

### 3.4 Pin xaritasi

| GPIO | Chiroq | Holat |
|---|---|---|
| GP1 | qizil | `FAULT` — avariya |
| GP5 | sariq | `IDLE` / `STOPPED` — kutish rejimi |
| GP9 | yashil | miltillasa `AWAIT_PART`, doimiy bo'lsa `PROCESSING` |
| GND (38-pin) | opto emitterlar umumiysi | |
| VSYS (39-pin) | 5 V DC-DC dan | |

Pinlarni o'zgartirish kerak bo'lsa — faqat `config.py` dagi `LAMPS` jadvali
tahrirlanadi, kodga tegilmaydi.

### 3.5 Pico quvvati — chiroqlardan MUSTAQIL bo'lishi shart

Stanok o'chirilganda uchchala chiroq ham o'chadi va aynan shu holat
qayd etilishi kerak. Lekin buni xabar qilish uchun **Pico o'sha paytda
ishlab turishi shart**.

| Quvvat manbai | Stanok o'chganda | Natija |
|---|---|---|
| **USB — stanokdagi kompyuterdan** | Pico ishlaydi | ✅ `OFF` qayd etiladi |
| 24 V DC-DC — doim yoniq turadigan liniyadan | Pico ishlaydi | ✅ `OFF` qayd etiladi |
| 24 V DC-DC — stanok bilan birga o'chadigan liniyadan | Pico ham o'chadi | ❌ `OFF` yuborilmaydi, faqat "aloqa yo'q" ko'rinadi |

Hozirgi yechimda (USB transport) bu shart o'z-o'zidan bajariladi.
Kelajakda Pico W ga o'tilsa, DC-DC ni **stanok kalitidan oldingi**
(doimiy) 24 V liniyaga ulash kerak — aks holda "stanok o'chirilgan"
hodisasi umuman yozilmay qoladi.

### 3.6 Aniqlanishi kerak bo'lgan ikki narsa (o'rnatishdan oldin)

**A. PLC chiqishi PNP (sourcing) mi, NPN (sinking) mi?**
Optopara qutbi shunga bog'liq. NPN bo'lsa opto LED ni teskari ulang yoki
ikkita LED ni qarama-qarshi (bidirectional) qo'ying.
*Tekshirish:* multimetr bilan chiroq yoniq paytda signal simi va 0 V
orasidagi kuchlanishni o'lchang. +24 V bo'lsa — PNP; 0 V ga tortilsa — NPN.

**B. Yashil chiroq qanday tezlikda miltillaydi?**
Bu **dasturga bevosita ta'sir qiladi** (5.3-bo'lim). Sekundomer bilan
10 ta miltillashni sanang va davrni yozing.

| O'lchangan davr | Nima qilinadi |
|---|---|
| 0.5–2 s (0.5–2 Hz) | hech nima, standart sozlama ishlaydi |
| 2 s dan uzun | `BLINK_WINDOW_MS` va `MIN_STATE_MS` oshiriladi |
| 0.2 s dan qisqa | `DEBOUNCE_SAMPLES` kamaytiriladi |

---

## 4. Dasturiy ta'minot

### 4.1 Pico ga yuklanadigan fayllar

`firmware/` papkasidagi yettita fayl (boshqa hech narsa kerak emas):

| Fayl | Vazifasi | Hajmi |
|---|---|---|
| `config.py` | barcha sozlamalar — **odatda faqat shu fayl tahrirlanadi** | ~2 KB |
| `lamps.py` | GPIO o'qish, debounce, miltillash aniqlash | ~2 KB |
| `fsm.py` | holat mashinasi, to'xtash va sikl hisobi | ~6 KB |
| `link_serial.py` | **USB transport** — Wi-Fi'siz Pico uchun | ~4 KB |
| `link.py` | Wi-Fi + MQTT, NTP — faqat Pico W da kerak | ~9 KB |
| `settings.py` | MQTT orqali o'zgartiriladigan sozlamalar (flash) | ~1 KB |
| `scanner.py` | UART QR skaner — **ishlatilmaydi** (`SCANNER = None`) | ~2 KB |
| `main.py` | asosiy tsikl | ~4 KB |

Qo'shimcha: `umqtt.simple` kutubxonasi — **faqat Wi-Fi transportda**
(Thonny → `import mip; mip.install("umqtt.simple")`). USB transportda
hech qanday qo'shimcha kutubxona kerak emas.

### 4.2 Transport — MES ga qanday ulanadi

Ikkita variant bor, `config.py` dagi `TRANSPORT` bilan tanlanadi.

#### `TRANSPORT = "serial"` — USB kabel (Wi-Fi'siz Pico)

```
Pico ──USB──► stanokdagi kompyuter ──► MQTT broker ──► MES
              (mes/serial_bridge.py)
```

Pico eventlarni USB orqali qator-qator yuboradi, kompyuterdagi ko'prik
ularni MQTT ga uzatadi. QR skaner allaqachon o'sha kompyuterga ulangan,
ya'ni **yangi temir kerak emas**.

Sim protokoli (har biri bitta qator):

| Yo'nalish | Format | Izoh |
|---|---|---|
| Pico → kompyuter | `MES event {json}` | holat yoki sikl xabari |
| Pico → kompyuter | `MES state {json}` | retained snapshot |
| kompyuter → Pico | `CMD {json}` | sozlama o'zgartirish |
| kompyuter → Pico | `PING` | har 5 s, "men tirikman" |

Boshqa har qanday qator (`print`, traceback) ko'prik tomonidan jurnal deb
qabul qilinadi — shuning uchun disk raskadrovka chiqishini o'chirish shart emas.

**Onlayn/oflayn.** USB CDC ga yozilgan ma'lumot, agar hech kim o'qimasa,
jimgina yo'qoladi. Shuning uchun Pico "onlayn" ni `PING` bo'yicha aniqlaydi:
15 sekund ovoz chiqmasa oflayn deb hisoblaydi va eventlarni buferga yig'adi.
Kabel qayta ulanganda hammasi ketma-ket yuboriladi.

**Vaqt.** NTP yo'q → eventlar `ts: 0` bilan ketadi → vaqtni MES qo'yadi.
Bu shartnomada allaqachon ko'zda tutilgan.

**Kamchiligi.** Kompyuter o'chsa yoki qotib qolsa, qayd to'xtaydi (Pico
buferi to'lguncha saqlaydi — 200 ta event).

Ishga tushirish (stanokdagi kompyuterda):

```bash
python -m mes.serial_bridge --machine PRISADKA-01 --host <BROKER-IP>
python -m mes.serial_bridge --list       # portlar ro'yxati
```

#### `TRANSPORT = "wifi"` — to'g'ridan-to'g'ri MQTT (faqat Pico W)

Pico W broker'ga o'zi ulanadi, oraliq kompyuter kerak emas. Qolgan mantiq
bir xil. Wi-Fi'siz Pico da bu variant tanlansa, `network` moduli topilmay
xato beradi.

### 4.3 Asosiy tsikl

Har ~2 ms da quyidagilar bajariladi:

```
1. wdt.feed()                    watchdog boqiladi (8 s limit)
2. har 10 ms:  chiroqlarni o'qish → debounce → holat mashinasi
3. har 30 s:   retained snapshot yuborish (heartbeat)
4. tarmoq:     MQTT pump — ulanish, buyruq qabul qilish, navbatni bo'shatish
5. LED:        doimiy = onlayn, miltillash = tarmoq yo'q
```

**Qattiq qoida:** asosiy tsiklda 1–2 sekunddan uzoq bloklovchi chaqiruv
bo'lmasligi kerak. Wi-Fi ulanishi holat mashinasi ko'rinishida yozilgan,
MQTT soketida 2 s timeout bor (8 s / 3 bosqich), NTP o'z timeouti bilan.

---

## 5. Holat mashinasi — asosiy mantiq

### 5.1 Signal → holat

| Signal | Holat | Ma'nosi |
|---|---|---|
| Qizil (yoniq **yoki** miltillash) | `FAULT` | Avariya. MES da **sabab tanlanishi shart** |
| Yashil **miltillash** | `AWAIT_PART` | QR chek skanerlandi, detal stanokka solinishi kutilmoqda |
| Yashil **doimiy** | `PROCESSING` | Detal stanok ichida, ishlov (obrabotka) ketmoqda |
| Sariq | `IDLE` | Kutish rejimi — hech qanday chek skanerlanmagan |
| Sariq, limitdan uzoq | `STOPPED` | **O'chiq** deb qayd etiladi, sabab talab qilinadi |
| **Hammasi o'chiq** | `OFF` | **Stanok o'chirilgan** — sabab talab qilinadi |

**Prioritet: qizil > yashil > sariq.** Ikki chiroq birga yonsa, yuqoridagisi
g'olib chiqadi.

### 5.2 Kutish limiti (IDLE → STOPPED)

Sariq chiroq `idle_timeout_s` (standart **900 s = 15 daqiqa**) dan uzoq
uzluksiz yonsa, holat avtomatik `IDLE` dan `STOPPED` ga o'tadi va to'xtash
yozuvi ochiladi.

Limit ikki joydan boshqariladi:
- `config.py` → `IDLE_TIMEOUT_S` (boshlang'ich qiymat);
- MQTT `cmd` topigi → `{"idle_timeout_s": 600}` (ishlab turgan holda,
  `settings.json` ga saqlanadi, reboot'dan keyin ham qoladi).

### 5.3 Vaqt parametrlari — nima uchun shunday

| Parametr | Qiymat | Sababi |
|---|---|---|
| `SAMPLE_MS` | 10 ms | chiroqni o'qish davri |
| `DEBOUNCE_SAMPLES` | 5 (= 50 ms) | kontakt shovqinini filtrlash |
| `BLINK_WINDOW_MS` | 2000 ms | shu oynada 2+ o'zgarish bo'lsa — "miltillash" |
| `MIN_STATE_MS` | **1200 ms** | ⚠ quyidagi izohga qarang |
| `MIN_PROCESS_MS` | 5000 ms | bundan qisqa "ishlov" detal deb sanalmaydi |
| `OFF_CONFIRM_MS` | 5000 ms | "hammasi o'chiq" shuncha turishi kerak — quyidagi izoh |
| `HEARTBEAT_S` | 30 s | retained snapshot davri |

> ⚠ **`MIN_STATE_MS` miltillashning yarim davridan katta bo'lishi SHART.**
>
> Yashil chiroq miltillay boshlaganda birinchi yarim davr **doimiy yoniq**
> bo'lib ko'rinadi — `lamps.py` ikkita qirra ko'rmaguncha "miltillash" deb
> ayta olmaydi. Agar `MIN_STATE_MS` kichik bo'lsa, o'sha soxta
> `PROCESSING` qayd etiladi va **har QR skanda bitta ortiqcha detal
> sanaladi**. Bu xato simulyatsiyada aniqlangan va tuzatilgan.
>
> `BLINK_WINDOW_MS = 2000` → aniqlanadigan eng sekin miltillash yarim davri
> 1000 ms → `MIN_STATE_MS = 1200`. Miltillash sekinroq bo'lsa, ikkalasini
> ham mutanosib oshiring.

> ⚠ **`OFF_CONFIRM_MS` nima uchun kerak.** PLC bir chiroqni o'chirib
> ikkinchisini yoqguncha oraliqda **hamma chiroq o'chiq** bo'lib qolishi
> mumkin. Bu "stanok o'chdi" emas — shunchaki o'tish pallasi. Shu sababli
> `OFF` boshqa holatlardan farqli ravishda 5 sekund tasdiqlanadi.
> Agar stanokda bu palla 5 sekunddan uzoq bo'lsa, qiymatni oshiring.

Oqibati: holat o'zgarishi ~1.2 s kechikish bilan xabar qilinadi.
Davomiyliklar esa **aniq** qoladi — hisob commit paytidan emas, o'tish
ro'y bergan paytdan olinadi.

---

## 6. To'xtash yozuvi (downtime)

`FAULT`, `STOPPED` va `OFF` — sabab talab qiladigan holatlar.

`OFF` (uchchala chiroq ham o'chiq) stanok o'chirilganini bildiradi. Smena
tugadimi, elektr uzildimi, rejali ta'mirmi — buni faqat odam ayta oladi,
shuning uchun MES da sabab so'raladi. Sabablar ro'yxati holatga qarab
filtrlanadi: `OFF` uchun "Smena tugadi", "Elektr uzilishi", "Rejali ta'mir"
chiqadi, "Xomashyo tugadi" esa chiqmaydi.

- To'xtash **boshlanganda**: eventda `downtime_id` + `reason_required: true`.
- To'xtash **tugaganda**: eventda `closes_downtime_id` (o'sha id) va
  `prev_duration_s` (davomiyligi).

**`downtime_id` formati:** `<MACHINE_ID>-<session>-<seq>`,
masalan `PRISADKA-01-a3f19c-142`.

`session` — har yuklanishda yangilanadigan tasodifiy 6 belgili id.
U shuning uchun kerakki, `seq` qayta yuklanishdan keyin 1 dan boshlanadi:
sessiyasiz id lar to'qnashib, eski yozuvlar ustiga tushardi.

> **Muhim qoida MES uchun:** bitta event ikkala maydonni ham olib kelishi
> mumkin. `STOPPED → FAULT` o'tishida event eski `STOPPED` yozuvini yopadi
> **va** yangi `FAULT` yozuvini ochadi. Ikkala maydon ham tekshirilishi shart.

---

## 7. Detal sikli va QR bog'lanishi

```
QR nakleyka o'qildi → yashil miltillaydi → yashil doimiy → keyingi QR
                      └──── wait_s ─────┘  └─ process_s ─┘

Ishlov paytida keyingi chek skanerlansa, chiroq doimiy yashil qolaveradi;
ishlov tugashi bilan DARHOL miltillashga o'tadi:

  [ishlov: detal A] ... chek B o'qildi ... [ishlov tugadi] → miltillash (B kutilmoqda)

Hech narsa skanerlanmagan bo'lsa, ishlov tugagach SARIQ yonadi (kutish rejimi).
```

| Maydon | Ma'nosi |
|---|---|
| `wait_s` | QR skandan ishlov boshlanguncha o'tgan vaqt |
| `process_s` | sof ishlov vaqti (avariya vaqti kirmaydi) |
| `completed` | `true` — detal ishlandi; `false` — ishlovsiz olindi |

**Sikl yopilish qoidalari:**

| O'tish | Nima bo'ladi |
|---|---|
| `PROCESSING → FAULT` | sikl **uzilmaydi**, ishlov vaqti saqlanadi, avariyadan keyin davom etadi |
| `PROCESSING → AWAIT_PART` | yangi QR keldi → oldingi detal tugadi, sikl yopiladi |
| `AWAIT_PART → IDLE/OFF` | detal ishlovsiz olindi → `completed: false`, hisobga kirmaydi |

### 7.1 Detal raqamini bog'lash (MES tomonida)

Pico detal raqamini bilmaydi. MES quyidagicha bog'laydi:

1. QR nakleyka o'qilganda MES `part_scan` jadvaliga yozadi
   (`machine_id`, `part_id`, `scanned_at`). Bu **navbat**.
2. Pico dan `AWAIT_PART` eventi kelganda MES navbatdan eng **ESKI**
   bog'lanmagan skanni oladi (FIFO) va uni "joriy detal" qiladi.
3. Keyingi `cycle` xabari yopilayotgan detalga tegishli bo'ladi.
4. `PROCESSING/AWAIT_PART → IDLE/STOPPED/OFF` (sariq yondi) — stanokning
   o'zi "navbatda detal yo'q" deb aytmoqda. Qolgan bog'lanmagan skanlar
   **eskirgan** deb belgilanadi.

**Nima uchun FIFO va nima uchun oyna uzun.** Operator ishlov ketayotgan
paytda keyingi detalning chekini skanerlab qo'yishi mumkin — chiroq doimiy
yashil bo'lib turaveradi, ishlov tugashi bilan darhol miltillashga o'tadi.
Ya'ni skan `AWAIT_PART` dan bir necha daqiqa oldin bo'lishi mumkin, shuning
uchun oyna 4 soat (bir smena). Ikki detal navbatga qo'yilsa, birinchi
skanerlangani birinchi ishlanadi — shuning uchun FIFO.

**4-qadam nima uchun kerak.** Chek o'qilgan-u detal stanokka solinmagan
bo'lsa (operator fikridan qaytdi, detal brak chiqdi), o'sha skan navbatda
qolib, keyingi detalga noto'g'ri yopishardi va butun hisob bir qadamga
siljirdi. Sariq chiroq buni o'zi-o'zidan to'g'rilaydi.

> **Nozik jihat:** yangi QR (`AWAIT_PART`) oldingi siklning `cycle`
> xabaridan **oldin** keladi. Shuning uchun MES eski detalni alohida
> saqlashi kerak (`closing_part_id`), aks holda har sikl bitta keyingi
> detal raqamini olib, hisob siljib ketadi. Bu xato prototipda aniqlangan
> va tuzatilgan (`mes/bridge.py`, `tests/test_bridge.py`).

---

## 8. MQTT shartnomasi

**Topiklar:** `mes/andon/<MACHINE_ID>/{event,state,online,cmd}`

### 8.1 `event` — ikki xil xabar, `type` maydoni bilan ajraladi

Holat o'zgarishi:
```json
{"type": "state", "machine_id": "PRISADKA-01", "site": "SEX-1",
 "session": "a3f19c", "seq": 142, "ts": 1757490231,
 "state": "FAULT", "prev_state": "PROCESSING", "prev_duration_s": 90,
 "lamps": {"green":"off","yellow":"off","red":"on"}, "part_id": null,
 "downtime_id": "PRISADKA-01-a3f19c-142", "reason_required": true}
```

Detal sikli:
```json
{"type": "cycle", "machine_id": "PRISADKA-01", "site": "SEX-1",
 "session": "a3f19c", "seq": 143, "ts": 1757490350, "part_id": null,
 "wait_s": 40, "process_s": 120, "completed": true, "part_count": 517}
```

### 8.2 Qoidalar

- `ts: 0` → NTP hali sinxronlanmagan, **server o'z vaqtini qo'yadi**.
- `seq` uzluksiz, lekin faqat bitta `session` ichida. Bo'shliq → xabar
  yo'qolgan; yangi `session` → qurilma qayta yuklangan.
- Yagona kalit: **(machine_id, session, seq)**. Takroriy xabar shu kalit
  bo'yicha e'tiborsiz qoldiriladi.
- `part_count` boot'dan beri hisoblanadi va reboot'da nollanadi — MES
  detallarni o'z jadvalidan sanasin.
- QoS 0. Ishonchlilik `seq` va oflayn bufer orqali ta'minlanadi.

### 8.3 `state` — retained snapshot (har 30 s)

Joriy holat, detal soni, sozlamalar, navbat uzunligi, RSSI, uptime.
Retained bo'lgani uchun MES qayta ishga tushganda darhol oxirgi holatni oladi.

### 8.4 `online` — LWT

`1` = ulangan (retained), `0` = uzilgan. Broker Last Will orqali
avtomatik qo'yadi — Pico quvvatsiz qolsa ham MES biladi.

### 8.5 `cmd` (MES → Pico)

| Buyruq | Ta'siri |
|---|---|
| `{"idle_timeout_s": 600}` | kutish limitini o'zgartirish (30…86400 s) |
| `{"idle_timeout_enabled": false}` | eskalatsiyani o'chirish (sariq doim IDLE) |
| `{"reset_counter": true}` | detal hisoblagichini nollash |
| `{"reboot": true}` | qurilmani qayta yuklash |

Birinchi ikkitasi `settings.json` ga saqlanadi va reboot'dan keyin ham qoladi.

---

## 9. Ishonchlilik talablari

| Vaziyat | Qurilma xatti-harakati |
|---|---|
| Wi-Fi yo'qoldi | eventlar RAM buferiga yig'iladi (200 ta), tarmoq qaytganda ketma-ket yuboriladi |
| Broker javob bermayapti | eksponensial backoff 1 s → 30 s, soketda 2 s timeout |
| Bufer to'ldi | eng eski event tashlanadi, `dropped` hisoblagichi oshadi (snapshotda ko'rinadi) |
| Dastur osib qoldi | 8 s watchdog qurilmani qayta yuklaydi |
| Qayta yuklandi | yangi `session` id, `seq` 1 dan — MES yozuvlari to'qnashmaydi |
| NTP yo'q | eventlar `ts: 0` bilan ketadi, server o'z vaqtini qo'yadi — ishlash to'xtamaydi |
| Quvvat uzildi | yuborilmagan bufer yo'qoladi (stanok ham o'chgan — odatda muhim emas) |

**DNS ishlatilmaydi.** `MQTT_HOST` ham, `NTP_HOST` ham faqat IP bo'lishi
shart — DNS so'rovi soketni bloklab, watchdog reset'ga olib keladi.

---

## 10. Sozlamalar (`config.py`)

| Guruh | Parametr | Standart | Izoh |
|---|---|---|---|
| Transport | `TRANSPORT` | `serial` | `serial` = USB, `wifi` = Pico W |
| Identifikator | `MACHINE_ID` | `PRISADKA-01` | har stanokda **noyob** |
| | `SITE` | `SEX-1` | sex/uchastka |
| Wi-Fi | `WIFI_SSID`, `WIFI_PASS` | — | sex tarmog'i |
| MQTT | `MQTT_HOST` | — | **faqat IP** |
| | `MQTT_PORT` | 1883 | |
| | `MQTT_SOCKET_TIMEOUT_S` | 2 | 8 s watchdog / 3 bosqich |
| Pinlar | `LAMPS` | GP1/GP5/GP9 | `(nom, gpio)` juftliklari |
| | `ACTIVE_LOW` | `True` | chiroq yoniq → GPIO 0 |
| Vaqt | `IDLE_TIMEOUT_S` | 900 | sariq → STOPPED |
| | `MIN_STATE_MS` | 1200 | miltillash yarim davridan katta |
| | `MIN_PROCESS_MS` | 5000 | detal sanash chegarasi |
| | `BLINK_WINDOW_MS` | 2000 | miltillash oynasi |
| Tarmoq | `BUFFER_MAX` | 200 | oflayn navbat (RAM) |
| | `HEARTBEAT_S` | 30 | snapshot davri |
| NTP | `NTP_HOST` | `= MQTT_HOST` | MES serveri NTP ham bersin |

Ko'p stanok uchun: faqat `MACHINE_ID` o'zgaradi, qolgan hammasi bir xil.

---

## 11. O'rnatish tartibi

1. MicroPython proshivkasi: BOOTSEL tugmasini bosib USB ga ulang, ochilgan
   diskka `.uf2` faylni ko'chiring.
   • Wi-Fi'siz Pico → `RPI_PICO` build • Pico W → `RPI_PICO_W` build
2. Faqat Wi-Fi transportda: `import mip; mip.install("umqtt.simple")`.
3. `config.example.py` dan `config.py` yaratib, to'ldirish:
   `TRANSPORT`, `MACHINE_ID`, pinlar, kutish limiti (+ Wi-Fi/MQTT IP).
4. Fayllarni Pico ga ko'chirish (`mpremote cp firmware/*.py :`).
   USB transportda `link.py` kerak emas, Wi-Fi da `link_serial.py` kerak emas.
5. Shkafda quvvatni uzib (LOTO), optoparalarni chiroq liniyalariga parallel
   ulash va Pico ni DIN korpusga o'rnatish.

> **Xavfsiz yuklanish.** Watchdog yoqilgandan keyin qurilmani to'xtatib qayta
> dasturlash qiyinlashadi. Shuning uchun `main.py` boshida 3 sekundlik oyna
> bor (LED miltillab turadi): shu paytda Ctrl-C bosilsa REPL ga chiqiladi.
> Umuman ishga tushirmaslik uchun **GP22 ni GND ga** qisqartiring — qurilma
> "xavfsiz rejim" deb yozadi va `main.py` ishlamaydi.
6. Quvvat berish. Onboard LED:
   **doimiy yonadi** → MQTT ga ulangan; **miltillaydi** → tarmoq yo'q.
7. `mosquitto_sub -h <BROKER-IP> -t 'mes/andon/#' -v` bilan eventlarni kuzatish.

---

## 12. Qabul sinovlari

Har bir qator temirda tekshirilib, natija yozilishi kerak.

### 12.1 Elektr qismi

| # | Sinov | Kutilgan natija | ✓ |
|---|---|---|---|
| E1 | Chiroqlar yoniq/o'chiq holatda GPIO kuchlanishi | yoniq → 0 V, o'chiq → 3.3 V | |
| E2 | Pico o'chirilgan holda stanok ishlashi | chiroqlar odatdagidek ishlaydi | |
| E3 | 24 V va Pico GND orasida izolyatsiya | uzilish (∞ Ω) | |
| E4 | DC-DC chiqishi | 5.0 ± 0.25 V, yuk ostida barqaror | |

### 12.2 Holat mashinasi

| # | Amal | Kutilgan holat | ✓ |
|---|---|---|---|
| S1 | Yashil doimiy yoqish | `PROCESSING` | |
| S2 | Yashil miltillatish | `AWAIT_PART` (1–2 s ichida) | |
| S3 | Sariq yoqish | `IDLE` | |
| S4 | Sariqni limitdan uzoq ushlash | `STOPPED` + `downtime_id` | |
| S5 | Qizil yoqish | `FAULT` + `downtime_id` | |
| S6 | Qizilni o'chirish | `closes_downtime_id` o'sha id bilan | |
| S7 | `STOPPED` ustidan qizil yoqish | bitta eventda eskisi yopiladi, yangisi ochiladi | |
| S8 | Hammasini o'chirish (5 s dan uzoq) | `OFF` + `downtime_id`, sabab so'raladi | |
| S8b | Bir chiroqni o'chirib, 2–3 s dan keyin boshqasini yoqish | `OFF` qayd etilmasligi kerak | |
| S8c | Stanokni o'chirib, Pico ni USB da qoldirish | `OFF` yozuvi ochiladi (3.5-bo'lim) | |
| S9 | 0.2 s lik qisqa qizil | event **bo'lmasligi** kerak | |

### 12.3 Detal hisobi

| # | Amal | Kutilgan natija | ✓ |
|---|---|---|---|
| D1 | To'liq sikl (QR → miltillash → doimiy → yangi QR) | 1 ta `cycle`, `completed: true` | |
| D2 | `wait_s` va `process_s` | sekundomer bilan ±2 s farq | |
| D3 | Ishlov o'rtasida avariya | sikl uzilmaydi, ishlov vaqti qo'shiladi | |
| D4 | 10 ta detal ketma-ket | MES da roppa-rosa 10 ta, ortiqchasi yo'q | |
| D5 | Miltillashni QR siz yoqib-o'chirish | ortiqcha detal sanalmasligi kerak | |

### 12.4 Tarmoq va ishonchlilik

| # | Amal | Kutilgan natija | ✓ |
|---|---|---|---|
| N1 | Wi-Fi ni 5 daqiqaga o'chirish | eventlar buferga yig'iladi, LED miltillaydi | |
| N2 | Wi-Fi ni qaytarish | barcha eventlar ketma-ket keladi, `seq` da bo'shliq yo'q | |
| N3 | Broker ni to'xtatish/yoqish | qurilma o'zi qayta ulanadi (≤30 s) | |
| N4 | Pico quvvatini uzish | MES da `online: 0` 1–2 daqiqada | |
| N8 | USB kabelni sug'urib olish | ko'prik `online: 0` qo'yadi, Pico buferga yig'adi | |
| N9 | Kabelni qaytadan ulash | buferdagi eventlar ketma-ket keladi, `seq` uzluksiz | |
| N10 | Ko'prikni to'xtatib, qayta yoqish | Pico 15 s ichida oflayn → onlayn bo'ladi | |
| N5 | Qurilmani qayta yoqish | yangi `session`, eski yozuvlar buzilmaydi | |
| N6 | 24 soat uzluksiz ishlash | reset bo'lmasligi (`uptime_s` uzluksiz o'sadi) | |
| N7 | MQTT `cmd` bilan limitni o'zgartirish | snapshotda yangi qiymat, reboot'dan keyin ham qoladi | |

### 12.5 MES tomoni

| # | Amal | Kutilgan natija | ✓ |
|---|---|---|---|
| M1 | To'xtash yuz berdi | operator ekranida sababsiz yozuv paydo bo'ladi | |
| M2 | Operator sabab tanladi | yozuv ro'yxatdan chiqadi, Pareto ga tushadi | |
| M3 | Izoh majburiy sabab | izohsiz saqlash rad etiladi | |
| M4 | QR skan + sikl | detal raqami to'g'ri siklga bog'lanadi | |
| M5 | Availability hisobi | qo'lda hisoblangan qiymat bilan mos | |

---

## 13. Prototip stendi (temirsiz sinov)

Loyihada to'liq ishlaydigan sinov muhiti bor — Pico kelmasdan oldin ham
butun zanjirni tekshirish mumkin. Tashqi dastur o'rnatish talab qilinmaydi
(faqat Python 3).

```bash
python -m mes.server                    # MQTT broker + baza + veb (http://localhost:8080)
python sim/pico_sim.py --mode demo      # 45 daqiqalik smena, 120x tezlikda
python sim/pico_sim.py --mode manual    # chiroqlarni MES ekranidan boshqarish
```

Simulyator **haqiqiy firmware kodini** ishlatadi (`fsm.py`, `lamps.py`
o'zgarishsiz), faqat GPIO va tarmoq qatlami almashtiriladi. Shu sababli
bu yerda topilgan xato temirda ham bo'lardi — 5.3-bo'limdagi miltillash
muammosi aynan shunday aniqlangan.

Testlar:
```bash
python tests/test_fsm.py       # holat mashinasi
python tests/test_link.py      # bufer va qayta ulanish
python tests/test_bridge.py    # MES ko'prigi, QR bog'lanishi
```

---

## 14. Ochiq savollar va cheklovlar

### Hal qilinishi kerak

1. **PLC chiqishi PNP mi, NPN mi** (3.5-A bo'lim) — optopara qutbi shunga bog'liq.
2. **Miltillash tezligi** (3.5-B bo'lim) — `MIN_STATE_MS` shunga sozlanadi.
3. **Ishlab chiqarish brokeri:** prototipdagi Python broker sinov uchun.
   Doimiy ish uchun **Mosquitto** o'rnatilishi kerak.
5. **Stanokdagi kompyuter uxlab qolishi** (USB transport uchun eng jiddiy
   xavf). Ma'lumotga ko'ra kompyuterga uzoq tegilmasa o'chadi. U holda
   ko'prik ham to'xtaydi va qayd yo'qoladi. Uchta yechim:

   | Yechim | Ijobiy | Salbiy |
   |---|---|---|
   | Uyquni o'chirish (`powercfg /change standby-timeout-ac 0`) | bepul, 1 daqiqa ish | IT siyosatiga zid bo'lishi mumkin |
   | Pico buferiga tayanish | hech nima qilinmaydi | 200 event (~bir necha soat), keyin eng eskisi yo'qoladi |
   | **Pico W ga o'tish** | kompyuterga umuman bog'liq emas | yangi plata kerak (~80-100 ming so'm) |

   Qaror qabul qilinmaguncha USB transport faqat sinov uchun ishlatilsin.
6. **MES PRO bazasiga yozish.** Prototip o'z SQLite bazasiga yig'ayapti.
   Muhandislarga beriladigan so'rov va namuna fayllar tayyor:
   `docs/mes-pro-integration.md` + `python -m mes.export`.
4. **Baza:** prototip SQLite da. Ishlab chiqarishga PostgreSQL
   (`docs/mes-schema.sql` tayyor).

### Cheklovlar

- Oflayn bufer RAM da — quvvat uzilsa yuborilmagan xabarlar yo'qoladi.
  Kerak bo'lsa `link.py` ga flash'ga yozish qo'shiladi.
- Holat o'zgarishi ~1.2 s kechikish bilan xabar qilinadi (miltillashni
  aniqlash uchun zarur). Davomiyliklar aniq qoladi.
- `blink → doimiy` o'tishi ~2 s kechikish bilan tan olinadi
  (`BLINK_WINDOW_MS` tufayli).
- Qurilma faqat kuzatadi — stanokni to'xtata olmaydi va boshqara olmaydi.
