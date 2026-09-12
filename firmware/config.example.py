# PRISADKA STANOK - ANDON MONITOR (Raspberry Pi Pico W)
# Barcha sozlamalar shu faylda.

# ---------- Stanok identifikatori ----------
MACHINE_ID = "PRISADKA-01"
SITE = "SEX-1"

# ---------- Transport: MES ga qanday ulanadi ----------
#   "serial" - USB kabel orqali stanokdagi kompyuterga (Wi-Fi'siz Pico uchun).
#              Kompyuterda `python -m mes.serial_bridge` ishlashi kerak.
#   "wifi"   - to'g'ridan-to'g'ri MQTT broker'ga (faqat Pico W).
# Wi-Fi'siz Pico da "wifi" tanlansa, `network` moduli topilmay xato beradi.
TRANSPORT = "serial"
SERIAL_HOST_TIMEOUT_MS = 15000   # ko'prikdan shuncha vaqt ovoz chiqmasa - oflayn

# ---------- Wi-Fi (faqat TRANSPORT = "wifi" bo'lganda) ----------
WIFI_SSID = "SSID-NI-YOZING"
WIFI_PASS = "PAROLNI-YOZING"
WIFI_TIMEOUT_S = 15

# ---------- MQTT broker (MES tomoni) ----------
# MUHIM: IP manzil yozing. DNS so'rovi Pico'ni bloklab, watchdog reset qilishi mumkin.
MQTT_HOST = "0.0.0.0"          # broker IP manzili
MQTT_PORT = 1883
MQTT_USER = None
MQTT_PASS = None
MQTT_KEEPALIVE = 60
# Soket timeout. umqtt connect() da uchta bloklovchi bosqich bor
# (TCP + CONNACK + SUBACK), shuning uchun 8 s watchdog / 3 dan kichik bo'lsin.
MQTT_SOCKET_TIMEOUT_S = 2

TOPIC_EVENT  = "mes/andon/{}/event"    # state + cycle xabarlari
TOPIC_STATE  = "mes/andon/{}/state"    # retained snapshot (heartbeat)
TOPIC_ONLINE = "mes/andon/{}/online"   # LWT: 1 = ulangan, 0 = uzilgan
TOPIC_CMD    = "mes/andon/{}/cmd"      # MES -> Pico: sozlamalarni o'zgartirish

# ---------- Pin xaritasi ----------
# Chiroq YONIQ -> optopara ochiladi -> GPIO = 0
# Tartib ahamiyatsiz - mantiq nom bo'yicha ishlaydi.
LAMPS = (
    ("red",     1),   # GP1  - qizil:  avariya
    ("yellow",  5),   # GP5  - sariq:  kutish rejimi (detal skanerlanmagan)
    ("green",   9),   # GP9  - yashil: miltillasa detal kutilmoqda, doimiy bo'lsa ishlov
)
ACTIVE_LOW = True
# DIQQAT: GP1 - UART0 RX ning standart pini. Kelajakda UART qurilma qo'shilsa,
# u boshqa pinlarga (masalan UART1: GP4/GP5 emas, GP8/GP9 emas) olinishi kerak.

# ---------- Kutish rejimi -> O'CHIQ ----------
# Sariq chiroq shu vaqtdan uzoq yonsa, stanok STOPPED (o'chiq) deb qayd etiladi.
# Bu qiymatni MQTT orqali ham o'zgartirish mumkin (settings.json ga saqlanadi):
#   mes/andon/PRISADKA-01/cmd  <-  {"idle_timeout_s": 600}
IDLE_TIMEOUT_S = 900          # 15 daqiqa
IDLE_TIMEOUT_ENABLED = True   # False -> sariq doim IDLE bo'lib qoladi

# ---------- "Stanok o'chirilgan" ni tasdiqlash ----------
# Uchchala chiroq ham o'chiq bo'lsa stanok o'chirilgan deb qayd etiladi va
# MES da sabab so'raladi. Lekin PLC bir chiroqni o'chirib ikkinchisini
# yoqguncha oraliqda hamma chiroq o'chiq bo'lib qolishi mumkin - o'sha
# qisqa pallani "o'chdi" deb yozmaslik uchun tasdiqlash vaqti.
OFF_CONFIRM_MS = 5000

# ---------- Xavfsiz yuklanish ----------
# Watchdog yoqilgandan keyin qurilmani to'xtatib qayta dasturlash qiyin.
# Shu sabab main.py boshida kichik oyna qoldiriladi:
#   - BOOT_DELAY_S soniya davomida Ctrl-C bosilsa REPL ga chiqiladi;
#   - SAFE_BOOT_PIN GND ga qisqartirilgan bo'lsa, main.py umuman ishlamaydi.
BOOT_DELAY_S = 3
SAFE_BOOT_PIN = 22            # chiroq pinlaridan (1, 5, 9) farqli bo'lsin

# ---------- QR skaner (ixtiyoriy) ----------
# TTL/RS232 chiqishli skaner Pico UART ga ulansa, detal raqami eventga qo'shiladi.
# Skaner MES kompyuteriga ulangan bo'lsa, bu yerni None qoldiring -
# MES eventlarni vaqt bo'yicha o'zi bog'laydi.
SCANNER = None
# SCANNER = {"uart": 0, "tx": 0, "rx": 1, "baud": 9600}
SCAN_MAX_AGE_MS = 60000       # skandan keyin shu vaqt ichida detal kutishga o'tsa - bog'lanadi

# ---------- Vaqt sozlamalari (ms) ----------
SAMPLE_MS = 10                # chiroqni o'qish davri
DEBOUNCE_SAMPLES = 5          # 5 x 10 ms = 50 ms barqarorlik
BLINK_WINDOW_MS = 2000        # miltillash oynasi
BLINK_MIN_EDGES = 2           # oynada 2+ o'zgarish -> "blink"
# Holat commit qilinishidan oldin shuncha vaqt barqaror turishi kerak.
# MUHIM: bu qiymat miltillashning YARIM DAVRIDAN katta bo'lishi shart.
# Yashil miltillay boshlaganda birinchi yarim davr "doimiy yoniq" bo'lib
# ko'rinadi (lamps.py ikkita qirra ko'rmaguncha blink deya olmaydi) - agar
# MIN_STATE_MS kichik bo'lsa, o'sha soxta PROCESSING qayd etiladi.
# BLINK_WINDOW_MS = 2000 -> aniqlanadigan eng sekin miltillash yarim davri
# 1000 ms -> MIN_STATE_MS undan katta: 1200.
MIN_STATE_MS = 1200
# Sikl "tugallandi" deb sanalishi uchun minimal ishlov vaqti. Haqiqiy detal
# sikli daqiqalar bilan o'lchanadi, shuning uchun bu faqat shovqin filtri.
MIN_PROCESS_MS = 5000

# ---------- Tarmoq / bufer ----------
HEARTBEAT_S = 30
BUFFER_MAX = 200              # oflayn navbat (RAM). Har yozuv ~300 bayt;
                              # Pico W da bo'sh RAM ~170 KB, oshirmang.
RECONNECT_MIN_MS = 1000
RECONNECT_MAX_MS = 30000

# ---------- NTP ----------
# MUHIM: faqat IP. DNS nomi (masalan "pool.ntp.org") getaddrinfo'da soketni
# bloklaydi va watchdog reset'ga olib keladi. Odatda MES serveri NTP ham
# tarqatadi - shuning uchun MQTT_HOST ning o'zi.
NTP_HOST = MQTT_HOST
NTP_RESYNC_S = 3600
