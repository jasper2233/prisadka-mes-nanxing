"""USB-serial transport testlari (Pico tomoni + kompyuter tomoni).

Wi-Fi'siz Pico eventlarni USB orqali yuboradi. Bu yerda ikkala uchi ham
sinaladi: `firmware/link_serial.py` (qurilmada) va `mes/serial_bridge.py`
(kompyuterda) — haqiqiy temir va COM portsiz.

Ishga tushirish:  python3 tests/test_serial.py
"""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# MUHIM: ko'prik soxta `time` qo'yilishidan OLDIN import qilinadi
# (u asyncio/socket ga bog'liq, ular esa haqiqiy `time` ni talab qiladi).
from mes.serial_bridge import SerialBridge          # noqa: E402

# ---- soxta MicroPython muhiti ----
t = types.ModuleType("time")
t.NOW = [0]
t.ticks_ms = lambda: t.NOW[0]
t.ticks_diff = lambda a, b: a - b
t.ticks_add = lambda a, b: a + b
sys.modules["time"] = t


class FakePoll:
    def __init__(self):
        self.obj = None

    def register(self, obj, events):
        self.obj = obj

    def poll(self, timeout=0):
        return [(self.obj, 1)] if getattr(self.obj, "data", "") else []


_sel = types.ModuleType("select")
_sel.POLLIN = 1
_sel.poll = FakePoll
sys.modules["select"] = _sel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "firmware"))
import link_serial                                   # noqa: E402


class FakeIn:
    def __init__(self):
        self.data = ""

    def feed(self, s):
        self.data += s

    def read(self, n):
        if not self.data:
            return ""
        out, self.data = self.data[:n], self.data[n:]
        return out


class FakeOut:
    def __init__(self):
        self.chunks = []

    def write(self, s):
        self.chunks.append(s)

    def lines(self):
        return "".join(self.chunks).splitlines()


class Cfg:
    BUFFER_MAX = 5
    SERIAL_HOST_TIMEOUT_MS = 15000


def new_link(on_cmd=None):
    t.NOW[0] = 100000
    link_serial.sys = types.SimpleNamespace(stdin=FakeIn(), stdout=FakeOut())
    lk = link_serial.SerialLink(Cfg, on_cmd=on_cmd)
    return lk, link_serial.sys.stdin, link_serial.sys.stdout


# ---------------------------------------------------------------- Pico tomoni

def test_starts_offline_and_buffers():
    """Ko'prik gapirmaguncha qurilma oflayn - eventlar buferda saqlanadi."""
    lk, _, out = new_link()
    assert lk.online is False
    lk.enqueue("event", {"seq": 1})
    lk.enqueue("event", {"seq": 2})
    lk.pump()
    assert out.lines() == [], out.lines()
    assert len(lk.buf) == 2


def test_ping_brings_online_and_flushes():
    """PING kelishi bilan onlayn bo'ladi va navbat bo'shaydi."""
    lk, stdin, out = new_link()
    lk.enqueue("event", {"seq": 1})
    lk.enqueue("event", {"seq": 2})

    stdin.feed("PING\n")
    lk.pump()

    assert lk.online is True
    lines = out.lines()
    assert len(lines) == 2, lines
    assert lines[0].startswith("MES event "), lines[0]
    assert '"seq": 1' in lines[0] or '"seq":1' in lines[0]
    assert lk.buf == []


def test_goes_offline_when_host_silent():
    """Ko'prik jim qolsa (kabel uzildi), qurilma yana oflayn bo'ladi."""
    lk, stdin, _ = new_link()
    stdin.feed("PING\n")
    lk.pump()
    assert lk.online is True

    t.NOW[0] += Cfg.SERIAL_HOST_TIMEOUT_MS + 1
    assert lk.online is False

    lk.enqueue("event", {"seq": 9})
    lk.pump()
    assert len(lk.buf) == 1, "oflayn paytda yuborilmasligi kerak"


def test_cmd_is_parsed_and_applied():
    got = []
    lk, stdin, _ = new_link(on_cmd=got.append)
    stdin.feed('CMD {"idle_timeout_s": 600}\n')
    lk.pump()
    assert got == [{"idle_timeout_s": 600}], got


def test_partial_line_is_assembled():
    """Qator bo'lak-bo'lak kelsa ham to'g'ri yig'ilishi kerak."""
    got = []
    lk, stdin, _ = new_link(on_cmd=got.append)
    stdin.feed('CMD {"reset_')
    lk.pump()
    assert got == []
    stdin.feed('counter": true}\n')
    lk.pump()
    assert got == [{"reset_counter": True}], got


def test_garbage_does_not_break_link():
    """Shovqin va buzuq JSON aloqani buzmasligi kerak.

    `_read()` bitta chaqiruvda ko'pi bilan 256 belgi o'qiydi - asosiy tsikl
    sekinlashmasin. Shuning uchun uzun axlatni bir necha pump() tozalaydi.
    """
    got = []
    lk, stdin, _ = new_link(on_cmd=got.append)
    stdin.feed("x" * 600 + "\n")             # 512 dan uzun shovqin
    stdin.feed("CMD not-json\n")
    stdin.feed("PING\n")
    for _ in range(10):
        lk.pump()
    assert lk.online is True
    assert got == [], got


def test_snapshot_is_replaced_not_stacked():
    lk, stdin, out = new_link()
    for i in range(20):
        lk.enqueue("state", {"n": i}, retain=True)
    assert len(lk.buf) == 1
    stdin.feed("PING\n")
    lk.pump()
    lines = out.lines()
    assert len(lines) == 1 and ("19" in lines[0]), lines


def test_buffer_cap_drops_oldest():
    lk, _, _ = new_link()
    for i in range(Cfg.BUFFER_MAX + 3):
        lk.enqueue("event", {"seq": i})
    assert len(lk.buf) == Cfg.BUFFER_MAX
    assert lk.dropped == 3


# ---------------------------------------------------------- kompyuter tomoni

class FakeMq:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))

    def check(self):
        pass


class FakePort:
    def __init__(self):
        self.written = []

    def write(self, text):
        self.written.append(text)
        return True

    def close(self):
        pass


def new_bridge():
    args = types.SimpleNamespace(machine="PRISADKA-01", host="127.0.0.1",
                                 mqtt_port=1883, port=None, baud=115200)
    br = SerialBridge(args)
    br.mq = FakeMq()
    br.port = FakePort()
    return br


def test_bridge_routes_event_and_state():
    br = new_bridge()
    br.handle_line('MES event {"type": "state", "seq": 5, "state": "FAULT"}\n')
    br.handle_line('MES state {"type": "snapshot", "state": "FAULT"}\n')

    topics = [p[0] for p in br.mq.published]
    assert topics == ["mes/andon/PRISADKA-01/event",
                      "mes/andon/PRISADKA-01/state"], topics
    assert br.mq.published[0][2] is False          # event retained emas
    assert br.mq.published[1][2] is True           # snapshot retained


def test_bridge_ignores_log_lines():
    """Pico ning oddiy print() lari MQTT ga tushmasligi kerak."""
    br = new_bridge()
    br.handle_line("PRISADKA-01 sessiya=a3f19c kutish limiti=900 s\n")
    br.handle_line("Traceback (most recent call last):\n")
    assert br.mq.published == []


def test_bridge_rejects_broken_json():
    br = new_bridge()
    br.handle_line('MES event {"seq": 5, buzuq\n')
    assert br.mq.published == []


def test_bridge_forwards_cmd_to_pico():
    br = new_bridge()
    br.on_mqtt("mes/andon/PRISADKA-01/cmd", b'{"idle_timeout_s": 600}')
    assert br.port.written == ['CMD {"idle_timeout_s": 600}\n'], br.port.written


def test_bridge_ignores_cmd_when_port_closed():
    br = new_bridge()
    br.port = None
    br.on_mqtt("mes/andon/PRISADKA-01/cmd", b'{"reboot": true}')   # yiqilmasin


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print("  OK    {}".format(fn.__name__))
        except AssertionError as e:
            failed += 1
            print("  XATO  {}\n        {}".format(fn.__name__, e))
    print("\n{}/{} test o'tdi".format(len(tests) - failed, len(tests)))
    sys.exit(1 if failed else 0)
