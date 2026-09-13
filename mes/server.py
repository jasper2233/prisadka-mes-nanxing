"""Vaqtinchalik MES: broker + ko'prik + veb - bitta jarayonda.

Ishga tushirish:
    python -m mes.server

Keyin:
    http://localhost:8080        - MES ekrani
    mqtt://<shu-kompyuter-IP>:1883 - Pico shu manzilga ulanadi
"""

import argparse
import asyncio
import os
import socket

from . import bridge as bridge_mod
from . import broker as broker_mod
from . import db
from . import telegram
from . import web as web_mod


def local_ip():
    """Tashqi interfeysdagi IP - Pico config.py ga shuni yozish kerak."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


async def run(args):
    db_path = args.db or db.DEFAULT_PATH
    con = db.connect(db_path)

    # Telegram: bazaning yonida telegram.json bo'lsa yoqiladi (ichida token bor,
    # shuning uchun .gitignore da va .exe ga qo'shilmaydi)
    tg_path = getattr(args, "telegram", None) or os.path.join(
        os.path.dirname(os.path.abspath(db_path)), "telegram.json")
    tg = telegram.load_bot(tg_path, db_path)
    notify = tg.notify if tg else None
    bk = broker_mod.Broker(port=args.mqtt_port)
    br = bridge_mod.Bridge(con, notify=notify)
    br.attach(bk)
    wb = web_mod.Web(con, bk, port=args.http_port, notify=notify)

    try:
        mqtt_srv = await bk.serve()
        http_srv = await wb.serve()
    except OSError as e:
        print("Port band ({}). MES serveri allaqachon ishlayaptimi?".format(e))
        print("Tekshirish: http://localhost:{}".format(args.http_port))
        return

    if tg:
        tg.start()

    if getattr(args, "quiet", False):
        # .exe ichida app.py o'z bannerini chiqaradi - ikki marta kerak emas
        async with mqtt_srv, http_srv:
            await asyncio.Event().wait()
        return

    ip = local_ip()
    print("-" * 62)
    print("  MES ekrani   : http://localhost:{}".format(args.http_port))
    print("  MQTT broker  : {}:{}".format(ip, args.mqtt_port))
    print("  Baza         : {}".format(args.db or db.DEFAULT_PATH))
    print()
    print("  Pico config.py:  MQTT_HOST = \"{}\"".format(ip))
    print("  To'xtatish    :  Ctrl+C")
    print("-" * 62)

    async with mqtt_srv, http_srv:
        await asyncio.Event().wait()


def main():
    p = argparse.ArgumentParser(description="Prisadka MES (prototip)")
    p.add_argument("--mqtt-port", type=int, default=1883)
    p.add_argument("--http-port", type=int, default=8080)
    p.add_argument("--db", default=None, help="SQLite fayl yo'li")
    args = p.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nMES to'xtatildi.")


if __name__ == "__main__":
    main()
