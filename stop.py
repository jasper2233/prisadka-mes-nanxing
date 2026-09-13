"""MES ning barcha qismlarini to'xtatadi (server, ko'prik, simulyator).

    python stop.py
"""

import subprocess
import sys

TARGETS = ("mes.server", "mes.serial_bridge", "pico_sim", "app.py")

PS = r"""
Get-CimInstance Win32_Process | Where-Object { $_.Name -in 'python.exe','pythonw.exe','PrisadkaMES.exe' } | ForEach-Object {
  $c = $_.CommandLine
  if ($_.Name -eq 'PrisadkaMES.exe' -or $c -and ($c -match 'mes\.server' -or $c -match 'mes\.serial_bridge' -or $c -match 'pico_sim' -or $c -match 'app\.py')) {
    Write-Output "to'xtatildi: PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
}
"""


def main():
    if sys.platform != "win32":
        print("Bu skript Windows uchun. Boshqa tizimda oynalarni qo'lda yoping.")
        return 1
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS],
        capture_output=True, text=True)
    text = (out.stdout or "").strip()
    print(text if text else "Ishlab turgan MES jarayoni topilmadi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
