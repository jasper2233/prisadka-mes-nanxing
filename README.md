# Prisadka MES — Andon monitor

Prisadka stanogining signal ustunini (24 V DC) o'qib, stanok holatini, to'xtash
vaqtlarini va detal sikllarini MES tizimiga uzatuvchi qurilma va dastur.

```
signal ustuni ──optopara──► Raspberry Pi Pico ──USB──► PrisadkaMES.exe ──► Chrome (MES ekrani)
 qizil/sariq/yashil          (MicroPython)              broker + baza         Telegram bot
```

- **Stanok holati** real vaqtda: ishlov, detal kutish, kutish, avariya, o'chirilgan
- **To'xtashlar** avtomatik qayd etiladi, operator MES ekranida sababini tanlaydi
- **Detal sikllari**: kutish va ishlov vaqti, QR raqami bilan bog'lanadi
- **Hisobot**: availability, to'xtash sabablari Pareto'si, CSV/JSON eksport
- **Telegram**: avariya va to'xtashlar haqida xabar, `/holat`, `/hisobot`
- **Avtozapusk**: sex kompyuteri yoqilganda o'zi ishga tushadi, oynasiz ishlaydi

## Holat modeli

| Signal | Holat | Ma'nosi |
|---|---|---|
| Qizil | `FAULT` | Avariya — sabab talab qilinadi |
| Yashil miltillash | `AWAIT_PART` | QR chek skanerlandi, detal kutilmoqda |
| Yashil doimiy | `PROCESSING` | Detal stanok ichida, ishlov ketmoqda |
| Sariq | `IDLE` | Kutish rejimi |
| Sariq, limitdan uzoq | `STOPPED` | Uzoq kutish — sabab talab qilinadi |
| Hammasi o'chiq | `OFF` | Stanok o'chirilgan — sabab talab qilinadi |

## Tez boshlash

### Sex kompyuteri — bitta .exe

Python o'rnatish shart emas.

1. `PrisadkaMES.exe` ni doimiy papkaga qo'ying, masalan `C:\PrisadkaMES\`
   (fleshkadan turib ishga tushirmang — avtozapusk fleshkaga bog'lanib qoladi).
2. Ikki marta bosing. «Kompyuter yoqilganda ishga tushsinmi?» → **Ha**.
3. Pico ni USB ga ulang — dastur o'zi topadi. Chrome da MES ekrani ochiladi.

Hamma narsa .exe yonida saqlanadi: `mes-data.db` (baza), `logs\prisadka.log`
(jurnal). Ikkinchi marta bosilsa yangi nusxa ochilmaydi — faqat MES ekrani.

| Buyruq | Nima qiladi |
|---|---|
| `PrisadkaMES.exe --status` | ishlayaptimi, avtozapusk, baza va jurnal qayerda |
| `PrisadkaMES.exe --stop` | to'xtatish |
| `PrisadkaMES.exe --install` | avtozapuskni yoqish |
| `PrisadkaMES.exe --uninstall` | avtozapuskni o'chirish va to'xtatish |
| `PrisadkaMES.exe --console` | jurnalni jonli ko'rish oynasi bilan |
| `PrisadkaMES.exe --sim-demo` | Pico'siz sinov: 45 daqiqalik smena ssenariysi |
| `PrisadkaMES.exe --kiosk` | sex monitori uchun to'liq ekran |

.exe ni qurish: `pip install -r requirements-dev.txt` → `python build_exe.py`
→ `dist/PrisadkaMES.exe` (~9 MB).

### Manbadan — Python 3 (3.12 da sinalgan)

```bash
pip install -r requirements.txt
python app.py                # MES + USB ko'prik + Chrome
python app.py --sim-demo     # Pico'siz sinov
```

Brauzerda **http://localhost:8080**:

- **Monitor** — stanok holati, availability, so'nggi hodisalar
- **To'xtashlar** — operator ekrani: sababsiz to'xtashlarga bahona tanlash
- **Detal sikllari**, **Hisobot** — sikllar, QR skanlar, Pareto
- **Sinov paneli** — virtual signal ustuni, QR skan, stanokka buyruq

## Telegram bot

1. @BotFather dan bot oching va tokenni oling.
2. `telegram.example.json` dan nusxa olib, **.exe yoniga** `telegram.json` nomi
   bilan qo'ying va tokenni yozing.
3. Dasturni qayta ishga tushiring, Telegram'da botni ochib **Start** bosing —
   birinchi bosgan odam avtomatik ulanadi. Boshqalar uchun botga `/kod` yozing,
   ular `/start KOD` yuborsin.

Bot yuboradi: avariya, uzoq kutish, stanok o'chdi/yoqildi, aloqa uzildi (ovozli);
tayyor detallar, operator ko'rsatgan sabablar, soatlik hisobot (ovozsiz).
Buyruqlar: `/holat`, `/hisobot`, `/kod`, `/stop`.

> Bitta botni faqat **bitta kompyuter** ishlatishi kerak — aks holda buyruqlar
> aralashib ketadi. Bot bu holatni sezsa, javobda ogohlantiradi.

## Pico ga firmware yuklash

Chiroqlar **GP1 = qizil, GP5 = sariq, GP9 = yashil** pinlariga PC817 optopara
orqali ulanadi. 24 V hech qachon GPIO ga to'g'ridan-to'g'ri ulanmaydi.

```bash
copy firmware\config.example.py firmware\config.py     # sozlamalarni tahrirlang
python -m mpremote connect COM4 fs cp firmware/config.py firmware/lamps.py firmware/fsm.py :
python -m mpremote connect COM4 fs cp firmware/link_serial.py firmware/scanner.py firmware/settings.py :
python -m mpremote connect COM4 fs cp firmware/main.py :
python -m mpremote connect COM4 reset
```

Ulash sxemasi, detallar ro'yxati va qabul sinovlari: [`docs/hardware.md`](docs/hardware.md),
[`docs/tz.md`](docs/tz.md).

## Testlar

Temirsiz, internetsiz. Har biri alohida jarayonda ishga tushiriladi:

```bash
python tests/test_fsm.py        # holat mashinasi
python tests/test_link.py       # Wi-Fi transport, oflayn bufer
python tests/test_bridge.py     # MES ko'prigi, QR navbati
python tests/test_serial.py     # USB transport
python tests/test_telegram.py   # Telegram bot
```

## Tuzilishi

```
app.py                 kirish nuqtasi (.exe ham shu): MES + ko'prik + avtozapusk
build_exe.py           PyInstaller bilan .exe qurish
firmware/              Pico ga yuklanadigan MicroPython kodi
  fsm.py               holat mashinasi — asosiy mantiq
  lamps.py             chiroqlarni o'qish, miltillashni aniqlash
  link_serial.py       USB transport (Wi-Fi'siz Pico)
  link.py              Wi-Fi + MQTT transport (Pico W)
  config.example.py    sozlamalar namunasi
mes/                   MES: MQTT broker, SQLite, veb-interfeys
  bridge.py            MQTT → baza, QR skanni siklga bog'lash
  serial_bridge.py     Pico USB → MQTT
  telegram.py          Telegram bot
  export.py            CSV/JSON eksport
sim/pico_sim.py        Pico simulyatori — haqiqiy firmware kodi bilan
tests/                 testlar
docs/                  texnik topshiriq, ulash sxemasi, PostgreSQL sxemasi
```

## Hujjatlar

| Fayl | Nima bor |
|---|---|
| [`docs/tz.md`](docs/tz.md) | **Texnik topshiriq** — uskuna, mantiq, MQTT shartnomasi, qabul sinovlari |
| [`docs/hardware.md`](docs/hardware.md) | Ulash sxemasi, detallar, o'rnatish |
| [`docs/mes-pro-integration.md`](docs/mes-pro-integration.md) | MES PRO ga ulash uchun so'rov |
| [`docs/mes-schema.sql`](docs/mes-schema.sql) | PostgreSQL jadvallari |
| [`CLAUDE.md`](CLAUDE.md) | Loyiha konteksti, nozik joylar, qabul qilingan qarorlar |

## Maxfiy fayllar

Quyidagilar `.gitignore` da va hech qachon commit qilinmaydi:

- `firmware/config.py` — Wi-Fi paroli va IP manzillar (`config.example.py` dan nusxa oling)
- `telegram.json` — bot tokeni (`telegram.example.json` dan nusxa oling)
- `mes-data.db`, `logs/` — ishlab turgan tizim ma'lumotlari
