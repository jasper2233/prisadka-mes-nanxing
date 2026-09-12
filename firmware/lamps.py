# Chiroq liniyalarini o'qish: debounce + miltillash (blink) aniqlash.

import time
from machine import Pin

OFF = "off"
ON = "on"
BLINK = "blink"

_MAX_EDGES = 16


class Lamp:
    def __init__(self, name, gpio, active_low, debounce_n, blink_window, blink_edges):
        self.name = name
        pull = Pin.PULL_UP if active_low else Pin.PULL_DOWN
        self.pin = Pin(gpio, Pin.IN, pull)
        self._active_low = active_low
        self._debounce_n = debounce_n
        self._window = blink_window
        self._min_edges = blink_edges

        self.level = False        # debounce'dan o'tgan holat
        self.status = OFF
        self._cand = False
        self._count = 0
        self._edges = []

    def _raw(self):
        v = self.pin.value()
        return (v == 0) if self._active_low else (v == 1)

    def update(self, now):
        r = self._raw()

        # --- debounce: bir xil qiymat N marta ketma-ket kelishi kerak ---
        if r == self._cand:
            if self._count < self._debounce_n:
                self._count += 1
        else:
            self._cand = r
            self._count = 1

        if self._count >= self._debounce_n and r != self.level:
            self.level = r
            self._edges.append(now)
            if len(self._edges) > _MAX_EDGES:
                self._edges.pop(0)

        # --- oynadan chiqqan o'zgarishlarni tashlash ---
        while self._edges and time.ticks_diff(now, self._edges[0]) > self._window:
            self._edges.pop(0)

        # --- tasnif ---
        if len(self._edges) >= self._min_edges:
            self.status = BLINK
        elif self.level:
            self.status = ON
        else:
            self.status = OFF
        return self.status


class LampReader:
    """Barcha chiroqlarni bitta joydan boshqaradi.

    update() har safar bitta va o'sha lug'atni qaytaradi (RAM tejash uchun).
    Nusxa kerak bo'lsa dict(...) qiling.
    """

    def __init__(self, cfg):
        self.lamps = [
            Lamp(name, gpio, cfg.ACTIVE_LOW, cfg.DEBOUNCE_SAMPLES,
                 cfg.BLINK_WINDOW_MS, cfg.BLINK_MIN_EDGES)
            for name, gpio in cfg.LAMPS
        ]
        self.status = {l.name: OFF for l in self.lamps}

    def update(self, now):
        for l in self.lamps:
            self.status[l.name] = l.update(now)
        return self.status
