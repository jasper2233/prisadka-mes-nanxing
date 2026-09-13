"""Telegram bot testlari - internet va haqiqiy tokensiz.

Telegram API soxta obyekt bilan almashtiriladi, `_send_next()` qo'lda
chaqiriladi (oqimlar ishga tushirilmaydi). Baza - vaqtinchalik SQLite fayl.

Ishga tushirish:  python3 tests/test_telegram.py
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mes import db as dbmod                           # noqa: E402
from mes import telegram as tg                        # noqa: E402
from mes.bridge import Bridge                         # noqa: E402

OWNER = 111
OTHER = 222


class FakeApi:
    def __init__(self):
        self.calls = []
        self.fail = []              # sendMessage uchun navbatdagi xatolar

    def __call__(self, method, payload=None, timeout=20):
        self.calls.append((method, payload or {}))
        if method == "sendMessage" and self.fail:
            raise self.fail.pop(0)
        return {"ok": True, "result": []}

    def sent(self):
        return [p for m, p in self.calls if m == "sendMessage"]


class Rig:
    def __init__(self, chat_ids=None, events=None):
        self.dir = tempfile.mkdtemp(prefix="tg-test-")
        self.cfg_path = os.path.join(self.dir, "telegram.json")
        cfg = {"token": "0:test", "chat_ids": chat_ids or []}
        if events is not None:
            cfg["events"] = events
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        self.db_path = os.path.join(self.dir, "mes.db")
        self.con = dbmod.connect(self.db_path)
        self.api = FakeApi()
        self.bot = tg.TelegramBot(self.cfg_path, self.db_path, log=lambda *a: None,
                                  api=self.api, sleep=lambda s: None)

    def flush(self):
        statuses = []
        while True:
            st = self.bot._send_next()
            if st == "empty" or len(statuses) > 50:
                return statuses
            statuses.append(st)

    def saved(self):
        with open(self.cfg_path, encoding="utf-8") as f:
            return json.load(f)

    def say(self, chat_id, text, name="Ali"):
        self.bot.handle_update({"update_id": 1, "message": {
            "chat": {"id": chat_id, "type": "private", "first_name": name},
            "text": text}})

    def close(self):
        self.con.close()
        shutil.rmtree(self.dir, ignore_errors=True)


# ---------------------------------------------------------------- ulanish

def test_first_start_registers_owner_without_code():
    """Birinchi /start - egasi, kodsiz ulanadi va faylga saqlanadi."""
    r = Rig()
    try:
        r.say(OWNER, "/start")
        assert r.saved()["chat_ids"] == [OWNER], r.saved()
        r.flush()
        assert "Ulandingiz" in r.api.sent()[0]["text"]
    finally:
        r.close()


def test_second_chat_needs_join_code():
    """Keyingi odam kodsiz ulana olmaydi - aks holda botni topgan har kim
    zavod ma'lumotini olardi."""
    r = Rig(chat_ids=[OWNER])
    try:
        r.say(OTHER, "/start")
        assert OTHER not in r.saved()["chat_ids"]
        r.say(OTHER, "/start 000000" if r.bot.cfg["join_code"] != "000000" else "/start 111111")
        assert OTHER not in r.saved()["chat_ids"]
        r.say(OTHER, "/start " + r.bot.cfg["join_code"])
        assert OTHER in r.saved()["chat_ids"], r.saved()
    finally:
        r.close()


def test_join_code_generated_and_kept():
    r = Rig()
    try:
        code = r.saved()["join_code"]
        assert len(code) == 6 and code.isdigit(), code
        again = tg.load_config(r.cfg_path)["join_code"]
        assert again == code                           # har safar yangilanmaydi
    finally:
        r.close()


def test_unregistered_chat_cannot_query():
    r = Rig(chat_ids=[OWNER])
    try:
        r.say(OTHER, "/holat")
        r.flush()
        texts = [p["text"] for p in r.api.sent()]
        assert len(texts) == 1 and "/start KOD" in texts[0], texts
    finally:
        r.close()


def test_stop_unsubscribes():
    r = Rig(chat_ids=[OWNER])
    try:
        r.say(OWNER, "/stop")
        assert r.saved()["chat_ids"] == []
    finally:
        r.close()


def test_group_command_with_bot_name():
    """Guruhda buyruq /holat@kromkabot ko'rinishida keladi."""
    r = Rig(chat_ids=[OWNER])
    try:
        r.say(OWNER, "/holat@kromkabot")
        r.flush()
        assert "Hali hech qaysi stanok" in r.api.sent()[0]["text"]
    finally:
        r.close()


# ---------------------------------------------------------------- xabarlar

def test_downtime_is_loud_cycle_is_silent():
    """Avariya telefonni jiringlatadi, detal tayyor - jim (kuniga ~100 ta)."""
    r = Rig(chat_ids=[OWNER])
    try:
        r.bot.notify("downtime_open", machine="PRISADKA-01", state="FAULT",
                     prev_state="PROCESSING", prev_duration_s=198, ts=1789198483)
        r.bot.notify("cycle", machine="PRISADKA-01", part_id="QR-1", wait_s=41,
                     process_s=179, completed=True, today_count=12)
        r.flush()
        loud, silent = r.api.sent()
        assert "AVARIYA" in loud["text"] and loud["disable_notification"] is False
        assert "Sababni MES da" in loud["text"]
        assert "Bugun: 12 ta" in silent["text"] and silent["disable_notification"] is True
    finally:
        r.close()


def test_disabled_event_group_is_not_sent():
    r = Rig(chat_ids=[OWNER], events={"cycle": False})
    try:
        r.bot.notify("cycle", machine="M", completed=True, process_s=10, wait_s=1)
        r.bot.notify("downtime_open", machine="M", state="OFF", ts=1)
        r.flush()
        assert len(r.api.sent()) == 1 and "O'CHIRILDI" in r.api.sent()[0]["text"]
    finally:
        r.close()


def test_nothing_queued_without_chats():
    r = Rig()
    try:
        r.bot.notify("downtime_open", machine="M", state="FAULT", ts=1)
        assert r.flush() == []
    finally:
        r.close()


def test_html_is_escaped():
    """Operator izohida < > & bo'lsa, Telegram HTML xabarni rad etmasligi kerak."""
    text, _ = tg.format_event("reason", {"machine": "M", "state": "FAULT",
                                         "duration_s": 60, "reason_name": "Boshqa",
                                         "comment": "<b>nasos</b> & klapan"})
    assert "&lt;b&gt;nasos&lt;/b&gt; &amp; klapan" in text, text


# ---------------------------------------------------------------- yuborish

def test_rate_limit_429_retries_then_sends():
    r = Rig(chat_ids=[OWNER])
    try:
        r.api.fail = [tg.TelegramError(429, "Too Many Requests", retry_after=3)]
        r.bot.enqueue("salom")
        assert r.flush() == ["retry", "sent"]
    finally:
        r.close()


def test_network_error_keeps_message():
    r = Rig(chat_ids=[OWNER])
    try:
        r.api.fail = [OSError("internet yo'q"), OSError("hali yo'q")]
        r.bot.enqueue("salom")
        assert r.flush() == ["retry", "retry", "sent"]
    finally:
        r.close()


def test_blocked_chat_message_dropped():
    r = Rig(chat_ids=[OWNER])
    try:
        r.api.fail = [tg.TelegramError(403, "bot was blocked by the user")]
        r.bot.enqueue("salom")
        assert r.flush() == ["dropped"]
    finally:
        r.close()


def test_bad_token_disables_bot():
    r = Rig(chat_ids=[OWNER])
    try:
        r.api.fail = [tg.TelegramError(401, "Unauthorized")]
        r.bot.enqueue("bir")
        r.bot.enqueue("ikki")
        assert r.flush() == ["disabled"]
        assert r.bot.disabled
        r.bot.notify("downtime_open", machine="M", state="FAULT", ts=1)
        assert r.flush() == []
    finally:
        r.close()


def test_queue_drops_oldest_when_full():
    """Internet uzoq yo'q bo'lsa xotira to'lmasin - eng eskilari tashlanadi."""
    r = Rig(chat_ids=[OWNER])
    try:
        for i in range(tg.QUEUE_MAX + 5):
            r.bot.enqueue("xabar {}".format(i))
        assert len(r.bot._q) == tg.QUEUE_MAX
        assert r.bot._q[0][1] == "xabar 5"
    finally:
        r.close()


# ---------------------------------------------------------------- ko'prik bilan

def _state(br, seq, new, prev, dur, **kw):
    ev = {"type": "state", "session": "s1", "seq": seq, "ts": 1789198000 + seq,
          "state": new, "prev_state": prev, "prev_duration_s": dur, "lamps": {}}
    ev.update(kw)
    br.on_state("PRISADKA-01", ev)


def test_bridge_closes_before_opening():
    """STOPPED -> FAULT: avval "kutish tugadi", keyin "AVARIYA"."""
    r = Rig()
    calls = []
    try:
        br = Bridge(r.con, log=lambda *a: None, notify=lambda k, **d: calls.append((k, d)))
        _state(br, 1, "STOPPED", "IDLE", 900, downtime_id="DT-S", reason_required=True)
        _state(br, 2, "FAULT", "STOPPED", 300, closes_downtime_id="DT-S",
               downtime_id="DT-F", reason_required=True)
        kinds = [(k, d.get("state")) for k, d in calls]
        assert kinds == [("downtime_open", "STOPPED"), ("downtime_close", "STOPPED"),
                         ("downtime_open", "FAULT")], kinds
        assert calls[1][1]["duration_s"] == 300 and calls[1][1]["new_state"] == "FAULT"
    finally:
        r.close()


def test_bridge_duplicate_event_not_notified_twice():
    r = Rig()
    calls = []
    try:
        br = Bridge(r.con, log=lambda *a: None, notify=lambda k, **d: calls.append(k))
        _state(br, 1, "FAULT", "PROCESSING", 60, downtime_id="DT-1", reason_required=True)
        _state(br, 1, "FAULT", "PROCESSING", 60, downtime_id="DT-1", reason_required=True)
        assert calls == ["downtime_open"], calls
    finally:
        r.close()


def test_bridge_online_only_on_change():
    """online retained xabari qayta-qayta keladi - faqat o'zgarishda xabar."""
    r = Rig()
    calls = []
    try:
        br = Bridge(r.con, log=lambda *a: None,
                    notify=lambda k, **d: calls.append((k, d["online"])))
        for payload in (b"1", b"1", b"1", b"0", b"0", b"1"):
            br.on_online("PRISADKA-01", payload)
        assert calls == [("online", True), ("online", False), ("online", True)], calls
    finally:
        r.close()


def test_bridge_resets_online_on_startup():
    """MES qayta ishga tushganda oldingi "onlayn" belgisi qolib ketmasin."""
    r = Rig()
    try:
        Bridge(r.con, log=lambda *a: None).on_online("PRISADKA-01", b"1")
        Bridge(r.con, log=lambda *a: None)             # qayta ishga tushish
        row = r.con.execute("SELECT online FROM machine_state").fetchone()
        assert row["online"] == 0
    finally:
        r.close()


def test_notifier_crash_does_not_break_database():
    r = Rig()
    try:
        def boom(kind, **d):
            raise RuntimeError("telegram yiqildi")
        br = Bridge(r.con, log=lambda *a: None, notify=boom)
        _state(br, 1, "FAULT", "PROCESSING", 60, downtime_id="DT-1", reason_required=True)
        n = r.con.execute("SELECT COUNT(*) c FROM downtime").fetchone()["c"]
        assert n == 1
    finally:
        r.close()


# ---------------------------------------------------------------- hisobot

def test_status_and_report_read_database():
    r = Rig(chat_ids=[OWNER])
    try:
        br = Bridge(r.con, log=lambda *a: None)
        import time
        now = int(time.time())
        br.on_state("PRISADKA-01", {"session": "s", "seq": 1, "ts": now - 120,
                                    "state": "FAULT", "prev_state": "PROCESSING",
                                    "prev_duration_s": 300, "downtime_id": "D1",
                                    "reason_required": True})
        text = r.bot.status_text()
        assert "PRISADKA-01" in text and "avariya" in text, text
        assert "Sababsiz to'xtashlar: 1" in text, text
        rep = r.bot.report_text(now - 3600, "Soatlik hisobot")
        assert rep and "To'xtashlar: 1 ta" in rep, rep
        assert r.bot.report_text(now + 10, "Kelajak") is None     # tinch davr - jim
    finally:
        r.close()


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
        except Exception as e:
            failed += 1
            print("  XATO  {}\n        {!r}".format(fn.__name__, e))
    print("\n{}/{} test o'tdi".format(len(tests) - failed, len(tests)))
    sys.exit(1 if failed else 0)
