"""PrisadkaMES.exe ni qurish.

    python build_exe.py

Natija: `dist/PrisadkaMES.exe` — Python o'rnatilmagan kompyuterda ham
ishlaydigan bitta fayl (~9 MB). Ichida: MQTT broker, SQLite ko'prik,
veb-interfeys, USB ko'prik va Pico simulyatori.

Talab: `pip install pyinstaller`
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "PrisadkaMES"

# Bundle ichiga qo'shiladigan fayllar. Firmware modullari simulyator uchun
# kerak - u haqiqiy fsm.py va lamps.py kodini ishlatadi.
DATA = [
    ("mes/ui.html", "mes"),
    ("firmware/config.py", "firmware"),
    ("firmware/lamps.py", "firmware"),
    ("firmware/fsm.py", "firmware"),
    ("firmware/settings.py", "firmware"),
    ("sim/pico_sim.py", "sim"),
]


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller yo'q. O'rnating:  pip install pyinstaller")
        return 1

    missing = [src for src, _ in DATA if not os.path.exists(os.path.join(ROOT, src))]
    if missing:
        print("Fayllar topilmadi: {}".format(", ".join(missing)))
        return 1

    # config.py da real parol bo'lishi mumkin - bundle ga tushmasin.
    cfg = os.path.join(ROOT, "firmware", "config.py")
    src = cfg if os.path.exists(cfg) else os.path.join(ROOT, "firmware",
                                                       "config.example.py")
    if src != cfg:
        print("Eslatma: firmware/config.py yo'q, config.example.py ishlatiladi.")

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onefile", "--console", "--name", NAME]
    for rel, dest in DATA:
        cmd += ["--add-data", "{}{}{}".format(rel, os.pathsep, dest)]
    cmd += ["--hidden-import", "serial.tools.list_ports", "app.py"]

    print("Qurilmoqda... (birinchi marta 1-2 daqiqa)")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode:
        print("Qurish muvaffaqiyatsiz tugadi.")
        return r.returncode

    exe = os.path.join(ROOT, "dist", NAME + ".exe")
    size = os.path.getsize(exe) / 1048576
    print("-" * 54)
    print("  Tayyor: {}".format(exe))
    print("  Hajmi : {:.1f} MB".format(size))
    print()
    print("  Sex kompyuteriga shu bitta faylni ko'chiring.")
    print("  Baza (mes-data.db) .exe yonida hosil bo'ladi.")
    print("-" * 54)

    # oraliq fayllar kerak emas
    shutil.rmtree(os.path.join(ROOT, "build"), ignore_errors=True)
    spec = os.path.join(ROOT, NAME + ".spec")
    if os.path.exists(spec):
        os.remove(spec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
