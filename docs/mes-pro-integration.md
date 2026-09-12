# MES PRO ga ulanish — texnik so'rov

**Kimga:** MES PRO ni ishlab chiqqan muhandislarga
**Nima uchun:** Prisadka stanogining andon qurilmasi yig'ayotgan ma'lumotni
MES PRO bazasiga yozish kerak.

---

## 1. Qisqacha: nima yig'ilmoqda

Prisadka stanogining signal ustuniga (qizil / sariq / yashil) optopara orqali
ulangan qurilma chiroq holatini soniyaga aniqlik bilan o'qiydi va uchta
ma'lumot oqimini hosil qiladi:

| Oqim | Nima | Kuniga (1 stanok) |
|---|---|---|
| `downtime` | To'xtashlar — boshlanishi, tugashi, davomiyligi, **sababi** | 10–40 qator |
| `part_cycle` | Detal sikllari — kutish va ishlov vaqti, detal QR raqami | ~100 qator |
| `andon_event` | Xom holat o'zgarishlari (tekshirish va tahlil uchun) | 500–800 qator |

Yiliga bitta stanok uchun taxminan **250 ming qator**, hajmi ~50 MB.
Bu MES PRO bazasi uchun sezilarsiz yuk.

Ma'lumot **real vaqtda** keladi (holat o'zgarishi ~1–2 sekundda qayd etiladi),
lekin MES PRO ga yozish partiyalab (masalan har daqiqada) bo'lishi mumkin.

---

## 2. Maydonlar

### 2.1 `downtime` — to'xtashlar (eng muhim oqim)

| Maydon | Turi | Izoh |
|---|---|---|
| `downtime_id` | TEXT(64) | **Birlamchi kalit.** Qurilma beradi: `PRISADKA-01-a3f19c-142` |
| `machine_id` | TEXT(32) | Stanok kodi, masalan `PRISADKA-01` |
| `session` | TEXT(8) | Qurilma yuklanish id si (quyida izoh) |
| `state` | TEXT(16) | `FAULT` (avariya) / `STOPPED` (uzoq kutish) / `OFF` (o'chirilgan) |
| `started_at` | TIMESTAMP | to'xtash boshlangan vaqt |
| `ended_at` | TIMESTAMP NULL | tugagan vaqt; `NULL` = hali davom etmoqda |
| `duration_s` | INT NULL | davomiyligi, soniya |
| `reason_code` | TEXT(32) NULL | sabab kodi; `NULL` = operator hali ko'rsatmagan |
| `reason_name` | TEXT(128) | sabab nomi (o'zbekcha) |
| `reason_category` | TEXT(16) | `TEXNIK` / `XOMASHYO` / `TASHKILIY` / `REJALI` / `SIFAT` |
| `comment` | TEXT NULL | operator izohi |
| `set_by` | TEXT(64) NULL | sababni kim ko'rsatgan |
| `set_at` | TIMESTAMP NULL | qachon ko'rsatilgan |

**Muhim:** yozuv avval `reason_code = NULL` bilan yaratiladi, operator
sababni keyinroq ko'rsatadi va o'sha qator **yangilanadi** (`UPDATE`).
Ya'ni bitta `downtime_id` bo'yicha bir necha marta yozish bo'ladi.

### 2.2 `part_cycle` — detal sikllari

| Maydon | Turi | Izoh |
|---|---|---|
| `machine_id` | TEXT(32) | stanok kodi |
| `session` + `seq` | TEXT(8) + INT | **yagona kalit** `machine_id + session + seq` |
| `ts` | TIMESTAMP | sikl tugagan vaqt |
| `part_id` | TEXT(64) NULL | detal QR raqami (MES dagi skanerdan bog'lanadi) |
| `wait_s` | INT | QR skandan detal stanokka kirgunga qadar |
| `process_s` | INT | sof ishlov vaqti (avariya vaqti kirmaydi) |
| `completed` | BOOL | `false` = detal ishlovsiz olingan |

### 2.3 `andon_event` — xom holat o'zgarishlari

| Maydon | Turi | Izoh |
|---|---|---|
| `machine_id` | TEXT(32) | |
| `session` + `seq` | TEXT(8) + INT | **yagona kalit** `machine_id + session + seq` |
| `ts` | TIMESTAMP | o'tish vaqti |
| `received_at` | TIMESTAMP | server qabul qilgan vaqt |
| `state` | TEXT(16) | `PROCESSING` / `AWAIT_PART` / `IDLE` / `STOPPED` / `FAULT` / `OFF` |
| `prev_state` | TEXT(16) | oldingi holat |
| `prev_duration_s` | INT | oldingi holat necha soniya davom etgan |
| `part_id` | TEXT(64) NULL | |
| `lamps` | TEXT/JSON | chiroqlar holati, masalan `{"red":"off","yellow":"on","green":"off"}` |

Bu oqim majburiy emas — faqat tekshirish va batafsil tahlil uchun. Agar
MES PRO ga faqat `downtime` va `part_cycle` kerak bo'lsa, shu ikkitasi
yetarli.

---

## 3. Ikkita texnik tafsilot

**`session` nima uchun kerak.** Qurilmadagi `seq` hisoblagichi har qayta
yuklanishda 1 dan boshlanadi (quvvat uzilishi, qayta ishga tushirish).
`session` — har yuklanishda yangilanadigan 6 belgili tasodifiy id.
Shu sababli yagona kalit **`machine_id + session + seq`** bo'lishi kerak.
Faqat `seq` bo'yicha kalit qo'yilsa, qayta yuklanishdan keyingi haqiqiy
yozuvlar dublikat deb rad etiladi.

**Takroriy yozish xavfsiz bo'lishi kerak.** Aloqa uzilib qayta ulanganda
bir xil yozuv ikki marta yuborilishi mumkin. Shuning uchun:
`INSERT ... ON CONFLICT DO NOTHING` yoki `MERGE` kerak
(`downtime` uchun esa `ON CONFLICT DO UPDATE` — sabab keyin qo'shiladi).

---

## 4. Bizga kerak bo'lgan javoblar

| № | Savol | Nima uchun muhim |
|---|---|---|
| 1 | MES PRO bazasi qaysi **MBBT** da? (PostgreSQL / MS SQL Server / MySQL / Oracle) | ulanish kutubxonasi va SQL sintaksisi shunga bog'liq |
| 2 | «OYY bo'limi» — bu **sxema** nomimi, **jadval** mi, yoki alohida **modul** mi? Mavjud jadval tuzilishi qanday? | o'z jadvalimizni yaratamizmi yoki mavjudiga yozamizmi |
| 3 | Yozish usuli: **to'g'ridan-to'g'ri SQL**, **saqlangan protsedura**, yoki **REST API**? | |
| 4 | Ulanish ma'lumotlari: server manzili, port, foydalanuvchi, huquqlar (faqat `INSERT`/`UPDATE` yetarli) | |
| 5 | Stanok kodi MES PRO da qanday ataladi? Bizdagi `PRISADKA-01` ga qaysi kod mos keladi? | ma'lumot to'g'ri stanokka bog'lanishi uchun |
| 6 | Detal QR raqami MES PRO da qaysi maydonda saqlanadi? | siklni detalga bog'lash uchun |
| 7 | To'xtash sabablari ro'yxati MES PRO da **bormi**? Bo'lsa, kodlarini bering — biznikini moslaymiz | ikki xil ro'yxat bo'lib qolmasligi uchun |
| 8 | Vaqt zonasi: baza `TIMESTAMP` ni UTC da saqlaydimi yoki mahalliy vaqtda? | |

Eng tez yo'l: **bitta jadval + bitta hisob (login)** bersangiz, biz faqat
`INSERT`/`UPDATE` qilamiz. Qolganini MES PRO o'z ichida ishlaydi.

---

## 5. Namuna fayllar

Haqiqiy ma'lumotdan chiqarilgan namunalarni ko'rish uchun:

```bash
python -m mes.export --days 7 --format csv
```

`eksport/` papkasida uchta fayl hosil bo'ladi (`;` ajratgichli, Excel da
to'g'ri ochiladi). Muhandislarga aynan shu fayllarni ko'rsatish mumkin —
jadval tuzilishi darhol tushunarli bo'ladi.

JSON kerak bo'lsa: `--format json`.

---

## 6. Hozirgi holat

Prototip o'z SQLite bazasiga yig'ayapti va veb-interfeysda ko'rsatyapti
(to'xtashlar ro'yxati, sabab tanlash, availability, Pareto). MES PRO ga
yozish qo'shilganda bu ikkalasi **parallel** ishlaydi:

```
Pico ──► MQTT ──► ko'prik ──┬──► SQLite (o'z ekranimiz, zaxira)
                            └──► MES PRO (asosiy baza)
```

Zaxira nusxa ataylab qoldiriladi: MES PRO vaqtincha yetib bo'lmasa,
ma'lumot yo'qolmaydi va aloqa tiklanganda yuboriladi.
