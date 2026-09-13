# Uskuna: ulash, o'rnatish, sinov

## 1. Ehtiyot choralari

| ❗ | Nima uchun |
|---|---|
| 24 V ni **hech qachon** to'g'ridan-to'g'ri GPIO ga ulamang | RP2040 maksimum 3.3 V. Chip kuyadi. |
| Chiroq simini **kesmang**, parallel ulang | Optopara ~5 mA oladi, chiroq ishlashiga ta'sir qilmaydi. |
| 24 V GND ni Pico GND ga ulamang | Galvanik izolyatsiya buziladi. |
| Shkafda ish qilishdan oldin quvvatni uzing (LOTO) | Xavfsizlik talabi. |

## 2. Detallar

| Detal | Miqdor | Izoh |
|---|---|---|
| Raspberry Pi Pico (RP2040) | 1 | Bizdagi plata Wi-Fi'siz → USB transport |
| USB kabel (micro-USB, ekranlangan) | 1 | stanokdagi kompyuterga, 3 m gacha |
| PC817 optopara (yoki 4-kanalli opto modul) | 3 | Har chiroqqa 1 ta |
| Rezistor 4.7 kΩ / 1 W | 3 | Opto LED ga ketma-ket |
| Diod 1N4148 | 3 | Opto LED ga teskari parallel |
| DC-DC 24 V → 5 V (MP1584 / Mean Well DR-15-5) | 0–1 | faqat USB'siz variantda — 4a-bo'limga qarang |
| DIN korpus + klemmalar | 1 | Shkafga o'rnatish |

**Rezistor hisobi:** `R = (24 − 1.2) / 5 mA ≈ 4.5 kΩ` → 4.7 kΩ.
Quvvat `I²R ≈ 0.12 W` → **1 W** rezistor oling (isishga zaxira).

## 3. Ulash

Har bir chiroq liniyasi uchun:

```
Chiroq signali (+24 V) ──[4.7 kΩ 1W]──► PC817 anod (1)
Chiroq umumiy (0 V)    ─────────────► PC817 katod (2)   (1N4148 teskari parallel)

PC817 kollektor (4) ───────────────► Pico GP1 / GP5 / GP9
PC817 emitter   (3) ───────────────► Pico GND
```

- Chiroq **yoniq** → opto ochiladi → GPIO = **0** (`ACTIVE_LOW = True`).
- PLC chiqishi **NPN (sinking)** bo'lsa opto qutbini teskari ulang, yoki ikkita
  opto LED'ni qarama-qarshi (bidirectional) qo'ying.
- Tayyor 4-kanalli opto modul ishlatsangiz: chiqish tomoniga **3.3 V** bering, 5 V emas.

Pin xaritasi: **GP1 = qizil, GP5 = sariq, GP9 = yashil** (`config.py` da o'zgartiriladi).

## 4. QR skaner

Ikki variant:

1. **Skaner MES kompyuteriga ulangan** (odatiy) — `config.py` da `SCANNER = None`.
   MES skan vaqtini Pico ning `AWAIT_PART` eventiga vaqt bo'yicha bog'laydi.
2. **Skaner Pico ga ulangan** (TTL/RS232 chiqishli) — detal raqami eventga
   to'g'ridan-to'g'ri qo'shiladi:
   ```python
   SCANNER = {"uart": 0, "tx": 0, "rx": 1, "baud": 9600}
   ```
   Skaner chiqishi 3.3 V TTL bo'lishi kerak. RS232 (±12 V) bo'lsa MAX3232 kerak.

## 4a. Pico quvvati — chiroqlardan MUSTAQIL bo'lishi shart

Stanok o'chirilganda uchchala chiroq ham o'chadi va aynan shu holat
`OFF` deb qayd etilishi kerak. Buni xabar qilish uchun **Pico o'sha paytda
ishlab turishi shart**.

| Quvvat manbai | Stanok o'chganda | Natija |
|---|---|---|
| **USB — stanokdagi kompyuterdan** (hozirgi yechim) | Pico ishlaydi | ✅ `OFF` qayd etiladi |
| 24 V DC-DC — doim yoniq liniyadan | Pico ishlaydi | ✅ qayd etiladi |
| 24 V DC-DC — stanok bilan birga o'chadigan liniyadan | Pico ham o'chadi | ❌ hech narsa yozilmaydi |

> **Diqqat:** ba'zi kompyuterlar uyqu rejimida USB portlarni ham o'chiradi.
> U holda Pico qayta yuklanadi va buferdagi xabarlar yo'qoladi. Kompyuterda
> uyquni o'chiring (`powercfg /change standby-timeout-ac 0`) yoki Pico ni
> tashqi quvvatli USB-hub orqali ulang.

## 5. O'rnatish

1. **MicroPython proshivkasi.** BOOTSEL tugmasini bosib turib USB ga ulang —
   `RPI-RP2` nomli disk ochiladi, `.uf2` faylni o'sha diskka ko'chiring:
   Wi-Fi'siz Pico → `RPI_PICO` build; Pico W → `RPI_PICO_W` build
   (micropython.org/download). Plata o'zi qayta yuklanib, COM port bo'lib
   ko'rinadi.
2. **Faqat Wi-Fi variantida** MQTT kutubxonasi kerak
   (USB transportda qo'shimcha kutubxona kerak emas):
   ```python
   import mip
   mip.install("umqtt.simple")
   ```
3. `firmware/config.example.py` dan `config.py` yarating va to'ldiring:
   `TRANSPORT` (`serial` yoki `wifi`), `MACHINE_ID`, pinlar, kutish limiti.
   Wi-Fi variantida qo'shimcha: SSID/parol, `MQTT_HOST`.
   **DNS nomi yozmang** — na MQTT, na NTP uchun, faqat IP: nom so'rovi
   soketni bloklab, watchdog reset'ga olib keladi.
4. Fayllarni Pico ga ko'chiring (`mpremote`). USB transportda `link.py`
   kerak emas; Wi-Fi variantida esa `link_serial.py` kerak emas:
   ```
   python -m mpremote connect COM4 fs cp firmware/config.py firmware/lamps.py :
   python -m mpremote connect COM4 fs cp firmware/fsm.py firmware/link_serial.py :
   python -m mpremote connect COM4 fs cp firmware/scanner.py firmware/settings.py :
   python -m mpremote connect COM4 fs cp firmware/main.py :
   python -m mpremote connect COM4 reset
   ```
5. Onboard LED:
   - **3 s miltillaydi** → xavfsiz yuklanish oynasi (Ctrl-C bosilsa REPL)
   - **doimiy yonadi** → MES bilan aloqa bor
   - **sekin miltillaydi** → aloqa yo'q, eventlar buferga yozilyapti

> **Qurilmani ushlab qolish.** Watchdog yoqilgandan keyin `mpremote` ba'zan
> ulana olmaydi. Ikki yo'l: yuklanish paytidagi 3 s oynada urinish, yoki
> **GP22 ni GND ga** qisqartirib xavfsiz rejimda yuklash (`main.py` umuman
> ishga tushmaydi).

## 6. Sinov (stanoksiz)

| Amal | Kutilgan holat |
|---|---|
| GP9 ni simcha bilan GND da ushlab turing | `PROCESSING` |
| GP9 ni sekundiga 2–3 marta tegizing | `AWAIT_PART` |
| GP5 ni ushlab turing | `IDLE`, limitdan keyin `STOPPED` |
| GP1 ni ushlab turing | `FAULT` + `downtime_id` |
| Hech narsa ulanmagan (5 s dan uzoq) | `OFF` + `downtime_id` — "stanok o'chirilgan" |
| Bir chiroqni o'chirib, 2–3 s dan keyin boshqasini yoqing | `OFF` qayd etilmasligi kerak (o'tish pallasi) |
| GP5 ni uzoq ushlab, keyin GP1 ga o'ting | `STOPPED` yozuvi yopiladi (`closes_downtime_id`) va yangi `FAULT` ochiladi |

Qurilma yoqilganda REPL ga sessiya id chiqadi
(`PRISADKA-01 sessiya=a3f19c ...`) — u har qayta yuklanishda o'zgaradi va
eventlardagi `session` maydoniga tushadi.

Sinovni kuzatish — MES ekranini oching:

```bash
python app.py            # MES + USB ko'prik + Chrome  (yoki PrisadkaMES.exe)
```

Holat o'zgarishlari **Monitor** bo'limida, to'xtashlar **To'xtashlar** da
darhol ko'rinadi. Sozlamani o'zgartirish uchun **Sinov paneli** →
"Stanokka buyruq" (kutish limiti, hisoblagichni nollash, qayta yuklash).

Xom xabarlarni ko'rish kerak bo'lsa: `PrisadkaMES.exe --console` yoki
jurnal `logs\prisadka.log`.

## 7. Cheklovlar

- Bufer **RAM** da (`BUFFER_MAX = 200`, har yozuv ~300 bayt). Quvvat uzilsa
  yuborilmagan xabarlar yo'qoladi. Kerak bo'lsa flash'ga yozish qo'shiladi.
- USB transportda qayd stanokdagi kompyuterga bog'liq: u o'chsa yoki uxlasa,
  ko'prik to'xtaydi. Pico ~200 ta event saqlaydi (bir necha soat), keyin eng
  eskisi yo'qola boshlaydi.
  Retained snapshot'lar buferda to'planmaydi — faqat oxirgisi saqlanadi,
  shuning uchun uzoq oflayn turish RAM ni to'ldirmaydi.
- Miltillashni aniqlash 2 s oynada ishlaydi: `blink → doimiy` o'tishi ~2 s
  kechikish bilan tan olinadi. Chiroq 0.5 Hz dan sekin miltillasa,
  `BLINK_WINDOW_MS` ni oshiring.
