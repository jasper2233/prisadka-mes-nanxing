"""MQTT -> SQLite ko'prigi.

Pico dan kelgan xabarlarni bazaga yozadi va QR skanni detal sikliga bog'laydi.

QR skan Pico ga ulanmagan: nakleyka o'qilganda ma'lumot MES tizimiga (va
parallel ravishda stanok progasiga) ketadi. Pico faqat chiroqni ko'radi.

Skanlar NAVBAT hosil qiladi. Operator ishlov ketayotgan paytda keyingi
detalni skanerlab qo'yishi mumkin - u holda chiroq doimiy yashil bo'lib
turaveradi, ishlov tugashi bilan darhol miltillashga o'tadi. Shuning uchun:

  * navbat FIFO - `AWAIT_PART` eventi eng ESKI bog'lanmagan skanni oladi;
  * oyna uzun - skan ishlov boshida bo'lishi mumkin (bir necha daqiqa oldin);
  * `PROCESSING/AWAIT_PART -> IDLE/STOPPED/OFF` (sariq yondi) = stanokning
    o'zi "navbat bo'sh" deb aytmoqda -> qolgan bog'lanmagan skanlar eskiradi.
    Bu navbatni o'zi-o'zidan to'g'rilab turadi.
"""

import json

from . import db

# Skan ishlov boshida bo'lishi mumkin, AWAIT_PART esa ishlov tugagach keladi.
# Shuning uchun oyna bitta smenaga yaqin bo'lishi kerak.
SCAN_WINDOW_S = 4 * 3600

QUEUE_EMPTY_STATES = ("IDLE", "STOPPED", "OFF")
GREEN_STATES = ("PROCESSING", "AWAIT_PART")


class Bridge:
    def __init__(self, con, log=print):
        self.con = con
        self.log = log

    # ---------- MQTT topiklari ----------
    def attach(self, broker):
        broker.subscribe_local("mes/andon/+/event", self.on_message)
        broker.subscribe_local("mes/andon/+/state", self.on_message)
        broker.subscribe_local("mes/andon/+/online", self.on_message)

    def on_message(self, topic, payload, retained=False):
        parts = topic.split("/")
        if len(parts) != 4:
            return
        machine_id, kind = parts[2], parts[3]
        if kind == "online":
            self.on_online(machine_id, payload)
            return
        try:
            data = json.loads(payload)
        except Exception:
            self.log("JSON emas: {} {!r}".format(topic, payload[:60]))
            return
        if kind == "state":
            self.on_snapshot(machine_id, data)
        elif kind == "event":
            if data.get("type") == "cycle":
                self.on_cycle(machine_id, data)
            else:
                self.on_state(machine_id, data)

    # ---------- QR skan bog'lash ----------
    def bind_scan(self, machine_id, ts):
        """Navbatdagi eng eski skanni joriy detal sifatida oladi (FIFO).

        DIQQAT 1: navbat FIFO. Operator ishlov paytida ikkita detal
        skanerlab qo'ysa, birinchi skanerlangani birinchi ishlanadi.

        DIQQAT 2: yangi QR (`AWAIT_PART`) oldingi siklning `cycle` xabaridan
        OLDIN keladi. Shuning uchun eski detal `closing_part_id` ga
        ko'chiriladi - keyingi `cycle` o'shani oladi, yangisini emas.
        """
        row = self.con.execute("""
            SELECT id, part_id FROM part_scan
            WHERE machine_id = ? AND consumed = 0 AND scanned_at >= ?
            ORDER BY scanned_at ASC LIMIT 1""",
            (machine_id, ts - SCAN_WINDOW_S)).fetchone()
        if not row:
            return None
        self.con.execute("UPDATE part_scan SET consumed = 1 WHERE id = ?",
                         (row["id"],))
        self.con.execute("""
            UPDATE machine_state
               SET closing_part_id = COALESCE(closing_part_id, current_part_id),
                   current_part_id = ?
             WHERE machine_id = ?""", (row["part_id"], machine_id))
        return row["part_id"]

    def current_part(self, machine_id):
        row = self.con.execute(
            "SELECT current_part_id FROM machine_state WHERE machine_id = ?",
            (machine_id,)).fetchone()
        return row["current_part_id"] if row else None

    def expire_scans(self, machine_id, ts):
        """Sariq chiroq yondi = navbatda detal yo'q. Qolgan skanlar eskiradi.

        5 sekundlik zaxira: aynan shu paytda kelgan skan tasodifan
        o'chib ketmasin.
        """
        cur = self.con.execute("""
            UPDATE part_scan SET consumed = 2
            WHERE machine_id = ? AND consumed = 0 AND scanned_at <= ?""",
            (machine_id, ts - 5))
        if cur.rowcount:
            self.log("  {} ta bog'lanmagan skan eskirdi ({} sariqqa o'tdi)".format(
                cur.rowcount, machine_id))

    def take_closing_part(self, machine_id):
        """Sikl yopilayotganda qaysi detal tugagani. Oldingisi bo'lsa - o'sha."""
        row = self.con.execute(
            "SELECT current_part_id, closing_part_id FROM machine_state "
            "WHERE machine_id = ?", (machine_id,)).fetchone()
        if not row:
            return None
        if row["closing_part_id"]:
            self.con.execute(
                "UPDATE machine_state SET closing_part_id = NULL WHERE machine_id = ?",
                (machine_id,))
            return row["closing_part_id"]
        self.con.execute(
            "UPDATE machine_state SET current_part_id = NULL WHERE machine_id = ?",
            (machine_id,))
        return row["current_part_id"]

    # ---------- eventlar ----------
    def on_state(self, machine_id, d):
        ts = d.get("ts") or db.now()          # ts=0 -> NTP yo'q, server vaqti
        session = d.get("session", "?")
        self.ensure_machine(machine_id, d.get("site"), session)

        state, prev = d.get("state"), d.get("prev_state")
        part_id = d.get("part_id")
        if state == "AWAIT_PART" and not part_id:
            part_id = self.bind_scan(machine_id, ts)
        if state in QUEUE_EMPTY_STATES and prev in GREEN_STATES:
            self.expire_scans(machine_id, ts)
        if not part_id:
            part_id = self.current_part(machine_id)

        cur = self.con.execute("""
            INSERT OR IGNORE INTO andon_event
              (machine_id, session, seq, ts, received_at, state, prev_state,
               prev_duration_s, lamps, part_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (machine_id, session, d.get("seq", 0), ts, db.now(),
             d.get("state"), d.get("prev_state"), d.get("prev_duration_s"),
             json.dumps(d.get("lamps", {})), part_id))
        if cur.rowcount == 0:
            self.con.commit()
            return                            # dublikat - allaqachon bor

        # 1) ochiq to'xtashni yopish
        close_id = d.get("closes_downtime_id")
        if close_id:
            self.con.execute("""
                UPDATE downtime SET ended_at = ?, duration_s = ?
                WHERE downtime_id = ? AND ended_at IS NULL""",
                (ts, d.get("prev_duration_s"), close_id))
            self.log("  to'xtash yopildi: {} ({} s)".format(
                close_id, d.get("prev_duration_s")))

        # 2) yangi to'xtashni ochish
        # DIQQAT: STOPPED -> FAULT da bitta event ikkalasini ham olib keladi.
        open_id = d.get("downtime_id")
        if open_id:
            self.con.execute("""
                INSERT OR IGNORE INTO downtime
                  (downtime_id, machine_id, session, state, started_at)
                VALUES (?,?,?,?,?)""",
                (open_id, machine_id, session, d.get("state"), ts))
            self.log("  to'xtash ochildi: {} [{}] - sabab kutilmoqda".format(
                open_id, d.get("state")))

        self.con.execute("""
            UPDATE machine_state SET state = ?, session = ?, updated_at = ?
            WHERE machine_id = ?""", (d.get("state"), session, db.now(), machine_id))
        self.con.commit()
        self.log("[{}] {} {} -> {} ({} s){}".format(
            machine_id, d.get("seq"), d.get("prev_state"), d.get("state"),
            d.get("prev_duration_s"), "  detal=" + part_id if part_id else ""))

    def on_cycle(self, machine_id, d):
        ts = d.get("ts") or db.now()
        session = d.get("session", "?")
        self.ensure_machine(machine_id, d.get("site"), session)
        part_id = d.get("part_id") or self.take_closing_part(machine_id)

        cur = self.con.execute("""
            INSERT OR IGNORE INTO part_cycle
              (machine_id, session, seq, ts, part_id, wait_s, process_s, completed)
            VALUES (?,?,?,?,?,?,?,?)""",
            (machine_id, session, d.get("seq", 0), ts, part_id,
             d.get("wait_s"), d.get("process_s"),
             1 if d.get("completed") else 0))
        self.con.commit()
        if cur.rowcount:
            self.log("[{}] SIKL {} kutish={}s ishlov={}s {}".format(
                machine_id, part_id or "-", d.get("wait_s"), d.get("process_s"),
                "tugallandi" if d.get("completed") else "TUGALLANMADI"))

    def on_snapshot(self, machine_id, d):
        self.ensure_machine(machine_id, d.get("site"), d.get("session"))
        self.con.execute("""
            UPDATE machine_state SET
              site = COALESCE(?, site), session = COALESCE(?, session),
              state = ?, since_s = ?, lamps = ?, part_count = ?,
              idle_timeout_s = ?, idle_timeout_enabled = ?, uptime_s = ?,
              queued = ?, dropped = ?, rssi = ?, updated_at = ?
            WHERE machine_id = ?""",
            (d.get("site"), d.get("session"), d.get("state"), d.get("since_s"),
             json.dumps(d.get("lamps", {})), d.get("part_count"),
             d.get("idle_timeout_s"), 1 if d.get("idle_timeout_enabled") else 0,
             d.get("uptime_s"), d.get("queued"), d.get("dropped"),
             d.get("rssi"), db.now(), machine_id))
        self.con.commit()

    def on_online(self, machine_id, payload):
        val = 1 if payload.strip() in (b"1", b"true") else 0
        self.ensure_machine(machine_id, None, None)
        self.con.execute(
            "UPDATE machine_state SET online = ?, updated_at = ? WHERE machine_id = ?",
            (val, db.now(), machine_id))
        self.con.commit()
        self.log("[{}] {}".format(machine_id, "ONLAYN" if val else "UZILDI"))

    def ensure_machine(self, machine_id, site, session):
        self.con.execute("""
            INSERT OR IGNORE INTO machine_state (machine_id, site, session, updated_at)
            VALUES (?,?,?,?)""", (machine_id, site, session, db.now()))
