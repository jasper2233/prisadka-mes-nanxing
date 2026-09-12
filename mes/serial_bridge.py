"""USB-serial ko'prigi: Pico  <--USB-->  kompyuter  <--MQTT-->  MES.

Wi-Fi'siz Pico (oddiy RP2040) uchun. Pico eventlarni USB kabel orqali
qator-qator yuboradi, shu dastur ularni MQTT ga uzatadi va aksincha —
MES dan kelgan buyruqlarni Pico ga qaytaradi.

Sim protokoli:
    Pico -> bu dastur :  MES <kind> <json>     kind = event | state
    bu dastur -> Pico :  CMD <json>            sozlama o'zgartirish
                         PING                  har 5 s, "men tirikman"

Boshqa qatorlar (print, traceback) jurnalga `[pico]` deb chiqariladi.

Ishga tushirish:
    python -m mes.serial_bridge                 # portni o'zi topadi
    python -m mes.serial_bridge --port COM5
    python -m mes.serial_bridge --list          # portlar ro'yxati
"""

import argparse
import json
import socket
import sys
import time

from .client import Client

PICO_VID = 0x2E8A               # Raspberry Pi (RP2040/RP2350)
PING_EVERY_S = 5
LOCK_PORT = 8765                # ikkinchi nusxa ishga tushmasligi uchun


def singleton_lock():
    """Bitta ko'prik yetarli: ikkinchisi bir xil portni band qila olmaydi.

    Ikkita ko'prik bitta COM portga urinsa, biri xato beradi va eventlar
    aralashib ketardi.
    """
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


# ---------------------------------------------------------------- port topish

def list_ports():
    """(nom, izoh) ro'yxati. pyserial bo'lsa to'liq, bo'lmasa registrdan."""
    out = []
    try:
        from serial.tools import list_ports as lp
        for p in lp.comports():
            out.append((p.device, "{} (VID:{})".format(
                p.description, hex(p.vid) if p.vid else "?")))
        return out
    except ImportError:
        pass
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"HARDWARE\DEVICEMAP\SERIALCOMM")
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            i += 1
            out.append((val, name))
    except Exception:
        pass
    return out


def find_pico():
    """Pico ning COM portini topadi (VID 2E8A bo'yicha)."""
    try:
        from serial.tools import list_ports as lp
        for p in lp.comports():
            if p.vid == PICO_VID:
                return p.device
    except ImportError:
        pass
    # pyserial yo'q: USB seriali bo'lgan birinchi portni olamiz
    for dev, desc in list_ports():
        if "USBSER" in str(desc).upper() or "VCP" in str(desc).upper():
            return dev
    return None


# ---------------------------------------------------------------- port ochish

class Port:
    """pyserial bo'lsa o'shani, bo'lmasa xom fayl I/O ni ishlatadi."""

    def __init__(self, name, baud=115200):
        self.name = name
        try:
            import serial
            self.impl = "pyserial"
            self.s = serial.Serial(name, baud, timeout=0.2)
        except ImportError:
            self.impl = "raw"
            path = name if name.startswith("\\\\") else r"\\.\{}".format(name)
            self.s = open(path, "r+b", buffering=0)

    def readline(self):
        try:
            return self.s.readline()
        except Exception:
            return b""

    def write(self, text):
        data = text.encode("utf-8")
        try:
            self.s.write(data)
            if hasattr(self.s, "flush"):
                self.s.flush()
            return True
        except Exception:
            return False

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


# ---------------------------------------------------------------- ko'prik

class SerialBridge:
    def __init__(self, args):
        self.args = args
        self.machine = args.machine
        self.port = None
        self.mq = None
        self._next_ping = 0
        self.t_event = "mes/andon/{}/event".format(self.machine)
        self.t_state = "mes/andon/{}/state".format(self.machine)
        self.t_online = "mes/andon/{}/online".format(self.machine)
        self.t_cmd = "mes/andon/{}/cmd".format(self.machine)

    # ---------- MQTT ----------
    def connect_mqtt(self):
        self.mq = Client(self.args.host, self.args.mqtt_port,
                         client_id="serial-bridge-" + self.machine,
                         will=(self.t_online, b"0", True),
                         on_message=self.on_mqtt)
        self.mq.connect()
        self.mq.subscribe(self.t_cmd)
        print("MQTT: {}:{}  stanok: {}".format(
            self.args.host, self.args.mqtt_port, self.machine))

    def on_mqtt(self, topic, payload, retained=False):
        """MES -> Pico buyrug'i."""
        try:
            data = json.loads(payload)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        if self.port and self.port.write("CMD " + json.dumps(data) + "\n"):
            print("-> pico: {}".format(data))
        else:
            print("-> pico YUBORILMADI (port yopiq): {}".format(data))

    # ---------- Pico ----------
    def open_port(self):
        name = self.args.port or find_pico()
        if not name:
            return False
        try:
            self.port = Port(name, self.args.baud)
        except Exception as e:
            print("port ochilmadi ({}): {}".format(name, e))
            self.port = None
            return False
        print("Pico porti: {} ({})".format(name, self.port.impl))
        self.mq.publish(self.t_online, b"1", retain=True)
        return True

    def close_port(self, why=""):
        if self.port:
            self.port.close()
            self.port = None
            print("port yopildi {}".format(why))
        try:
            self.mq.publish(self.t_online, b"0", retain=True)
        except Exception:
            pass

    def handle_line(self, line):
        if not line.startswith("MES "):
            text = line.strip()
            if text:
                print("[pico] {}".format(text))
            return
        try:
            _, kind, payload = line.split(" ", 2)
        except ValueError:
            return
        topic = {"event": self.t_event, "state": self.t_state}.get(kind)
        if topic is None:
            return
        try:
            json.loads(payload)              # buzuq JSON ni o'tkazmaymiz
        except Exception:
            print("buzuq JSON: {}".format(payload[:80]))
            return
        self.mq.publish(topic, payload.strip(), retain=(kind == "state"))
        if kind == "event":
            self.log_event(payload)

    def log_event(self, payload):
        try:
            d = json.loads(payload)
        except Exception:
            return
        if d.get("type") == "cycle":
            print("[{}] SIKL kutish={}s ishlov={}s {}".format(
                d.get("seq"), d.get("wait_s"), d.get("process_s"),
                "tugallandi" if d.get("completed") else "TUGALLANMADI"))
        else:
            print("[{}] {} -> {} ({} s)".format(
                d.get("seq"), d.get("prev_state"), d.get("state"),
                d.get("prev_duration_s")))

    # ---------- asosiy tsikl ----------
    def run(self):
        self.connect_mqtt()
        last_try = 0
        while True:
            if self.port is None:
                if time.time() - last_try < 2:
                    time.sleep(0.3)
                    self.mq.check()
                    continue
                last_try = time.time()
                if not self.open_port():
                    print("Pico topilmadi, kutilmoqda... "
                          "(BOOTSEL rejimida emasligini tekshiring)")
                    continue

            try:
                raw = self.port.readline()
            except Exception as e:
                self.close_port("({})".format(e))
                continue
            if raw:
                self.handle_line(raw.decode("utf-8", "replace"))

            if time.time() >= self._next_ping:
                self._next_ping = time.time() + PING_EVERY_S
                if not self.port.write("PING\n"):
                    self.close_port("(yozib bo'lmadi)")
                    continue
            try:
                self.mq.check()
            except Exception as e:
                print("MQTT uzildi ({}), qayta ulanmoqda...".format(e))
                time.sleep(1)
                self.connect_mqtt()


def main():
    p = argparse.ArgumentParser(description="Pico USB-serial -> MQTT ko'prigi")
    p.add_argument("--port", default=None, help="COM porti (bo'sh -> o'zi topadi)")
    p.add_argument("--machine", default="PRISADKA-01")
    p.add_argument("--host", default="127.0.0.1", help="MQTT broker IP")
    p.add_argument("--mqtt-port", type=int, default=1883)
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--list", action="store_true", help="portlar ro'yxatini ko'rsatish")
    args = p.parse_args()

    if args.list:
        ports = list_ports()
        if not ports:
            print("Serial port topilmadi.")
        for dev, desc in ports:
            print("  {:8} {}".format(dev, desc))
        pico = find_pico()
        print("\nPico porti: {}".format(pico or "topilmadi"))
        return 0

    lock = singleton_lock()
    if lock is None:
        print("Ko'prik allaqachon ishlayapti (port {}). Ikkinchisi kerak emas."
              .format(LOCK_PORT))
        return 0

    try:
        import serial           # noqa: F401
    except ImportError:
        print("Eslatma: `pyserial` o'rnatilmagan - xom fayl I/O ishlatiladi.\n"
              "         Ishonchliroq bo'lishi uchun: pip install pyserial\n")

    br = SerialBridge(args)
    try:
        br.run()
    except KeyboardInterrupt:
        print("\nko'prik to'xtatildi")
    finally:
        br.close_port()
        if br.mq:
            br.mq.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
