"""Pico simulyatori - temirsiz sinov uchun.

Muhimi: bu yerda **haqiqiy firmware kodi** ishlaydi. `firmware/lamps.py` va
`firmware/fsm.py` o'zgarishsiz import qilinadi; faqat `machine` va `time`
modullari soxta versiyalar bilan almashtiriladi (Pico'dagi GPIO va
`ticks_ms()` o'rniga). Tarmoq qatlami (`link.py`) o'rniga `mes.client`
ishlatiladi - qolgan hammasi bir xil.

Ishlatish:
    python sim/pico_sim.py --mode demo            # 45 daqiqalik smena, tezlashtirilgan
    python sim/pico_sim.py --mode manual          # chiroqlar MES sinov panelidan
    python sim/pico_sim.py --machine PRISADKA-02  # ikkinchi stanok
"""

import argparse
import json
import os
import sys
import time as real_time
import types
import urllib.request

try:                       # chiqish darhol ko'rinsin (fayllga yozilganda ham)
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE = os.path.join(ROOT, "firmware")
sys.path.insert(0, ROOT)

# MUHIM: `mes.client` soxta `time` qo'yilishidan OLDIN import qilinadi,
# aks holda u MicroPython'ning ticks_ms() li modulini olib qolardi.
from mes.client import Client                                    # noqa: E402

# ---------------------------------------------------------------- soxta muhit
LEVELS = {}                      # gpio -> 0/1 (chiroq yoniq bo'lsa 0)

_ft = types.ModuleType("time")
_ft.NOW = [0]
_ft.ticks_ms = lambda: _ft.NOW[0]
_ft.ticks_diff = lambda a, b: a - b
_ft.ticks_add = lambda a, b: a + b
_ft.time = real_time.time
_ft.sleep_ms = lambda ms: None
sys.modules["time"] = _ft


class FakePin:
    IN = 0
    OUT = 1
    PULL_UP = 2
    PULL_DOWN = 3

    def __init__(self, gpio, mode=None, pull=None):
        self.gpio = gpio

    def value(self, v=None):
        return LEVELS.get(self.gpio, 1)


_fm = types.ModuleType("machine")
_fm.Pin = FakePin
sys.modules["machine"] = _fm

sys.path.insert(0, FIRMWARE)
import config as base_cfg          # noqa: E402
import lamps as lamps_mod          # noqa: E402
import settings as settings_mod    # noqa: E402
from fsm import Fsm                # noqa: E402

# ---------------------------------------------------------------- ssenariy
# (izoh, chiroqlar, virtual soniya, shu qadam ichida QR skan qilinadigan soniya)
#
# Haqiqiy ish tartibi:
#   operator detal chekini skanerlaydi     -> yashil MILTILLAYDI (detal kutilmoqda)
#   detal stanokka kirdi                   -> yashil DOIMIY (ishlov ketmoqda)
#   ishlov paytida keyingi chek skanerlandi -> chiroq doimiy yashil qolaveradi,
#       ishlov tugashi bilan DARHOL yana miltillashga o'tadi
#   hech narsa skanerlanmagan              -> SARIQ (kutish rejimi)
DEMO = [
    ("Smena boshlanmagan",                   {},                   20,  None),
    ("Kutish rejimi (sariq)",                {"yellow": "on"},     90,  85),
    ("Detal kutilmoqda (yashil miltillash)", {"green": "blink"},   40,  None),
    ("Detal kirdi - ishlov ketmoqda",        {"green": "on"},      180, 30),
    ("Navbatdagi detal kutilmoqda",          {"green": "blink"},   25,  None),
    ("Ishlov ketmoqda",                      {"green": "on"},      200, None),
    ("AVARIYA (ishlov o'rtasida)",           {"red": "on"},        240, None),
    ("Avariya tugadi, ishlov davom etdi",    {"green": "on"},      60,  None),
    ("Skan yo'q -> sariq (kutish rejimi)",   {"yellow": "on"},     120, 110),
    ("Detal kutilmoqda",                     {"green": "blink"},   35,  None),
    ("Ishlov ketmoqda",                      {"green": "on"},      190, None),
    ("Uzoq kutish -> STOPPED",               {"yellow": "on"},     1200, None),
    ("STOPPED ustiga AVARIYA",               {"red": "on"},        150, None),
    ("Ishga tushdi, chek skanerlandi",       {"yellow": "on"},     20,  10),
    ("Detal kutilmoqda",                     {"green": "blink"},   30,  None),
    ("Ishlov ketmoqda",                      {"green": "on"},      170, None),
    ("Smena tugadi",                         {},                   30,  None),
]

BLINK_HALF_MS = 500              # yashil miltillash: 1 Hz (0.5 s yoniq / 0.5 s o'chiq)


class Sim:
    def __init__(self, args):
        self.args = args
        self.cfg = self._cfg()
        self.st = {"idle_timeout_s": args.idle_timeout,
                   "idle_timeout_enabled": True}
        self.lampcmd = {"green": "off", "yellow": "off", "red": "off"}
        self.pending = []
        self.epoch = int(real_time.time())
        self.boot_v = 0
        self.reader = lamps_mod.LampReader(self.cfg)
        self.fsm = Fsm(self.cfg, self.st, self.pending.append)
        self.mq = None
        self.next_beat = 0

    def _cfg(self):
        class C:
            pass
        for k in dir(base_cfg):
            if k.isupper():
                setattr(C, k, getattr(base_cfg, k))
        C.MACHINE_ID = self.args.machine
        return C

    # ---------------------------------------------------------- MQTT
    def topic(self, kind):
        return "mes/andon/{}/{}".format(self.cfg.MACHINE_ID, kind)

    def connect(self):
        self.mq = Client(self.args.host, self.args.port,
                         client_id=self.cfg.MACHINE_ID,
                         will=(self.topic("online"), b"0", True),
                         on_message=self.on_message)
        self.mq.connect()
        self.mq.publish(self.topic("online"), b"1", retain=True)
        self.mq.subscribe(self.topic("cmd"))
        self.mq.subscribe("sim/{}/lamps".format(self.cfg.MACHINE_ID))
        print("broker: {}:{}  stanok: {}  sessiya: {}".format(
            self.args.host, self.args.port, self.cfg.MACHINE_ID, self.fsm.session))

    def on_message(self, topic, payload, retained=False):
        try:
            data = json.loads(payload)
        except Exception:
            return
        if topic.startswith("sim/"):
            for k in ("green", "yellow", "red"):
                if k in data:
                    self.lampcmd[k] = data[k]
            return
        # ---- MES dan kelgan buyruq (Pico dagi main.on_cmd bilan bir xil) ----
        if settings_mod.apply_cmd(self.st, data):
            self.fsm.apply(self.st)
            print("  sozlama: kutish limiti = {} s, yoqilgan = {}".format(
                self.st["idle_timeout_s"], self.st["idle_timeout_enabled"]))
        if data.get("reset_counter"):
            self.fsm.part_count = 0
            print("  hisoblagich nollandi")
        if data.get("reboot"):
            print("  QAYTA YUKLANISH (yangi sessiya, seq 1 dan)")
            self.fsm = Fsm(self.cfg, self.st, self.pending.append)
            self.boot_v = _ft.NOW[0]
            print("  yangi sessiya: {}".format(self.fsm.session))

    def ts(self):
        return self.epoch + _ft.NOW[0] // 1000

    def flush(self):
        for ev in self.pending:
            if ev["type"] == "state":
                print("  [{}] {} -> {} ({} s){}".format(
                    ev["seq"], ev["prev_state"], ev["state"],
                    ev["prev_duration_s"],
                    "  to'xtash#" + ev["downtime_id"] if ev.get("downtime_id") else ""))
            else:
                print("  [{}] SIKL kutish={}s ishlov={}s {}".format(
                    ev["seq"], ev["wait_s"], ev["process_s"],
                    "tugallandi" if ev["completed"] else "TUGALLANMADI"))
            self.mq.publish(self.topic("event"), json.dumps(ev))
        self.pending.clear()

    def snapshot(self):
        return {
            "type": "snapshot",
            "machine_id": self.cfg.MACHINE_ID,
            "site": self.cfg.SITE,
            "session": self.fsm.session,
            "ts": self.ts(),
            "state": self.fsm.state or "BOOT",
            "since_s": self.fsm.elapsed_s(_ft.NOW[0]),
            "lamps": dict(self.reader.status),
            "part_id": self.fsm.part_id,
            "part_count": self.fsm.part_count,
            "idle_timeout_s": self.st["idle_timeout_s"],
            "idle_timeout_enabled": self.st["idle_timeout_enabled"],
            "uptime_s": (_ft.NOW[0] - self.boot_v) // 1000,
            "queued": 0,
            "dropped": 0,
            "rssi": -55,
        }

    def send_scan(self, part_id):
        """MES tizimiga QR skan keldi (haqiqiy tizimda o'z skaneridan)."""
        body = json.dumps({"machine_id": self.cfg.MACHINE_ID,
                           "part_id": part_id,
                           "scanned_at": self.ts()}).encode()
        req = urllib.request.Request(
            self.args.mes + "/api/scan", data=body,
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=3).read()
            print("  MES: QR skan {}".format(part_id))
        except Exception as e:
            print("  MES ga skan yuborilmadi: {}".format(e))

    # ---------------------------------------------------------- chiroqlar
    def apply_levels(self):
        """Chiroq buyrug'ini xom GPIO darajasiga aylantiradi.

        Miltillash haqiqiy chiroq kabi o'chib-yonadi - shu tufayli
        `lamps.py` dagi debounce va blink aniqlash ham sinaladi.
        """
        v = _ft.NOW[0]
        for name, gpio in self.cfg.LAMPS:
            c = self.lampcmd.get(name, "off")
            if c == "on":
                lit = True
            elif c == "blink":
                lit = (v // BLINK_HALF_MS) % 2 == 0
            else:
                lit = False
            LEVELS[gpio] = 0 if (lit == self.cfg.ACTIVE_LOW) else 1

    def step(self):
        """Bitta o'qish davri (Pico dagi SAMPLE_MS ga teng)."""
        _ft.NOW[0] += self.cfg.SAMPLE_MS
        self.apply_levels()
        status = self.reader.update(_ft.NOW[0])
        self.fsm.update(_ft.NOW[0], status, self.ts())

    # ---------------------------------------------------------- tsikllar
    def run_steps(self, virtual_ms, label=None):
        """Virtual vaqtni `virtual_ms` ga suradi, real vaqtda tezlashtirilgan."""
        target = _ft.NOW[0] + virtual_ms
        tick = 0.02                                   # 20 ms real
        chunk = max(self.cfg.SAMPLE_MS,
                    int(self.args.speed * tick * 1000))
        while _ft.NOW[0] < target:
            end = min(target, _ft.NOW[0] + chunk)
            while _ft.NOW[0] < end:
                self.step()
            self.flush()
            self.mq.check()
            if _ft.NOW[0] >= self.next_beat:
                self.next_beat = _ft.NOW[0] + self.cfg.HEARTBEAT_S * 1000
                self.mq.publish(self.topic("state"),
                                json.dumps(self.snapshot()), retain=True)
            real_time.sleep(tick)

    def run_demo(self):
        total = sum(s[2] for s in DEMO)
        self.epoch = int(real_time.time()) - total
        print("\nDemo ssenariy: {} daqiqa smena, {}x tezlikda (~{} s)\n".format(
            total // 60, self.args.speed, round(total / self.args.speed)))
        self.part_no = 1001
        for label, cmd, secs, scan_at in DEMO:
            print("{:>6}s  {}".format(_ft.NOW[0] // 1000, label))
            self.lampcmd = {"green": "off", "yellow": "off", "red": "off"}
            self.lampcmd.update(cmd)
            if scan_at is None:
                self.run_steps(secs * 1000)
            else:
                # skan qadam O'RTASIDA bo'ladi - masalan ishlov ketayotganda
                self.run_steps(scan_at * 1000)
                self.send_scan("QR-88340{}".format(self.part_no))
                self.part_no += 1
                self.run_steps((secs - scan_at) * 1000)
        self.mq.publish(self.topic("state"),
                        json.dumps(self.snapshot()), retain=True)
        self.flush()
        print("\nSsenariy tugadi. Natijani MES ekranida ko'ring.")

    def run_manual(self):
        print("\nQo'lda rejim. Chiroqlarni MES ekranidagi 'Sinov paneli' dan\n"
              "boshqaring: http://localhost:8080  (Ctrl+C - to'xtatish)\n")
        self.lampcmd = {"green": "off", "yellow": "on", "red": "off"}
        while True:
            self.run_steps(1000)


def main():
    p = argparse.ArgumentParser(description="Pico W andon simulyatori")
    p.add_argument("--mode", choices=("demo", "manual"), default="demo")
    p.add_argument("--machine", default=base_cfg.MACHINE_ID)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--mes", default="http://127.0.0.1:8080")
    p.add_argument("--speed", type=float, default=120,
                   help="demo rejimida vaqtni tezlashtirish (1 = real vaqt)")
    p.add_argument("--idle-timeout", type=int, default=900,
                   help="sariq chiroq limiti, soniya")
    args = p.parse_args()
    if args.mode == "manual":
        args.speed = 1

    sim = Sim(args)
    try:
        sim.connect()
    except Exception as e:
        print("Broker'ga ulanib bo'lmadi ({}). Avval `python -m mes.server` "
              "ishga tushiring.".format(e))
        return 1
    try:
        if args.mode == "demo":
            sim.run_demo()
        else:
            sim.run_manual()
    except KeyboardInterrupt:
        print("\nsimulyator to'xtatildi")
    finally:
        sim.mq.publish(sim.topic("online"), b"0", retain=True)
        sim.mq.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
