"""Link (tarmoq qatlami) ni CPython'da sinash.

`network` va `umqtt.simple` faqat Pico'da bor, shuning uchun ular soxta
modullar bilan almashtiriladi. Bu yerda tekshiriladigan narsa - eventlarni
yo'qotmaslik mantiqi: oflayn bufer, retained snapshot, bloklamaydigan Wi-Fi.

Ishga tushirish:  python3 tests/test_link.py
"""

import os
import sys
import types

# ---- soxta MicroPython 'time' moduli (link.py import qilishidan oldin) ----
t = types.ModuleType("time")
t.NOW = [0]
t.ticks_ms = lambda: t.NOW[0]
t.ticks_diff = lambda a, b: a - b
t.ticks_add = lambda a, b: a + b
t.time = lambda: 1757490000
t.gmtime = lambda x=0: (1970, 1, 1, 0, 0, 0, 3, 1)
t.sleep_ms = lambda ms: None
sys.modules["time"] = t

# ---- soxta 'network' ----
_net = types.ModuleType("network")
_net.STA_IF = 0


class FakeWlan:
    def __init__(self, *a):
        self.connected = False
        self.connects = []

    def active(self, v=None):
        return True

    def isconnected(self):
        return self.connected

    def connect(self, ssid, password):
        self.connects.append((t.NOW[0], ssid))

    def status(self, what):
        return -55


_net.WLAN = FakeWlan
sys.modules["network"] = _net

# ---- soxta 'umqtt.simple' ----
_umqtt = types.ModuleType("umqtt")
_simple = types.ModuleType("umqtt.simple")
_simple.socket = types.ModuleType("socket")     # shim shu modul o'rnini bosadi


class FakeMQTTClient:
    def __init__(self, *a, **kw):
        self.published = []

    def set_callback(self, cb):
        pass

    def set_last_will(self, *a, **kw):
        pass

    def connect(self):
        pass

    def subscribe(self, *a, **kw):
        pass

    def publish(self, topic, msg, retain=False, qos=0):
        self.published.append((topic, msg, retain))


_simple.MQTTClient = FakeMQTTClient
_umqtt.simple = _simple
sys.modules["umqtt"] = _umqtt
sys.modules["umqtt.simple"] = _simple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "firmware"))
import link as linkmod  # noqa: E402


class Cfg:
    MACHINE_ID = "PRISADKA-01"
    SITE = "SEX-1"
    WIFI_SSID = "TEST-WIFI"
    WIFI_PASS = "x"
    WIFI_TIMEOUT_S = 15
    MQTT_HOST = "10.0.0.1"
    MQTT_PORT = 1883
    MQTT_USER = None
    MQTT_PASS = None
    MQTT_KEEPALIVE = 60
    MQTT_SOCKET_TIMEOUT_S = 2
    TOPIC_EVENT = "mes/andon/{}/event"
    TOPIC_STATE = "mes/andon/{}/state"
    TOPIC_ONLINE = "mes/andon/{}/online"
    TOPIC_CMD = "mes/andon/{}/cmd"
    BUFFER_MAX = 10
    RECONNECT_MIN_MS = 1000
    RECONNECT_MAX_MS = 30000
    NTP_HOST = "10.0.0.1"
    NTP_RESYNC_S = 3600


def new_link():
    t.NOW[0] = 0
    return linkmod.Link(Cfg)


# ---------------------------------------------------------------- testlar

def test_retained_snapshot_is_replaced_not_stacked():
    """Oflayn paytdagi snapshot'lar to'planmasligi kerak - faqat oxirgisi qoladi.

    Aks holda har 30 sekundda bittadan snapshot RAM ni to'ldiradi va
    haqiqiy eventlarni buferdan siqib chiqaradi.
    """
    lk = new_link()
    for i in range(50):
        lk.enqueue(lk.t_state, {"n": i}, retain=True)

    assert len(lk.buf) == 1, lk.buf
    assert lk.dropped == 0
    assert '"n": 49' in lk.buf[0][1] or '"n":49' in lk.buf[0][1], lk.buf[0]


def test_events_are_not_replaced():
    """Oddiy eventlar (retain=False) navbatda saqlanadi, almashtirilmaydi."""
    lk = new_link()
    for i in range(3):
        lk.enqueue(lk.t_event, {"seq": i})
    assert len(lk.buf) == 3, lk.buf


def test_buffer_drops_oldest_and_counts():
    """Bufer to'lsa eng eskisi tashlanadi va `dropped` sanaydi."""
    lk = new_link()
    for i in range(Cfg.BUFFER_MAX + 3):
        lk.enqueue(lk.t_event, {"seq": i})

    assert len(lk.buf) == Cfg.BUFFER_MAX
    assert lk.dropped == 3
    first = lk.buf[0][1]
    assert '"seq": 3' in first or '"seq":3' in first, first


def test_snapshot_does_not_crowd_out_events():
    """Snapshot va eventlar aralash kelganda eventlar yo'qolmaydi."""
    lk = new_link()
    for i in range(Cfg.BUFFER_MAX - 1):
        lk.enqueue(lk.t_event, {"seq": i})
    for _ in range(100):
        lk.enqueue(lk.t_state, {"snap": True}, retain=True)

    events = [b for b in lk.buf if not b[2]]
    snaps = [b for b in lk.buf if b[2]]
    assert len(events) == Cfg.BUFFER_MAX - 1, len(events)
    assert len(snaps) == 1
    assert lk.dropped == 0


def test_flush_sends_in_order_and_clears():
    lk = new_link()
    lk.mq = FakeMQTTClient()
    for i in range(3):
        lk.enqueue(lk.t_event, {"seq": i})
    assert lk._flush() is True
    assert lk.buf == []
    assert [p[0] for p in lk.mq.published] == [lk.t_event] * 3


def test_ntp_host_must_be_ip():
    """DNS nomi bloklaydi - shuning uchun faqat IP qabul qilinadi."""
    assert linkmod._is_ip("10.0.0.1") is True
    assert linkmod._is_ip("pool.ntp.org") is False
    assert linkmod._is_ip("192.168.10") is False
    assert linkmod._is_ip("192.168.10.999") is False


def test_wifi_does_not_block():
    """_wifi_ready darhol qaytadi va connect() ni qayta-qayta chaqirmaydi."""
    lk = new_link()
    lk.wlan.connected = False

    assert lk._wifi_ready(t.NOW[0]) is False
    assert len(lk.wlan.connects) == 1

    t.NOW[0] += 5000                      # limit ichida - qayta urinmaydi
    assert lk._wifi_ready(t.NOW[0]) is False
    assert len(lk.wlan.connects) == 1

    t.NOW[0] += 20000                     # limitdan oshdi - qayta uriniladi
    assert lk._wifi_ready(t.NOW[0]) is False
    assert len(lk.wlan.connects) == 2

    lk.wlan.connected = True
    assert lk._wifi_ready(t.NOW[0]) is True
    assert lk._wifi_at is None


def test_pump_without_wifi_returns_quickly():
    """Tarmoq yo'q paytda pump() bloklamaydi va tez-tez qayta tekshiradi."""
    lk = new_link()
    lk.wlan.connected = False
    lk.pump()
    assert lk.mq is None
    assert lk._next_try == 500            # 500 ms dan keyin, 15 s kutmasdan


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
