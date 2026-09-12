# PRISADKA ANDON MONITOR - asosiy tsikl.
#
# Pico ga yuklang:
#   TRANSPORT = "serial" (Wi-Fi'siz Pico):
#       config.py lamps.py fsm.py link_serial.py scanner.py settings.py main.py
#   TRANSPORT = "wifi" (Pico W):
#       config.py lamps.py fsm.py link.py scanner.py settings.py main.py

import time
from machine import Pin, WDT

import config as cfg
import settings
from lamps import LampReader
from scanner import Scanner
from fsm import Fsm

# Transport config.py dan tanlanadi. MUHIM: `link.py` `network` modulini
# import qiladi, u esa Wi-Fi'siz Pico proshivkasida yo'q - shuning uchun
# kerakmagan modul umuman import qilinmaydi.
if getattr(cfg, "TRANSPORT", "wifi") == "serial":
    from link_serial import SerialLink as Link
else:
    from link import Link

try:
    led = Pin("LED", Pin.OUT)    # Pico W da Wi-Fi chipida, Pico da GP25
except Exception:
    led = Pin(25, Pin.OUT)

# Xavfsiz yuklanish oynasi. Watchdog yoqilgandan keyin qurilmani to'xtatib
# qayta dasturlash qiyinlashadi (ayniqsa xato tufayli reset tsikliga tushsa).
# Shu 3 sekundda Ctrl-C bosib REPL ga chiqib olish mumkin, yoki GP22 ni GND
# ga qisqartirib main.py ni umuman ishga tushirmaslik mumkin.
SAFE_PIN = getattr(cfg, "SAFE_BOOT_PIN", 22)
BOOT_DELAY_S = getattr(cfg, "BOOT_DELAY_S", 3)

print("PRISADKA ANDON - {} s ichida Ctrl-C bosilsa REPL ga chiqadi".format(
    BOOT_DELAY_S))
for _ in range(BOOT_DELAY_S * 5):
    led.toggle()
    time.sleep_ms(200)
led.value(0)

if Pin(SAFE_PIN, Pin.IN, Pin.PULL_UP).value() == 0:
    print("XAVFSIZ REJIM (GP{} = GND): main.py ishga tushmadi".format(SAFE_PIN))
    raise SystemExit

wdt = WDT(timeout=8000)          # RP2040 maksimumi ~8.3 s


def main():
    st = settings.load(cfg)
    reader = LampReader(cfg)
    scanner = Scanner(cfg)
    link = None
    fsm = None

    def emit(ev):
        link.enqueue(link.t_event, ev)
        if ev["type"] == "state":
            print("[{}] {} -> {} ({} s)".format(
                ev["seq"], ev["prev_state"], ev["state"], ev["prev_duration_s"]))
        else:
            print("[{}] SIKL {} kutish={}s ishlov={}s".format(
                ev["seq"], ev.get("part_id") or "-", ev["wait_s"], ev["process_s"]))

    def snapshot(now):
        return {
            "type": "snapshot",
            "machine_id": cfg.MACHINE_ID,
            "site": cfg.SITE,
            "session": fsm.session,
            "ts": link.now_ts(),
            "state": fsm.state or "BOOT",
            "since_s": fsm.elapsed_s(now),
            "lamps": dict(reader.status),
            "part_id": fsm.part_id,
            "part_count": fsm.part_count,
            "idle_timeout_s": st["idle_timeout_s"],
            "idle_timeout_enabled": st["idle_timeout_enabled"],
            "uptime_s": time.ticks_diff(now, boot_at) // 1000,
            "queued": len(link.buf),
            "dropped": link.dropped,
            "rssi": link.rssi(),
        }

    def on_cmd(data):
        # MES -> mes/andon/<ID>/cmd
        #   {"idle_timeout_s": 600}
        #   {"idle_timeout_enabled": false}
        #   {"reset_counter": true}
        #   {"reboot": true}
        if settings.apply_cmd(st, data):
            settings.save(st)
            fsm.apply(st)
            print("sozlama: kutish limiti =", st["idle_timeout_s"], "s,",
                  "yoqilgan =", st["idle_timeout_enabled"])
        if data.get("reset_counter"):
            fsm.part_count = 0
        link.enqueue(link.t_state, snapshot(time.ticks_ms()), retain=True)
        if data.get("reboot"):
            import machine
            machine.reset()

    link = Link(cfg, feed=wdt.feed, on_cmd=on_cmd)
    fsm = Fsm(cfg, st, emit, scanner)
    # Sessiya id har yuklanishda yangilanadi - MES eventlarni (session, seq)
    # bo'yicha ajratadi, aks holda reboot'dan keyin seq takrorlanib ketardi.
    print("{} sessiya={} kutish limiti={} s".format(
        cfg.MACHINE_ID, fsm.session, st["idle_timeout_s"]))

    now = time.ticks_ms()
    boot_at = now
    next_sample = now
    next_beat = now
    next_led = now

    while True:
        wdt.feed()
        now = time.ticks_ms()

        # ---------- 1. QR skaner ----------
        scanner.poll(now)

        # ---------- 2. Chiroqlar + holat mashinasi ----------
        if time.ticks_diff(now, next_sample) >= 0:
            next_sample = time.ticks_add(now, cfg.SAMPLE_MS)
            status = reader.update(now)
            fsm.update(now, status, link.now_ts())

        # ---------- 3. Heartbeat (retained) ----------
        if time.ticks_diff(now, next_beat) >= 0:
            next_beat = time.ticks_add(now, cfg.HEARTBEAT_S * 1000)
            link.enqueue(link.t_state, snapshot(now), retain=True)

        # ---------- 4. Tarmoq ----------
        link.pump()

        # ---------- 5. LED: doimiy = onlayn, miltillash = oflayn ----------
        if link.online:
            led.value(1)
        elif time.ticks_diff(now, next_led) >= 0:
            next_led = time.ticks_add(now, 400)
            led.toggle()

        time.sleep_ms(2)


try:
    main()
except Exception as e:
    import sys
    sys.print_exception(e)
    time.sleep(3)
    import machine
    machine.reset()
