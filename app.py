"""PrisadkaMES.exe — hammasi bitta faylda, avtozapusk bilan.

Oynasiz ishlaydi (operator tasodifan yopib qo'ymasin), hamma chiqish
`logs/prisadka.log` ga yoziladi. Birinchi ochilganda avtozapuskni yoqishni
so'raydi.

    PrisadkaMES.exe                 MES + USB ko'prik + Chrome
    PrisadkaMES.exe --install       avtozapuskni yoqish va ishga tushirish
    PrisadkaMES.exe --uninstall     avtozapuskni o'chirish va to'xtatish
    PrisadkaMES.exe --stop          ishlab turgan nusxani to'xtatish
    PrisadkaMES.exe --status        holat: avtozapusk, ishlayaptimi, jurnal
    PrisadkaMES.exe --console       jurnalni jonli ko'rish uchun oyna bilan

    PrisadkaMES.exe --sim-demo      Pico'siz sinov: smena ssenariysi
    PrisadkaMES.exe --kiosk         Chrome to'liq ekran (sex monitori)
    PrisadkaMES.exe --no-browser    brauzersiz

Farqi `start.py` dan: u qismlarni alohida jarayonlarda ochadi (ishlab
chiqish uchun), bu esa hammasini bitta jarayonda, oqimlar bilan ishlatadi.
"""

import argparse
import json
import logging
import os
import runpy
import socket
import subprocess
import sys
import threading
import time
import types
from logging.handlers import RotatingFileHandler

APP_NAME = "PrisadkaMES"
MUTEX_NAME = "Local\\PrisadkaMES"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WEB_PORT = 8080
MQTT_PORT = 1883

FROZEN = getattr(sys, "frozen", False)
IS_WIN = os.name == "nt"
# .exe oynasiz qurilgan: konsol yo'q, sys.stdout = None
WINDOWED = FROZEN or sys.__stdout__ is None

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


# ---------------------------------------------------------------- yo'llar

def base_dir():
    """Bundle ichidagi resurslar (ui.html, firmware/, sim/)."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


_DATA_DIR = None


def data_dir():
    """Yozish mumkin bo'lgan joy. Odatda .exe yonida - baza va jurnal shu yerda.

    .exe yozib bo'lmaydigan papkada tursa (masalan Program Files), jim
    yiqilmaslik uchun %LOCALAPPDATA%\\PrisadkaMES ga o'tiladi.
    """
    global _DATA_DIR
    if _DATA_DIR:
        return _DATA_DIR
    d = os.path.dirname(sys.executable) if FROZEN else \
        os.path.dirname(os.path.abspath(__file__))
    try:
        probe = os.path.join(d, ".yozish-sinovi")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except OSError:
        d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME)
        os.makedirs(d, exist_ok=True)
    _DATA_DIR = d
    return d


def app_settings_path():
    return os.path.join(data_dir(), "prisadka-app.json")


def load_app_settings():
    try:
        with open(app_settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_app_settings(s):
    try:
        with open(app_settings_path(), "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("sozlama saqlanmadi: {!r}".format(e))


# ---------------------------------------------------------------- jurnal

_log_lock = threading.Lock()


class _LogStream:
    """print() ni jurnal fayliga yo'naltiradi (bir nechta oqimdan xavfsiz).

    Oynasiz .exe da sys.stdout = None - ba'zi kutubxonalar unga yozmoqchi
    bo'lsa yiqiladi. Shu sababli uni doim haqiqiy obyekt bilan almashtiramiz.
    """

    def __init__(self, logger, level, mirror=None):
        self.logger = logger
        self.level = level
        self.mirror = mirror
        self._buf = ""

    def write(self, s):
        if not s:
            return 0
        with _log_lock:
            if self.mirror is not None:
                try:
                    self.mirror.write(s)
                    self.mirror.flush()
                except Exception:
                    pass
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    self.logger.log(self.level, line.rstrip())
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False


def _open_console():
    """--console: oynasiz .exe ga jurnalni jonli ko'rish uchun oyna ochadi."""
    if sys.__stdout__ is not None:
        return sys.__stdout__
    try:
        import ctypes
        ctypes.windll.kernel32.AllocConsole()
        return open("CONOUT$", "w", encoding="utf-8", buffering=1)
    except Exception:
        return None


def setup_logging(name, console=False):
    log_dir = os.path.join(data_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, name + ".log")
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    h = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(h)
    mirror = _open_console() if console else None
    sys.stdout = _LogStream(logger, logging.INFO, mirror)
    sys.stderr = _LogStream(logger, logging.ERROR, mirror)
    return path


# ---------------------------------------------------------------- Windows

MB_YESNO = 0x04
MB_ICONQUESTION = 0x20
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40
MB_TOPMOST = 0x40000
IDYES = 6


def tell(args, text, flags=MB_ICONINFORMATION):
    """Jurnalga yozadi; konsolsiz qo'lda ishga tushirilgan bo'lsa oyna ham ko'rsatadi."""
    print(text.replace("\n\n", "\n"))
    if not getattr(args, "dialogs", False):
        return 0
    try:
        import ctypes
        return ctypes.windll.user32.MessageBoxW(None, text, "PRISADKA MES",
                                                flags | MB_TOPMOST)
    except Exception:
        return 0


_MUTEX = None


def acquire_single_instance():
    """Bitta kompyuterda bitta nusxa. Ikkinchisi port uchun urishmasin."""
    global _MUTEX
    if not IS_WIN:
        return not port_busy(WEB_PORT)
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    _MUTEX = k.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != 183          # ERROR_ALREADY_EXISTS


def instance_running():
    if not IS_WIN:
        return port_busy(WEB_PORT)
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenMutexW.restype = ctypes.c_void_p
    k.OpenMutexW.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_wchar_p]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenMutexW(0x00100000, False, MUTEX_NAME)  # SYNCHRONIZE
    if h:
        k.CloseHandle(h)
        return True
    return False


def _self_command():
    """Shu dasturni qayta chaqirish uchun buyruq (.exe yoki pythonw app.py)."""
    if FROZEN:
        return [sys.executable]
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return [pyw if os.path.exists(pyw) else sys.executable, os.path.abspath(__file__)]


def autostart_flags(args):
    flags = ["--autostart"]
    if args.no_browser:
        flags.append("--no-browser")
    if args.kiosk:
        flags.append("--kiosk")
    return flags


def autostart_command(args):
    return " ".join('"{}"'.format(p) for p in _self_command()) + " " + \
        " ".join(autostart_flags(args))


def autostart_get():
    if not IS_WIN:
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, APP_NAME)[0]
    except OSError:
        return None


def autostart_set(cmd):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)


def autostart_remove():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, APP_NAME)
        return True
    except OSError:
        return False


def child_env():
    """O'zini qayta chaqirganda yangi nusxa o'z vaqtinchalik papkasini ochsin.

    Bitta faylli .exe o'zini %TEMP%\\_MEIxxxx ga ochadi. Bu o'zgaruvchisiz
    bola jarayon OTASINING papkasini meros qilib oladi - ota chiqib o'sha
    papkani o'chirganda, bola hali modul yuklayotgan bo'ladi va
    `No module named '_overlapped'` bilan yiqiladi (--install da aynan
    shunday bo'ldi).
    """
    env = dict(os.environ)
    if FROZEN:
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def spawn_detached(extra):
    subprocess.Popen(_self_command() + extra, cwd=data_dir(), close_fds=True,
                     env=child_env(),
                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)


def _exe_pids():
    """PrisadkaMES.exe jarayonlari (o'zidan tashqari).

    `tasklist /FO CSV` ishlatiladi: xabarlar Windows tiliga qarab o'zgaradi
    (bu kompyuterda ruscha), CSV qatorlari esa har doim bir xil.
    """
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq {}.exe".format(APP_NAME),
                        "/FO", "CSV", "/NH"],
                       capture_output=True, encoding="oem", errors="replace",
                       creationflags=CREATE_NO_WINDOW)
    # Bitta faylli .exe ikki jarayon: yuklovchi (ota) + Python (bola). O'zimizni
    # ham, o'z yuklovchimizni ham chetlab o'tamiz - aks holda --stop o'z
    # yuklovchisini o'ldiradi va Windows job obyekti orqali o'zi ham yopiladi.
    mine = {os.getpid(), os.getppid()}
    pids = []
    for ln in (r.stdout or "").splitlines():
        cols = [c.strip('"') for c in ln.split('","')]
        if len(cols) > 1 and cols[0].lower() == APP_NAME.lower() + ".exe" \
                and cols[1].isdigit() and int(cols[1]) not in mine:
            pids.append(int(cols[1]))
    return pids


def stop_other_instances():
    """Shu jarayondan boshqa hamma nusxani to'xtatadi. Nechtasi to'xtaganini qaytaradi."""
    me = os.getpid()
    if FROZEN:
        pids = _exe_pids()
        for pid in pids:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True,
                           creationflags=CREATE_NO_WINDOW)
        n = len(pids)
    else:
        ps = ("Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -match "
              "'app\\.py' -and $_.ProcessId -ne {} }} | ForEach-Object {{ "
              "Stop-Process -Id $_.ProcessId -Force; 'x' }}").format(me)
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
        n = (r.stdout or "").count("x")
    for _ in range(40):                     # port bo'shashini kutamiz
        if not port_busy(WEB_PORT) and not instance_running():
            break
        time.sleep(0.25)
    return n


# ---------------------------------------------------------------- tarmoq

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


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


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


def start_server(args):
    t = threading.Thread(target=server_thread, args=(args,), daemon=True,
                         name="mes-server")
    t.start()
    return t


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
    cmd = _self_command() + ["--sim-worker"] if FROZEN else \
        [sys.executable, os.path.join(base_dir(), "sim", "pico_sim.py")]
    cmd += ["--mode", mode, "--machine", args.machine,
            "--mes", "http://127.0.0.1:{}".format(args.http_port)]
    flags = CREATE_NO_WINDOW if WINDOWED else subprocess.CREATE_NEW_CONSOLE
    subprocess.Popen(cmd, env=child_env(), creationflags=flags if IS_WIN else 0)
    print("simulyator ishga tushdi ({} rejim)".format(mode))


def run_sim_worker():
    """--sim-worker: shu jarayon simulyatorga aylanadi."""
    path = os.path.join(base_dir(), "sim", "pico_sim.py")
    sys.argv = [path] + [a for a in sys.argv[1:] if a != "--sim-worker"]
    sys.path.insert(0, base_dir())
    runpy.run_path(path, run_name="__main__")


def open_chrome(url, kiosk=False):
    exe = next((p for p in CHROME_PATHS if os.path.exists(p)), None)
    extra = (["--kiosk"] if kiosk else []) + [url]
    try:
        if exe:
            subprocess.Popen([exe] + extra)
            print("Chrome ochildi: {}".format(url))
        else:
            import webbrowser
            webbrowser.open(url)
            print("Chrome topilmadi - standart brauzerda ochildi: {}".format(url))
    except Exception as e:
        print("brauzer ochilmadi: {!r}".format(e))


def offer_autostart(args):
    """Birinchi marta qo'lda ochilganda avtozapuskni taklif qiladi (bir marta)."""
    if not (FROZEN and IS_WIN and args.dialogs) or args.sim or args.sim_demo:
        return
    s = load_app_settings()
    if autostart_get() or s.get("autostart_asked"):
        return
    s["autostart_asked"] = True
    save_app_settings(s)
    ans = tell(args,
               "Kompyuter yoqilganda PRISADKA MES avtomatik ishga tushsinmi?\n\n"
               "Fayl joyi:\n{}\n\n"
               "Ha desangiz, bu faylni boshqa papkaga ko'chirmang.\n"
               "Keyin o'chirish:  PrisadkaMES.exe --uninstall".format(sys.executable),
               MB_YESNO | MB_ICONQUESTION)
    if ans == IDYES:
        autostart_set(autostart_command(args))
        tell(args, "Avtozapusk yoqildi.")


# ---------------------------------------------------------------- buyruqlar

def cmd_install(args):
    if not IS_WIN:
        print("Avtozapusk faqat Windows uchun.")
        return 1
    cmd = autostart_command(args)
    autostart_set(cmd)
    print("avtozapusk yozildi: {}".format(cmd))
    started = False
    if not instance_running():
        spawn_detached(autostart_flags(args))
        started = True
    tell(args,
         "Avtozapusk yoqildi.\n\n"
         "Kompyuter yoqilganda PRISADKA MES o'zi ishga tushadi.\n{}\n\n"
         "Fayl: {}\nBu faylni boshqa papkaga ko'chirmang.".format(
             "Hozir ham ishga tushirildi." if started else "Dastur allaqachon ishlab turibdi.",
             _self_command()[-1]))
    return 0


def cmd_uninstall(args):
    removed = autostart_remove() if IS_WIN else False
    n = stop_other_instances()
    tell(args, "Avtozapusk {}.\nTo'xtatilgan nusxalar: {}".format(
        "o'chirildi" if removed else "yoqilmagan edi", n))
    return 0


def cmd_stop(args):
    n = stop_other_instances()
    tell(args, "PRISADKA MES to'xtatildi." if n else "Ishlab turgan nusxa topilmadi.")
    return 0


def cmd_status(args):
    reg = autostart_get()
    running = instance_running()
    tell(args,
         "Ishlayapti: {}\nAvtozapusk: {}\n\nMES ekrani: http://localhost:{}\n"
         "Baza: {}\nJurnal: {}".format(
             "ha" if running else "yo'q",
             reg if reg else "yoqilmagan",
             WEB_PORT,
             os.path.join(data_dir(), "mes-data.db"),
             os.path.join(data_dir(), "logs", "prisadka.log")))
    return 0 if running else 1


def cmd_run(args):
    if args.db is None:
        args.db = os.path.join(data_dir(), "mes-data.db")
    url = "http://localhost:{}".format(args.http_port)

    if not acquire_single_instance():
        print("PRISADKA MES allaqachon ishlayapti.")
        if not args.autostart and not args.no_browser:
            open_chrome(url, args.kiosk)      # ikkinchi marta bosilsa - ekranni ochamiz
        return 0

    if port_busy(args.http_port):
        tell(args, "Port {} boshqa dastur tomonidan band.\n\n"
                   "PRISADKA MES ishga tushmadi.".format(args.http_port), MB_ICONWARNING)
        return 1

    print("=" * 58)
    print("PRISADKA MES ishga tushmoqda{}".format(" (avtozapusk)" if args.autostart else ""))
    print("papka: {}".format(data_dir()))

    server = start_server(args)
    if not wait_port(args.http_port):
        tell(args, "MES serveri ochilmadi. Jurnalni qarang:\n{}".format(args.log_path),
             MB_ICONWARNING)
        return 1

    if args.sim or args.sim_demo:
        start_simulator(args)
    else:
        threading.Thread(target=bridge_thread, args=(args,), daemon=True,
                         name="usb-bridge").start()

    print("MES ekrani : {}".format(url))
    print("tarmoqdan  : http://{}:{}".format(local_ip(), args.http_port))
    print("baza       : {}".format(args.db))
    print("=" * 58)

    if not args.no_browser:
        # avtozapuskda ish stoli to'liq yuklanishiga ozgina vaqt beramiz
        time.sleep(4 if args.autostart else 1)
        open_chrome(url, args.kiosk)

    threading.Thread(target=offer_autostart, args=(args,), daemon=True).start()

    # ---- nazorat: server oqimi yiqilsa, qayta ishga tushiramiz ----
    restarts = 0
    try:
        while True:
            time.sleep(5)
            if server.is_alive():
                if restarts and port_busy(args.http_port):
                    print("MES serveri tiklandi")
                    restarts = 0
                continue
            restarts += 1
            wait = min(60, 5 * restarts)
            print("MES serveri to'xtab qoldi - {} s dan keyin qayta ishga "
                  "tushiriladi ({}-urinish)".format(wait, restarts))
            time.sleep(wait)
            server = start_server(args)
    except KeyboardInterrupt:
        print("to'xtatildi")
    return 0


def main():
    console = "--console" in sys.argv

    if "--sim-worker" in sys.argv:
        if WINDOWED:
            setup_logging("simulyator", console)
        return run_sim_worker()

    log_path = setup_logging("prisadka", console) if WINDOWED else None

    p = argparse.ArgumentParser(prog=APP_NAME, description="PRISADKA MES - Andon monitor")
    g = p.add_argument_group("boshqaruv")
    g.add_argument("--install", action="store_true", help="avtozapuskni yoqish")
    g.add_argument("--uninstall", action="store_true", help="avtozapuskni o'chirish")
    g.add_argument("--stop", action="store_true", help="ishlab turgan nusxani to'xtatish")
    g.add_argument("--status", action="store_true", help="holatni ko'rsatish")
    g.add_argument("--autostart", action="store_true", help=argparse.SUPPRESS)
    g.add_argument("--silent", action="store_true", help="dialog oynalarsiz")
    g.add_argument("--console", action="store_true", help="jurnalni oynada ko'rsatish")
    r = p.add_argument_group("ishlash")
    r.add_argument("--sim", action="store_true", help="Pico o'rniga simulyator")
    r.add_argument("--sim-demo", action="store_true", help="simulyator, smena ssenariysi")
    r.add_argument("--machine", default="PRISADKA-01")
    r.add_argument("--port", default=None, help="COM porti (bo'sh - o'zi topadi)")
    r.add_argument("--mqtt-port", type=int, default=MQTT_PORT)
    r.add_argument("--http-port", type=int, default=WEB_PORT)
    r.add_argument("--db", default=None)
    r.add_argument("--kiosk", action="store_true", help="Chrome to'liq ekran")
    r.add_argument("--no-browser", action="store_true", help="brauzer ochmaslik")
    args = p.parse_args()

    # dialog oynalar faqat odam qo'lda, konsolsiz ochganda kerak
    args.dialogs = WINDOWED and not console and not args.silent and not args.autostart
    args.log_path = log_path

    if args.install:
        return cmd_install(args)
    if args.uninstall:
        return cmd_uninstall(args)
    if args.stop:
        return cmd_stop(args)
    if args.status:
        return cmd_status(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
