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
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "PrisadkaMES"

# Bundle ichiga qo'shiladigan fayllar. Firmware modullari simulyator uchun
# kerak - u haqiqiy fsm.py va lamps.py kodini ishlatadi.
DATA = [
    ("mes/ui.html", "mes"),
    ("firmware/lamps.py", "firmware"),
    ("firmware/fsm.py", "firmware"),
    ("firmware/settings.py", "firmware"),
    ("sim/pico_sim.py", "sim"),
]

# config.py o'rniga HAR DOIM config.example.py bundle qilinadi (config.py
# nomi bilan). Ikki sabab: config.py da real Wi-Fi paroli bor va u .exe
# orqali tarqalmasligi kerak; u .gitignore da, ya'ni yangi klonda umuman
# yo'q. Simulyatorga faqat pin va vaqt sozlamalari kerak - ular bir xil.
CONFIG_TEMPLATE = "firmware/config.example.py"


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller yo'q. O'rnating:  pip install pyinstaller")
        return 1

    needed = [src for src, _ in DATA] + [CONFIG_TEMPLATE]
    missing = [src for src in needed if not os.path.exists(os.path.join(ROOT, src))]
    if missing:
        print("Fayllar topilmadi: {}".format(", ".join(missing)))
        return 1

    stage = tempfile.mkdtemp(prefix="prisadka-bundle-")
    stage_cfg = os.path.join(stage, "config.py")
    shutil.copyfile(os.path.join(ROOT, CONFIG_TEMPLATE), stage_cfg)

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onefile", "--console", "--name", NAME]
    for rel, dest in DATA:
        cmd += ["--add-data", "{}{}{}".format(rel, os.pathsep, dest)]
    cmd += ["--add-data", "{}{}firmware".format(stage_cfg, os.pathsep)]
    cmd += ["--hidden-import", "serial.tools.list_ports", "app.py"]

    print("Qurilmoqda... (birinchi marta 1-2 daqiqa)")
    try:
        r = subprocess.run(cmd, cwd=ROOT)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
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
