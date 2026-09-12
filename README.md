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
