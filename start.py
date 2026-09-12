"""Hammasini bitta buyruq bilan ishga tushiradi va Chrome ni ochadi.

    python start.py                 # MES + ko'prik + Chrome
    python start.py --sim           # Pico o'rniga simulyator (temirsiz sinov)
    python start.py --sim-demo      # simulyator, 45 daqiqalik smena ssenariysi
    python start.py --kiosk         # Chrome to'liq ekran (sex monitori uchun)
    python start.py --no-browser    # brauzersiz

Qayta ishga tushirilsa xavfli emas: allaqachon ishlab turgan qismlar
qaytadan ochilmaydi (port band bo'lsa jarayon o'zi chiqib ketadi).
"""

import argparse
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB_PORT = 8080
MQTT_PORT = 1883

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def port_busy(port, host="127.0.0.1"):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def spawn(args, title):
    """Alohida oynada ishga tushiradi (yopilsa boshqalariga xalal bermaydi)."""
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_CONSOLE
    try:
        subprocess.Popen([sys.executable] + args, cwd=ROOT, creationflags=flags)
        print("  ishga tushdi: {}".format(title))
        return True
    except Exception as e:
        print("  XATO ({}): {}".format(title, e))
        return False


def wait_port(port, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if port_busy(port):
            return True
        time.sleep(0.3)
    return False


def find_pico():
    try:
        sys.path.insert(0, ROOT)
        from mes.serial_bridge import find_pico as fp
        return fp()
    except Exception:
        return None


def open_chrome(url, kiosk=False, app=False):
    exe = next((p for p in CHROME_PATHS if os.path.exists(p)), None)
    args = []
    if kiosk:
        args.append("--kiosk")
    if app:
        args.append("--app=" + url)
    else:
        args.append(url)
    if exe:
        subprocess.Popen([exe] + args)
        print("  Chrome ochildi: {}".format(url))
    else:
        import webbrowser
        webbrowser.open(url)
        print("  Chrome topilmadi - standart brauzerda ochildi: {}".format(url))


def startup_dir():
    return os.path.expandvars(
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")


def set_autostart(enable):
    """Kompyuter yoqilganda MES o'zi ishga tushsin.

    Startup papkasiga kichik .bat qo'yiladi - istalgan vaqtda o'chirsa bo'ladi.
    """
    path = os.path.join(startup_dir(), "prisadka-mes.bat")
    if not enable:
        if os.path.exists(path):
            os.remove(path)
            print("Avtoyuklanish o'chirildi: {}".format(path))
        else:
            print("Avtoyuklanish allaqachon o'chiq.")
        return 0
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write('@echo off\r\n')
            f.write('cd /d "{}"\r\n'.format(ROOT))
            f.write('start "" /min python start.py --no-browser\r\n')
        print("Avtoyuklanish yoqildi: {}".format(path))
        print("Kompyuter yoqilganda MES fonda ishga tushadi (brauzersiz).")
        print("O'chirish uchun:  python start.py --no-autostart")
        return 0
    except Exception as e:
        print("Avtoyuklanish o'rnatilmadi: {}".format(e))
        return 1


def main():
    p = argparse.ArgumentParser(description="PRISADKA MES - ishga tushirish")
    p.add_argument("--autostart", action="store_true",
                   help="kompyuter yoqilganda o'zi ishga tushsin")
    p.add_argument("--no-autostart", action="store_true",
                   help="avtoyuklanishni o'chirish")
    p.add_argument("--sim", action="store_true",
                   help="Pico o'rniga simulyator (qo'lda rejim)")
    p.add_argument("--sim-demo", action="store_true",
                   help="simulyator, 45 daqiqalik smena ssenariysi")
    p.add_argument("--machine", default="PRISADKA-01")
    p.add_argument("--kiosk", action="store_true", help="Chrome to'liq ekran")
    p.add_argument("--app", action="store_true", help="Chrome oynasi manzil satrisiz")
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()

    if args.autostart or args.no_autostart:
        return set_autostart(args.autostart)

    print("=" * 58)
    print("  PRISADKA MES - Andon monitor")
    print("=" * 58)

    # ---------- 1. MES serveri (broker + baza + veb) ----------
    if port_busy(WEB_PORT):
        print("  MES serveri allaqachon ishlayapti (port {})".format(WEB_PORT))
    else:
        spawn(["-m", "mes.server"], "MES serveri")
        if not wait_port(WEB_PORT):
            print("  XATO: MES serveri ochilmadi. Oynadagi xabarni qarang.")
            return 1

    # ---------- 2. Ma'lumot manbai: Pico yoki simulyator ----------
    if args.sim or args.sim_demo:
        mode = "demo" if args.sim_demo else "manual"
        spawn(["sim/pico_sim.py", "--mode", mode, "--machine", args.machine],
              "simulyator ({})".format(mode))
    else:
        port = find_pico()
        if port:
            print("  Pico topildi: {}".format(port))
            spawn(["-m", "mes.serial_bridge", "--machine", args.machine],
                  "USB ko'prik")
        else:
            print("  Pico topilmadi (USB ga ulanmagan yoki BOOTSEL rejimida).")
            print("  Ko'prik baribir ishga tushadi - plata ulanishi bilan ")
            print("  avtomatik ulanadi.")
            spawn(["-m", "mes.serial_bridge", "--machine", args.machine],
                  "USB ko'prik (kutish rejimida)")

    # ---------- 3. Chrome ----------
    if not args.no_browser:
        time.sleep(1.5)
        open_chrome("http://localhost:{}".format(WEB_PORT),
                    kiosk=args.kiosk, app=args.app)

    print("-" * 58)
    print("  MES ekrani : http://localhost:{}".format(WEB_PORT))
    print("  MQTT broker: {}".format(MQTT_PORT))
    print("  To'xtatish : stop.py yoki ochilgan oynalarni yopish")
    print("-" * 58)
    return 0


if __name__ == "__main__":
    sys.exit(main())
