# Prisadka MES — Andon monitor

Prisadka stanogining signal ustunini (24 V DC) o'qib, stanok holatini, to'xtash
vaqtlarini va detal sikllarini MQTT orqali MES tizimiga uzatadi.
Raspberry Pi Pico W + MicroPython.

## Tez boshlash

Hech narsa o'rnatish shart emas, faqat Python 3.

```bash
python start.py              # MES + USB ko'prik + Chrome - hammasi
python start.py --sim-demo   # Pico o'rniga simulyator (temirsiz sinov)
python stop.py               # to'xtatish
```

Windows da `start.bat` faylini ikki marta bosish ham kifoya.

## Sex kompyuteri uchun: bitta .exe

Python o'rnatilmagan kompyuterda ishlatish uchun:

```bash
python build_exe.py          # dist/PrisadkaMES.exe (~9 MB)
```

**O'rnatish:** faylni doimiy papkaga qo'ying (masalan `C:\PrisadkaMES\`) va
ikki marta bosing. Birinchi ochilganda «Kompyuter yoqilganda ishga
tushsinmi?» deb so'raydi. Shundan keyin kompyuter har yoqilganda o'zi ishga
tushadi va Chrome da MES ekranini ochadi.

Dastur **oynasiz** ishlaydi — operator tasodifan yopib qo'ya olmaydi.
Hamma narsa .exe yonida: `mes-data.db` (baza), `logs\prisadka.log` (jurnal).

```
PrisadkaMES.exe                 MES + USB ko'prik + Chrome
PrisadkaMES.exe --install       avtozapuskni yoqish va ishga tushirish
PrisadkaMES.exe --uninstall     avtozapuskni o'chirish va to'xtatish
PrisadkaMES.exe --stop          to'xtatish
PrisadkaMES.exe --status        ishlayaptimi, avtozapusk, jurnal qayerda
PrisadkaMES.exe --console       jurnalni jonli ko'rish oynasi bilan
PrisadkaMES.exe --sim-demo      Pico'siz sinash: smena ssenariysi
PrisadkaMES.exe --kiosk         sex monitori uchun to'liq ekran
```

### Telegram

.exe yoniga `telegram.json` qo'ying:

```json
{"token": "BOTFATHER-BERGAN-TOKEN"}
```

Dasturni qayta ishga tushiring va Telegram'da botni ochib **Start** bosing —
birinchi bosgan odam avtomatik ulanadi. Boshqalarni ulash uchun botga `/kod`
yozing va ular `/start KOD` yuborsin.

Bot yuboradi: avariya, uzoq kutish, stanok o'chdi/yoqildi, aloqa uzildi,
tayyor detallar, operator ko'rsatgan sabablar, soatlik hisobot.
Buyruqlar: `/holat`, `/hisobot`, `/kod`, `/stop`.

Ikkinchi marta bosilsa yangi nusxa ochilmaydi — faqat MES ekrani ochiladi.
Avtozapusk Windows'ning foydalanuvchi `Run` bo'limi orqali ishlaydi, admin
huquqi kerak emas.

Keyin brauzerda: **http://localhost:8080**

- **Monitor** — stanok holati, availability, so'nggi hodisalar
- **To'xtashlar** — operator ekrani: sababsiz to'xtashlarga bahona tanlash
- **Sinov paneli** — virtual signal ustuni, QR skan, stanokka buyruq

Qo'lda sinash uchun: `python sim/pico_sim.py --mode manual` — chiroqlarni
sinov panelidagi tugmalardan boshqarasiz.

Haqiqiy Pico ulangan bo'lsa (Wi-Fi'siz plata, USB orqali):

```bash
python -m mes.server                       # MES
python -m mes.serial_bridge                # Pico USB -> MQTT ko'prigi
```

```bash
# testlar (har biri alohida jarayonda)
python tests/test_fsm.py
python tests/test_link.py
python tests/test_bridge.py
python tests/test_serial.py
```

## Hujjatlar

| Fayl | Nima bor |
|---|---|
| **`docs/tz.md`** | **Texnik topshiriq** — uskuna, ulash, mantiq, qabul sinovlari |
| `docs/hardware.md` | Ulash sxemasi, detallar, o'rnatish |
| `docs/mes-schema.sql` | PostgreSQL jadvallari (ishlab chiqarish uchun) |
| `CLAUDE.md` | Loyiha konteksti, qabul qilingan qarorlar |

Firmware'ni Pico ga yuklash: `docs/hardware.md` → 5-bo'lim.

## Holat modeli

| Signal | Holat | Ma'nosi |
|---|---|---|
| Qizil | `FAULT` | Avariya — MES da sabab tanlanadi |
| Yashil miltillash | `AWAIT_PART` | QR skanerlandi, detal kutilmoqda |
| Yashil doimiy | `PROCESSING` | Detalga ishlov berilmoqda |
| Sariq | `IDLE` | Kutish rejimi |
| Sariq, limitdan uzoq | `STOPPED` | O'chiq deb qayd etiladi |
| Hammasi o'chiq | `OFF` | Stanok o'chirilgan — sabab talab qilinadi |

## Tuzilishi

```
docs/tz.md             Texnik topshiriq — asosiy hujjat
CLAUDE.md              Loyiha konteksti — Claude Code shu fayldan boshlaydi
firmware/              Pico ga yuklanadigan MicroPython kodi
  link_serial.py       USB transport (Wi-Fi'siz Pico) | link.py = Wi-Fi (Pico W)
  config.example.py    config.py uchun namuna (parolsiz)
mes/                   Vaqtinchalik MES: MQTT broker, SQLite, veb-interfeys
  serial_bridge.py     Pico USB -> MQTT ko'prigi (Wi-Fi'siz plata uchun)
sim/pico_sim.py        Pico simulyatori — haqiqiy firmware kodi bilan
tests/                 fsm, link, bridge testlari
```

## Ishni davom ettirish

VS Code da loyihani oching va Claude Code panelini ishga tushiring — `CLAUDE.md`
avtomatik o'qiladi. Unda uskuna cheklovlari, domen mantiqi, qabul qilingan
qarorlar va ochiq savollar yozilgan.
