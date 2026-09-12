"""PrisadkaMES.exe — hammasi bitta faylda, Python o'rnatilmagan kompyuter uchun.

Farqi `start.py` dan: u alohida jarayonlarni ochadi (ishlab chiqish uchun
qulay), bu esa hammasini **bitta jarayonda, oqimlar bilan** ishlatadi —
.exe ichida shunday to'g'ri bo'ladi.

    PrisadkaMES.exe                 MES + USB ko'prik + Chrome
    PrisadkaMES.exe --sim           Pico o'rniga simulyator (qo'lda rejim)
    PrisadkaMES.exe --sim-demo      simulyator, smena ssenariysi
    PrisadkaMES.exe --kiosk         Chrome to'liq ekran (sex monitori)
    PrisadkaMES.exe --no-browser    brauzersiz
"""

import argparse
import os
import runpy
import socket
import subprocess
import sys
import threading
import time
import types

WEB_PORT = 8080
MQTT_PORT = 1883

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def base_dir():
    """Bundle ichidagi resurslar (ui.html, firmware/, sim/)."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    """Yozish mumkin bo'lgan joy. .exe yonida - baza shu yerda qoladi."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def pause(msg="\n  Chiqish uchun Enter..."):
    """.exe ni ikki marta bosib ochganda oyna darhol yopilib ketmasin.
    Konsol bo'lmasa (quvurga yo'naltirilgan) - jim o'tib ketadi."""
    try:
        input(msg)
    except (EOFError, OSError, RuntimeError):
        pass


def port_busy(port, host="127.0.0.1"):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def wait_port(port, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if port_busy(port):
            return True
        time.sleep(0.25)
    return False


# ---------------------------------------------------------------- oqimlar

def server_thread(args):
    """MQTT broker + SQLite ko'prik + veb - o'z asyncio tsiklida."""
    import asyncio
    from mes import server as server_mod
    ns = types.SimpleNamespace(mqtt_port=args.mqtt_port, http_port=args.http_port,
                               db=args.db, quiet=True)
    try:
        asyncio.run(server_mod.run(ns))
    except Exception as e:
        print("MES serveri to'xtadi: {!r}".format(e))


def bridge_thread(args):
    """Pico USB -> MQTT. Broker ko'tarilguncha va plata ulanguncha kutadi."""
    from mes.serial_bridge import SerialBridge
    ns = types.SimpleNamespace(machine=args.machine, host="127.0.0.1",
                               mqtt_port=args.mqtt_port, port=args.port,
                               baud=115200)
    br = SerialBridge(ns)
    while True:
        try:
            br.run()
        except Exception as e:
            print("ko'prik uzildi ({!r}), 3 s dan keyin qayta uriniladi".format(e))
            try:
                br.close_port()
            except Exception:
                pass
            time.sleep(3)


def start_simulator(args):
    """Simulyatorni ALOHIDA jarayonda ochadi.

    U `sys.modules["time"]` ni soxta MicroPython versiyasi bilan almashtiradi,
    shuning uchun MES bilan bir jarayonda ishlay olmaydi.
    """
    mode = "demo" if args.sim_demo else "manual"
    cmd = [sys.executable]
    if getattr(sys, "frozen", False):
        cmd.append("--sim-worker")          # .exe o'zini qayta chaqiradi
    else:
        cmd.append(os.path.join(base_dir(), "sim", "pico_sim.py"))
    cmd += ["--mode", mode, "--machine", args.machine,
            "--mes", "http://127.0.0.1:{}".format(args.http_port)]
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    subprocess.Popen(cmd, creationflags=flags)
    print("  simulyator ishga tushdi ({} rejim)".format(mode))


def run_sim_worker():
    """--sim-worker: shu jarayon simulyatorga aylanadi."""
    path = os.path.join(base_dir(), "sim", "pico_sim.py")
    sys.argv = [path] + [a for a in sys.argv[1:] if a != "--sim-worker"]
    sys.path.insert(0, base_dir())
    runpy.run_path(path, run_name="__main__")


# ---------------------------------------------------------------- Chrome

def open_chrome(url, kiosk=False):
    exe = next((p for p in CHROME_PATHS if os.path.exists(p)), None)
    args = (["--kiosk"] if kiosk else []) + [url]
    if exe:
        subprocess.Popen([exe] + args)
        print("  Chrome ochildi: {}".format(url))
    else:
        import webbrowser
        webbrowser.open(url)
        print("  Chrome topilmadi - standart brauzerda ochildi: {}".format(url))


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------- asosiy

def main():
    if "--sim-worker" in sys.argv:
        return run_sim_worker()

    p = argparse.ArgumentParser(description="PRISADKA MES")
    p.add_argument("--sim", action="store_true", help="Pico o'rniga simulyator")
    p.add_argument("--sim-demo", action="store_true", help="simulyator, smena ssenariysi")
    p.add_argument("--machine", default="PRISADKA-01")
    p.add_argument("--port", default=None, help="COM porti (bo'sh -> o'zi topadi)")
    p.add_argument("--mqtt-port", type=int, default=MQTT_PORT)
    p.add_argument("--http-port", type=int, default=WEB_PORT)
    p.add_argument("--db", default=None)
    p.add_argument("--kiosk", action="store_true")
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()

    if args.db is None:
        args.db = os.path.join(data_dir(), "mes-data.db")

    print("=" * 58)
    print("  PRISADKA MES - Andon monitor")
    print("=" * 58)

    if port_busy(args.http_port):
        print("  Port {} band - MES allaqachon ishlayaptimi?".format(args.http_port))
        print("  Boshqa nusxasini yoping yoki --http-port bilan boshqa port bering.")
        pause()
        return 1

    threading.Thread(target=server_thread, args=(args,), daemon=True).start()
    if not wait_port(args.http_port):
        print("  XATO: MES serveri ochilmadi.")
        pause()
        return 1

    if args.sim or args.sim_demo:
        start_simulator(args)
    else:
        threading.Thread(target=bridge_thread, args=(args,), daemon=True).start()

    if not args.no_browser:
        time.sleep(1.0)
        open_chrome("http://localhost:{}".format(args.http_port), args.kiosk)

    print("-" * 58)
    print("  MES ekrani : http://localhost:{}".format(args.http_port))
    print("  Tarmoqdan  : http://{}:{}".format(local_ip(), args.http_port))
    print("  Baza       : {}".format(args.db))
    print("  To'xtatish : Ctrl+C yoki shu oynani yopish")
    print("-" * 58)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nto'xtatildi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
