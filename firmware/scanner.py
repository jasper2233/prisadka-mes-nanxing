# QR skaner (TTL/RS232 chiqishli) - ixtiyoriy modul.
# cfg.SCANNER = None bo'lsa hech narsa qilmaydi.

import time


class Scanner:
    def __init__(self, cfg):
        c = getattr(cfg, "SCANNER", None)
        self.enabled = bool(c)
        self.last_code = None
        self.last_ts = 0
        self._buf = b""
        self.uart = None
        if self.enabled:
            from machine import UART, Pin
            self.uart = UART(c["uart"], baudrate=c["baud"],
                             tx=Pin(c["tx"]), rx=Pin(c["rx"]), timeout=0)

    def poll(self, now):
        """Har tsiklda chaqiriladi. Yangi kod kelsa uni qaytaradi."""
        if not self.enabled:
            return None

        n = self.uart.any()
        if n:
            self._buf += self.uart.read(n)
            if len(self._buf) > 256:
                self._buf = self._buf[-256:]

        code = None
        while True:
            i = -1
            for sep in (b"\r", b"\n"):
                j = self._buf.find(sep)
                if j >= 0 and (i < 0 or j < i):
                    i = j
            if i < 0:
                break
            raw = self._buf[:i].strip()
            self._buf = self._buf[i + 1:]
            if raw:
                try:
                    code = raw.decode().strip()
                except Exception:
                    code = None

        if code:
            self.last_code = code
            self.last_ts = now
        return code

    def take(self, now, max_age_ms):
        """Yaqinda skanerlangan kodni oladi (bir marta)."""
        if self.last_code and time.ticks_diff(now, self.last_ts) <= max_age_ms:
            c = self.last_code
            self.last_code = None
            return c
        return None
