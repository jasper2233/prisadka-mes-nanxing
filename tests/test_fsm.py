"""FSM ni CPython'da sinash.

MicroPython'ning time.ticks_* funksiyalari yo'q, shuning uchun soxta 'time'
moduli sys.modules ga qo'yiladi. Shu tarzda Pico'siz, real vaqtni kutmasdan
soatlab davom etadigan ssenariylarni bir soniyada tekshirish mumkin.

Ishga tushirish:  python3 tests/test_fsm.py
"""

import os
import sys
import types

# ---- soxta MicroPython 'time' moduli (fsm.py import qilishidan oldin) ----
t = types.ModuleType("time")
t.NOW = [0]
t.ticks_ms = lambda: t.NOW[0]
t.ticks_diff = lambda a, b: a - b
t.ticks_add = lambda a, b: a + b
sys.modules["time"] = t

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "firmware"))
from fsm import Fsm  # noqa: E402


class Cfg:
    MACHINE_ID = "PRISADKA-01"
    SITE = "SEX-1"
    MIN_STATE_MS = 1200
    MIN_PROCESS_MS = 5000
    OFF_CONFIRM_MS = 5000
    SCAN_MAX_AGE_MS = 60000


def lamps(green="off", yellow="off", red="off"):
    return {"green": green, "yellow": yellow, "red": red}


class Rig:
    def __init__(self, idle_timeout_s=900, enabled=True):
        t.NOW[0] = 0
        self.events = []
        self.fsm = Fsm(Cfg,
                       {"idle_timeout_s": idle_timeout_s,
                        "idle_timeout_enabled": enabled},
                       self.events.append)

    def hold(self, status, seconds):
        """Chiroqlarni shu holatda 'seconds' soniya ushlab turish."""
        self.step(status, seconds * 1000)

    def step(self, status, ms, dt=100):
        """Qisqa oraliqlar uchun - millisekundda."""
        for _ in range(ms // dt):
            t.NOW[0] += dt
            self.fsm.update(t.NOW[0], status, 0)

    def states(self):
        return [(e["prev_state"], e["state"], e["prev_duration_s"])
                for e in self.events if e["type"] == "state"]

    def cycles(self):
        return [e for e in self.events if e["type"] == "cycle"]


# ---------------------------------------------------------------- testlar

def test_normal_cycle():
    """QR skan -> 40 s kutish -> 120 s ishlov -> yangi QR = 1 ta detal."""
    r = Rig()
    r.hold(lamps(), 5)
    r.hold(lamps(green="blink"), 40)
    r.hold(lamps(green="on"), 120)
    r.hold(lamps(green="blink"), 5)

    c = r.cycles()
    assert len(c) == 1, c
    assert c[0]["wait_s"] == 40
    assert c[0]["process_s"] == 120
    assert c[0]["completed"] is True
    assert c[0]["part_count"] == 1


def test_fault_does_not_break_cycle():
    """Ishlov o'rtasida avariya: ishlov vaqti yig'ilib davom etadi."""
    r = Rig()
    r.hold(lamps(green="blink"), 10)
    r.hold(lamps(green="on"), 60)
    r.hold(lamps(red="on"), 200)         # avariya
    r.hold(lamps(green="on"), 40)        # ishlov davom etdi
    r.hold(lamps(green="blink"), 5)      # yangi detal

    c = r.cycles()
    assert len(c) == 1, c
    assert c[0]["process_s"] == 100, c[0]   # 60 + 40
    assert c[0]["completed"] is True


def test_downtime_id_opens_and_closes():
    """Qizil -> downtime_id ochiladi, chiqishda o'sha id bilan yopiladi."""
    r = Rig()
    r.hold(lamps(green="on"), 30)
    r.hold(lamps(red="on"), 120)
    r.hold(lamps(green="on"), 10)

    opened = [e for e in r.events if e.get("reason_required")]
    closed = [e for e in r.events if e.get("closes_downtime_id")]
    assert len(opened) == 1 and len(closed) == 1
    assert opened[0]["downtime_id"] == closed[0]["closes_downtime_id"]
    assert closed[0]["prev_duration_s"] == 120


def test_stopped_to_fault_closes_previous_downtime():
    """STOPPED -> FAULT: bitta event eskisini yopib, yangisini ochishi kerak.

    Bu yerda `elif` ishlatilsa, STOPPED yozuvi MES da abadiy ochiq qolib,
    "sababsiz to'xtashlar" ro'yxatiga umuman tushmaydi.
    """
    r = Rig(idle_timeout_s=60)
    r.hold(lamps(yellow="on"), 120)      # IDLE -> STOPPED
    r.hold(lamps(red="on"), 30)          # STOPPED -> FAULT
    r.hold(lamps(green="on"), 10)        # FAULT -> PROCESSING

    opened = [e for e in r.events if e.get("downtime_id")]
    closed = [e for e in r.events if e.get("closes_downtime_id")]
    assert len(opened) == 2, opened                       # STOPPED va FAULT
    assert len(closed) == 2, closed                       # ikkalasi ham yopildi
    assert closed[0]["closes_downtime_id"] == opened[0]["downtime_id"]
    assert closed[1]["closes_downtime_id"] == opened[1]["downtime_id"]

    both = [e for e in r.events
            if e.get("closes_downtime_id") and e.get("downtime_id")]
    assert len(both) == 1 and both[0]["state"] == "FAULT", both


def test_session_makes_ids_unique_after_reboot():
    """Reboot'dan keyin seq noldan boshlanadi - id lar sessiya bilan ajraladi."""
    a = Rig()
    a.hold(lamps(red="on"), 5)
    b = Rig()                            # "qayta yuklanish"
    b.hold(lamps(red="on"), 5)

    ea = [e for e in a.events if e.get("downtime_id")][0]
    eb = [e for e in b.events if e.get("downtime_id")][0]
    assert ea["seq"] == eb["seq"]                          # seq takrorlandi,
    assert ea["downtime_id"] != eb["downtime_id"], ea      # id esa - yo'q
    assert a.fsm.session in ea["downtime_id"]
    assert ea["session"] == a.fsm.session


def test_idle_escalates_to_stopped():
    """Sariq 15 daqiqadan oshsa -> STOPPED, va orqaga qaytmaydi."""
    r = Rig(idle_timeout_s=900)
    r.hold(lamps(yellow="on"), 1500)     # 25 daqiqa

    seq = [s for _, s, _ in r.states()]
    assert "IDLE" in seq and "STOPPED" in seq, seq
    assert seq.count("STOPPED") == 1, seq          # bir marta, aylanmasdan
    assert seq.index("IDLE") < seq.index("STOPPED")
    assert r.fsm.state == "STOPPED"

    # STOPPED ham sabab talab qiladi
    st = [e for e in r.events if e["type"] == "state" and e["state"] == "STOPPED"][0]
    assert st["reason_required"] is True
    assert st["prev_duration_s"] == 900


def test_idle_timeout_disabled():
    """Eskalatsiya o'chirilgan bo'lsa, sariq doim IDLE bo'lib qoladi."""
    r = Rig(enabled=False)
    r.hold(lamps(yellow="on"), 3000)
    seq = [s for _, s, _ in r.states()]
    assert "STOPPED" not in seq, seq


def test_part_taken_without_processing():
    """QR skanerlandi, lekin ishlov bo'lmadi -> completed=False, hisobga kirmaydi."""
    r = Rig()
    r.hold(lamps(green="blink"), 30)
    r.hold(lamps(yellow="on"), 20)

    c = r.cycles()
    assert len(c) == 1, c
    assert c[0]["completed"] is False
    assert c[0]["process_s"] == 0
    assert c[0]["part_count"] == 0


def test_blink_onset_not_counted_as_processing():
    """Miltillash boshlanishi soxta PROCESSING va soxta detal bermasligi kerak.

    `lamps.py` ikkita qirra ko'rmaguncha "blink" deya olmaydi, shuning uchun
    yashil miltillay boshlaganda birinchi yarim davr (~0.5 s) "doimiy yoniq"
    bo'lib keladi. MIN_STATE_MS shu yarim davrdan katta bo'lgani uchun bu
    nomzod commit qilinmaydi.
    """
    r = Rig()
    r.hold(lamps(yellow="on"), 60)
    r.step(lamps(green="on"), 500)        # miltillashning birinchi yarmi
    r.hold(lamps(green="blink"), 40)      # endi blink deb tanildi
    r.hold(lamps(green="on"), 120)        # haqiqiy ishlov
    r.hold(lamps(green="blink"), 10)

    seq = [s for _, s, _ in r.states()]
    assert seq.count("PROCESSING") == 1, seq
    assert seq.count("AWAIT_PART") == 2, seq

    c = r.cycles()
    assert len(c) == 1, c
    assert c[0]["process_s"] == 120, c[0]
    assert c[0]["part_count"] == 1, c[0]


def test_short_processing_is_not_a_part():
    """Bir necha soniyalik "ishlov" detal deb sanalmaydi (MIN_PROCESS_MS)."""
    r = Rig()
    r.hold(lamps(green="blink"), 20)
    r.hold(lamps(green="on"), 3)          # MIN_PROCESS_MS = 5 s dan kichik
    r.hold(lamps(yellow="on"), 20)

    c = r.cycles()
    assert len(c) == 1, c
    assert c[0]["completed"] is False, c[0]
    assert c[0]["part_count"] == 0, c[0]


def test_all_lamps_off_is_recorded_as_downtime():
    """Uchchala chiroq ham o'chiq = stanok o'chirilgan, sabab talab qilinadi."""
    r = Rig()
    r.hold(lamps(green="on"), 60)
    r.hold(lamps(), 300)                  # stanok o'chirildi
    r.hold(lamps(yellow="on"), 30)        # qaytadan yoqildi

    off = [e for e in r.events if e["type"] == "state" and e["state"] == "OFF"]
    assert len(off) == 1, off
    assert off[0]["reason_required"] is True
    assert off[0]["downtime_id"], off[0]

    closed = [e for e in r.events if e.get("closes_downtime_id")]
    assert len(closed) == 1, closed
    assert closed[0]["closes_downtime_id"] == off[0]["downtime_id"]
    assert closed[0]["prev_duration_s"] == 300, closed[0]


def test_short_all_dark_gap_is_not_machine_off():
    """Chiroqlar almashganda oraliqda hammasi o'chiq bo'lishi mumkin.

    PLC sariqni o'chirib yashilni yoqguncha bir necha soniya o'tishi mumkin.
    Bu "stanok o'chdi" emas - OFF_CONFIRM_MS shu pallani filtrlaydi.
    """
    r = Rig()
    r.hold(lamps(yellow="on"), 60)
    r.step(lamps(), 3000)                 # 3 s hamma chiroq o'chiq (o'tish pallasi)
    r.hold(lamps(green="on"), 60)

    seq = [st for _, st, _ in r.states()]
    assert "OFF" not in seq, seq
    assert seq == ["IDLE", "PROCESSING"], seq


def test_machine_off_closes_running_cycle():
    """Ishlov paytida stanok o'chirilsa, sikl yopilishi kerak."""
    r = Rig()
    r.hold(lamps(green="blink"), 20)
    r.hold(lamps(green="on"), 90)
    r.hold(lamps(), 120)                  # o'chirildi

    c = r.cycles()
    assert len(c) == 1, c
    assert c[0]["process_s"] == 90, c[0]
    assert c[0]["completed"] is True


def test_short_glitch_ignored():
    """MIN_STATE_MS dan qisqa signal shovqin deb tashlanadi."""
    r = Rig()
    r.hold(lamps(green="on"), 20)
    before = len(r.states())
    r.step(lamps(red="on"), 200)                      # 200 ms qizil
    r.step(lamps(green="on"), 200)
    assert len(r.states()) == before


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
