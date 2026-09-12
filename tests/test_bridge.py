"""MES ko'prigi (MQTT -> baza) testlari.

MQTT va HTTP ishtirok etmaydi: `Bridge` ga to'g'ridan-to'g'ri Pico yuboradigan
lug'atlar beriladi va bazada nima hosil bo'lgani tekshiriladi.

Ishga tushirish:  python3 tests/test_bridge.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mes import db as dbmod            # noqa: E402
from mes.bridge import Bridge          # noqa: E402

M = "PRISADKA-01"
SES = "a04662"


class Rig:
    def __init__(self):
        self.con = dbmod.connect(":memory:")
        self.br = Bridge(self.con, log=lambda *a: None)
        self.seq = 0
        self.t = 1_700_000_000

    def tick(self, secs):
        self.t += secs

    def scan(self, part_id):
        self.con.execute(
            "INSERT INTO part_scan (machine_id, part_id, scanned_at) VALUES (?,?,?)",
            (M, part_id, self.t))
        self.con.commit()

    def state(self, new, prev, dur, **kw):
        self.seq += 1
        ev = {"type": "state", "machine_id": M, "session": SES, "seq": self.seq,
              "ts": self.t, "state": new, "prev_state": prev,
              "prev_duration_s": dur, "lamps": {}, "part_id": None}
        ev.update(kw)
        self.br.on_state(M, ev)
        return ev

    def cycle(self, wait_s, process_s, completed=True):
        self.seq += 1
        self.br.on_cycle(M, {"type": "cycle", "machine_id": M, "session": SES,
                             "seq": self.seq, "ts": self.t, "part_id": None,
                             "wait_s": wait_s, "process_s": process_s,
                             "completed": completed})

    def cycles(self):
        return self.con.execute(
            "SELECT * FROM part_cycle ORDER BY id").fetchall()

    def downtimes(self):
        return self.con.execute(
            "SELECT * FROM downtime ORDER BY started_at").fetchall()


# ---------------------------------------------------------------- testlar

def test_qr_binds_to_the_cycle_that_closes():
    """Yangi QR eventi eski siklning `cycle` xabaridan OLDIN keladi.

    Shu sababli yangi skan avtomatik "joriy detal" bo'lib qolsa, yopilayotgan
    sikl noto'g'ri (keyingi) detalni olardi. Ketma-ketlik Pico dagi kabi:
        AWAIT_PART(yangi QR) -> cycle(oldingi detal) -> PROCESSING
    """
    r = Rig()
    r.scan("QR-001")
    r.state("AWAIT_PART", "IDLE", 90)
    r.tick(40)
    r.state("PROCESSING", "AWAIT_PART", 40)
    r.tick(180)

    r.scan("QR-002")                       # ikkinchi detal skanerlandi
    r.state("AWAIT_PART", "PROCESSING", 180)
    r.cycle(40, 180)                       # birinchi detalning sikli yopildi
    r.tick(30)
    r.state("PROCESSING", "AWAIT_PART", 30)
    r.tick(200)
    r.state("IDLE", "PROCESSING", 200)
    r.cycle(30, 200)

    c = r.cycles()
    assert [x["part_id"] for x in c] == ["QR-001", "QR-002"], \
        [x["part_id"] for x in c]
    assert c[0]["process_s"] == 180 and c[1]["process_s"] == 200


def test_events_carry_current_part():
    r = Rig()
    r.scan("QR-777")
    r.state("AWAIT_PART", "IDLE", 10)
    r.tick(20)
    r.state("PROCESSING", "AWAIT_PART", 20)
    rows = r.con.execute("SELECT state, part_id FROM andon_event ORDER BY id").fetchall()
    assert all(x["part_id"] == "QR-777" for x in rows), [dict(x) for x in rows]


def test_old_scan_outside_window_is_ignored():
    """Juda eski skan yangi detalga bog'lanmasligi kerak."""
    r = Rig()
    r.scan("QR-ESKI")
    r.tick(5 * 3600)                        # besh soat o'tdi (oyna 4 soat)
    r.state("AWAIT_PART", "IDLE", 60)
    row = r.con.execute("SELECT part_id FROM andon_event").fetchone()
    assert row["part_id"] is None, dict(row)


def test_scan_during_processing_binds_to_next_part():
    """Operator ishlov ketayotganda keyingi detalni skanerlab qo'yadi.

    Chiroq doimiy yashil bo'lib turaveradi; ishlov tugashi bilan darhol
    miltillashga o'tadi va o'sha skan keyingi detalga bog'lanadi.
    Skan AWAIT_PART dan bir necha daqiqa OLDIN bo'lgani uchun oyna uzun.
    """
    r = Rig()
    r.scan("QR-A")
    r.state("AWAIT_PART", "IDLE", 90)
    r.tick(40)
    r.state("PROCESSING", "AWAIT_PART", 40)

    r.tick(30)
    r.scan("QR-B")                          # ishlov boshida keyingi detal skanerlandi
    r.tick(250)                             # ishlov yana 250 s davom etdi

    r.state("AWAIT_PART", "PROCESSING", 280)
    r.cycle(40, 280)                        # A ning sikli
    r.tick(20)
    r.state("PROCESSING", "AWAIT_PART", 20)
    r.tick(300)
    r.state("IDLE", "PROCESSING", 300)
    r.cycle(20, 300)                        # B ning sikli

    got = [x["part_id"] for x in r.cycles()]
    assert got == ["QR-A", "QR-B"], got


def test_scan_queue_is_fifo():
    """Ikki detal navbatga qo'yilsa, birinchi skanerlangani birinchi ishlanadi."""
    r = Rig()
    r.scan("QR-1")
    r.tick(5)
    r.scan("QR-2")
    r.state("AWAIT_PART", "IDLE", 60)
    first = r.con.execute(
        "SELECT part_id FROM andon_event ORDER BY id DESC LIMIT 1").fetchone()
    assert first["part_id"] == "QR-1", dict(first)

    r.tick(30)
    r.state("PROCESSING", "AWAIT_PART", 30)
    r.tick(200)
    r.state("AWAIT_PART", "PROCESSING", 200)     # navbatdagi ikkinchisi
    r.cycle(30, 200)
    second = r.con.execute(
        "SELECT current_part_id FROM machine_state WHERE machine_id = ?",
        (M,)).fetchone()
    assert second["current_part_id"] == "QR-2", dict(second)


def test_yellow_lamp_expires_stale_scans():
    """Sariq chiroq = navbatda detal yo'q. Bog'lanmagan skanlar eskirishi kerak.

    Bo'lmasa, o'qilgan-u stanokka solinmagan detal keyingi siklga noto'g'ri
    yopishib, butun hisobni siljitib yuborardi.
    """
    r = Rig()
    r.scan("QR-YOQOLGAN")                   # skanerlandi, lekin stanokka solinmadi
    r.state("AWAIT_PART", "IDLE", 60)       # bu skan bog'landi
    r.tick(20)
    r.scan("QR-ORTIQCHA")                   # yana bittasi navbatga tushdi
    r.tick(20)
    r.state("IDLE", "AWAIT_PART", 40)       # detal solinmadi -> sariq yondi

    stale = r.con.execute(
        "SELECT part_id, consumed FROM part_scan WHERE part_id = 'QR-ORTIQCHA'"
    ).fetchone()
    assert stale["consumed"] == 2, dict(stale)

    r.tick(60)
    r.scan("QR-YANGI")
    r.state("AWAIT_PART", "IDLE", 60)
    ev = r.con.execute(
        "SELECT part_id FROM andon_event ORDER BY id DESC LIMIT 1").fetchone()
    assert ev["part_id"] == "QR-YANGI", dict(ev)


def test_downtime_opens_and_closes():
    r = Rig()
    r.state("FAULT", "PROCESSING", 120,
            downtime_id="DT-1", reason_required=True)
    r.tick(240)
    r.state("PROCESSING", "FAULT", 240, closes_downtime_id="DT-1")

    d = r.downtimes()
    assert len(d) == 1
    assert d[0]["ended_at"] is not None
    assert d[0]["duration_s"] == 240
    assert d[0]["reason_code"] is None          # sabab hali ko'rsatilmagan
    assert len(dbmod.pending_downtimes(r.con)) == 1


def test_stopped_to_fault_closes_and_opens_in_one_event():
    """Bitta event ikkala maydonni olib kelsa, ikkalasi ham bajarilishi kerak."""
    r = Rig()
    r.state("STOPPED", "IDLE", 900, downtime_id="DT-S", reason_required=True)
    r.tick(300)
    r.state("FAULT", "STOPPED", 300,
            closes_downtime_id="DT-S", downtime_id="DT-F", reason_required=True)
    r.tick(150)
    r.state("PROCESSING", "FAULT", 150, closes_downtime_id="DT-F")

    d = {x["downtime_id"]: x for x in r.downtimes()}
    assert d["DT-S"]["duration_s"] == 300, dict(d["DT-S"])
    assert d["DT-F"]["duration_s"] == 150, dict(d["DT-F"])
    assert all(x["ended_at"] for x in d.values())


def test_duplicate_events_are_ignored():
    """Xabar ikki marta kelsa, baza ikki marta yozmasligi kerak."""
    r = Rig()
    ev = r.state("FAULT", "PROCESSING", 60, downtime_id="DT-9", reason_required=True)
    r.br.on_state(M, ev)                   # aynan o'sha xabar qaytadan
    r.br.on_state(M, ev)
    n = r.con.execute("SELECT COUNT(*) c FROM andon_event").fetchone()["c"]
    assert n == 1, n
    assert len(r.downtimes()) == 1


def test_reboot_session_does_not_collide():
    """Reboot'dan keyin seq 1 dan boshlanadi - session ularni ajratadi."""
    r = Rig()
    r.state("FAULT", "PROCESSING", 60, downtime_id="DT-A", reason_required=True)
    first = r.con.execute("SELECT COUNT(*) c FROM andon_event").fetchone()["c"]

    r.seq = 0                               # qurilma qayta yuklandi
    global SES
    old, SES = SES, "ffffff"
    try:
        r.tick(10)
        r.state("FAULT", "BOOT", 0, downtime_id="DT-B", reason_required=True)
    finally:
        SES = old
    n = r.con.execute("SELECT COUNT(*) c FROM andon_event").fetchone()["c"]
    assert first == 1 and n == 2, (first, n)


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
