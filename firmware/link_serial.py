# USB-serial transport — Wi-Fi'siz Pico (RP2040) uchun.
#
# `link.py` ning o'rnini bosadi va aynan o'sha interfeysni beradi
# (enqueue / pump / online / now_ts / rssi). Farqi: xabarlar Wi-Fi emas,
# USB kabel orqali kompyuterga boradi, u yerdagi ko'prik (mes/serial_bridge.py)
# ularni MQTT ga uzatadi.
#
# Sim protokoli (har biri bitta qator):
#   Pico -> kompyuter :  MES <kind> <json>     kind = event | state
#   kompyuter -> Pico :  CMD <json>            sozlama o'zgartirish
#                        PING                  "men tirikman" (har 5 s)
#
# Boshqa har qanday qator (print, traceback) ko'prik tomonidan jurnal deb
# qabul qilinadi — shuning uchun odatiy print() larni o'chirish shart emas.

import json
import sys
import time

try:
    import select
except ImportError:                       # eski MicroPython
    import uselect as select


class SerialLink:
    def __init__(self, cfg, feed=None, on_cmd=None):
        self.cfg = cfg
        self.feed = feed or (lambda: None)
        self.on_cmd = on_cmd
        self.buf = []
        self.dropped = 0
        self.time_ok = False              # NTP yo'q - vaqtni server qo'yadi
        self.wlan = None

        self._alive_ms = getattr(cfg, "SERIAL_HOST_TIMEOUT_MS", 15000)
        self._host_at = time.ticks_add(time.ticks_ms(), -self._alive_ms)
        self._rx = ""
        self._poll = select.poll()
        self._poll.register(sys.stdin, select.POLLIN)

        # `link.py` dagi topic nomlari o'rniga oddiy tur nomlari
        self.t_event = "event"
        self.t_state = "state"
        self.t_online = "online"
        self.t_cmd = "cmd"

    # ---------- holat ----------
    @property
    def online(self):
        """Kompyuterdagi ko'prik yaqinda gapirdimi?

        Kabel uzilsa yoki ko'prik to'xtasa, USB CDC ga yozilgan ma'lumot
        jimgina yo'qoladi. Shuning uchun "onlayn" ni PING bo'yicha
        aniqlaymiz va oflayn paytda buferga yig'amiz.
        """
        return time.ticks_diff(time.ticks_ms(), self._host_at) < self._alive_ms

    def rssi(self):
        return None

    def now_ts(self):
        return 0                          # vaqtni ko'prik qo'yadi

    # ---------- yuborish ----------
    def enqueue(self, topic, payload, retain=False):
        msg = json.dumps(payload)
        if retain:
            # snapshot - faqat oxirgisi kerak (link.py dagi kabi)
            for i in range(len(self.buf)):
                if self.buf[i][2] and self.buf[i][0] == topic:
                    self.buf[i] = (topic, msg, True)
                    return
        if len(self.buf) >= self.cfg.BUFFER_MAX:
            self.buf.pop(0)
            self.dropped += 1
        self.buf.append((topic, msg, retain))

    def _flush(self):
        while self.buf:
            topic, msg, _ = self.buf[0]
            try:
                sys.stdout.write("MES {} {}\n".format(topic, msg))
            except Exception:
                return False              # keyingi tsiklda qayta urinamiz
            self.buf.pop(0)
            self.feed()
        return True

    # ---------- qabul qilish ----------
    def _handle(self, line):
        self._host_at = time.ticks_ms()   # har qanday qator = ko'prik tirik
        if not line.startswith("CMD "):
            return
        try:
            data = json.loads(line[4:])
        except Exception:
            return
        if isinstance(data, dict) and self.on_cmd:
            try:
                self.on_cmd(data)
            except Exception as e:
                print("cmd xatosi:", e)

    def _read(self):
        # poll(0) bloklamaydi; 256 belgidan ko'p o'qimaymiz - asosiy tsikl
        # sekinlashmasin.
        n = 0
        while n < 256 and self._poll.poll(0):
            ch = sys.stdin.read(1)
            n += 1
            if not ch:
                break
            if ch in ("\n", "\r"):
                if self._rx:
                    self._handle(self._rx)
                    self._rx = ""
            else:
                self._rx += ch
                if len(self._rx) > 512:   # shovqin - tashlab yuboramiz
                    self._rx = ""

    # ---------- asosiy tsikl chaqiruvi ----------
    def pump(self):
        self._read()
        if self.buf and self.online:
            self._flush()
