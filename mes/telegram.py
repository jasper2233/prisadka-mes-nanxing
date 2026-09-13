"""Telegram bot: MES hodisalarini chatga yuborish va buyruqlarga javob berish.

Sozlama - `telegram.json`, bazaning yonida. Ichida token bor, shuning uchun
.gitignore da va .exe ga bundle qilinmaydi:

    {
      "token": "123456:ABC...",
      "chat_ids": [],            /start bosgan chatlar o'zi qo'shiladi
      "join_code": "482913",     ikkinchi va keyingi odamlar uchun
      "events": {"downtime": true, "cycle": true, "online": true,
                 "reason": true, "startup": true},
      "summary_minutes": 60      0 = davriy hisobot o'chiq
    }

Ulanish: Telegram'da botni ochib Start bosiladi. BIRINCHI chat kodsiz
ulanadi (egasi). Keyingilar `/start KOD` yuboradi - kod shu faylda, dastur
jurnalida va egasining `/kod` buyrug'ida. Kodsiz ochiq qoldirilsa, botni
topgan istalgan odam zavod ma'lumotini ola boshlardi.

Buyruqlar: /holat  /hisobot  /kod  /stop

Nozik jihatlar:
- `notify()` MES ning asyncio oqimidan chaqiriladi - u faqat navbatga
  qo'shadi, tarmoqqa chiqmaydi. Aks holda sekin internet brokerni qotirardi.
- Muhim xabarlar (avariya, aloqa uzildi) ovozli; detal, hisobot va
  tiklanishlar ovozsiz - kuniga ~100 ta detal telefonni jiringlatmasin.
- Bitta bot uchun getUpdates ni faqat bitta dastur o'qiy oladi. Ikki
  kompyuterda bir xil token bilan ishlatilsa, Telegram 409 qaytaradi.
"""

import collections
import html
import json
import os
import random
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request

API_URL = "https://api.telegram.org/bot{token}/{method}"
QUEUE_MAX = 300             # internet uzoq yo'q bo'lsa eng eskilari tashlanadi
SEND_INTERVAL = 1.05        # Telegram: bitta chatga sekundiga ~1 xabar
LATE_NOTE_S = 300           # shundan kech yuborilgan xabarga izoh qo'shiladi
CONFLICT_WARN_S = 600       # 409 dan keyin shuncha vaqt javoblarga ogohlantirish qo'shiladi

CONFLICT_NOTE = ("\n\n⚠️ <b>Diqqat:</b> bu bot boshqa kompyuterda ham ishga "
                 "tushirilgan. Buyruqlar ikkalasiga aralashib tushadi va javob "
                 "noto'g'ri kompyuterdan kelishi mumkin. Faqat bittasini qoldiring.")

DEFAULT_EVENTS = {"downtime": True, "cycle": True, "online": True,
                  "reason": True, "startup": True}
EVENT_GROUP = {"downtime_open": "downtime", "downtime_close": "downtime",
               "cycle": "cycle", "online": "online", "reason": "reason",
               "startup": "startup"}

STATE_UZ = {"PROCESSING": "ishlov", "AWAIT_PART": "detal kutilmoqda",
            "IDLE": "kutish", "STOPPED": "uzoq kutish", "FAULT": "avariya",
            "OFF": "o'chirilgan", "BOOT": "yoqildi"}
STATE_ICON = {"PROCESSING": "🟢", "AWAIT_PART": "🟢", "IDLE": "🟡",
              "STOPPED": "🟠", "FAULT": "🔴", "OFF": "⚫", "BOOT": "⚪"}
DOWNTIME_TITLE = {"FAULT": "AVARIYA", "STOPPED": "UZOQ KUTISH",
                  "OFF": "STANOK O'CHIRILDI"}
DOWNTIME_END = {"FAULT": "Avariya tugadi", "STOPPED": "Kutish tugadi",
                "OFF": "Stanok yoqildi"}

HELP = ("Buyruqlar:\n"
        "/holat - stanoklar hozir nima qilyapti\n"
        "/hisobot - bugungi hisobot\n"
        "/kod - boshqa odamni ulash kodi\n"
        "/stop - xabarlarni to'xtatish")


class TelegramError(Exception):
    def __init__(self, code, description="", retry_after=None):
        super().__init__("{} {}".format(code, description))
        self.code = code
        self.description = description
        self.retry_after = retry_after


# ---------------------------------------------------------------- formatlash

def esc(v):
    return html.escape("" if v is None else str(v), quote=False)


def fmt_dur(s):
    s = int(max(0, s or 0))
    if s < 60:
        return "{} s".format(s)
    if s < 3600:
        return "{} daq {:02d} s".format(s // 60, s % 60)
    return "{} soat {:02d} daq".format(s // 3600, s % 3600 // 60)


def fmt_time(ts=None):
    return time.strftime("%H:%M", time.localtime(ts or time.time()))


def state_uz(state):
    return STATE_UZ.get(state, state or "?")


def local_midnight(now=None):
    t = time.localtime(now or time.time())
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def format_event(kind, d):
    """Hodisani (matn, ovozsizmi) juftligiga aylantiradi. Keraksiz bo'lsa (None, _)."""
    m = esc(d.get("machine"))
    if kind == "downtime_open":
        st = d.get("state")
        lines = ["{} <b>{}</b> · {}".format(STATE_ICON.get(st, "⚠️"),
                                             DOWNTIME_TITLE.get(st, st), m)]
        if st == "STOPPED":
            lines.append("Sariq chiroq {} yonib turibdi".format(
                fmt_dur(d.get("prev_duration_s"))))
        else:
            lines.append("{} da boshlandi".format(fmt_time(d.get("ts"))))
            if d.get("prev_state") and d.get("prev_state") != "BOOT":
                lines.append("Oldin: {} ({})".format(
                    state_uz(d.get("prev_state")), fmt_dur(d.get("prev_duration_s"))))
        if d.get("part_id"):
            lines.append("Detal: {}".format(esc(d.get("part_id"))))
        lines.append("\nSababni MES da ko'rsating.")
        return "\n".join(lines), False

    if kind == "downtime_close":
        st = d.get("state")
        return ("✅ <b>{}</b> · {}\nDavomiyligi: {}\nHozir: {}".format(
            DOWNTIME_END.get(st, "To'xtash tugadi"), m,
            fmt_dur(d.get("duration_s")), state_uz(d.get("new_state")))), False

    if kind == "cycle":
        if d.get("completed"):
            text = "🟢 Detal tayyor · {}\n{}ishlov {} · kutish {}".format(
                m, esc(d.get("part_id")) + " · " if d.get("part_id") else "",
                fmt_dur(d.get("process_s")), fmt_dur(d.get("wait_s")))
            if d.get("today_count") is not None:
                text += "\nBugun: {} ta".format(d["today_count"])
        else:
            text = "⚪ Detal ishlovsiz olindi · {}{}".format(
                m, "\n" + esc(d.get("part_id")) if d.get("part_id") else "")
        return text, True

    if kind == "online":
        if d.get("online"):
            return "📡 {} bilan aloqa tiklandi".format(m), True
        return ("⚠️ <b>{} bilan aloqa uzildi</b>\n"
                "Pico USB dan uzilgan yoki kompyuter uxlab qolgan.".format(m)), False

    if kind == "reason":
        text = "📝 Sabab ko'rsatildi · {}\n{}, {} → <b>{}</b>".format(
            m, state_uz(d.get("state")).capitalize(), fmt_dur(d.get("duration_s")),
            esc(d.get("reason_name")))
        if d.get("comment"):
            text += "\n«{}»".format(esc(d.get("comment")))
        if d.get("set_by"):
            text += "\n{}".format(esc(d.get("set_by")))
        return text, True

    if kind == "startup":
        return "🚀 PRISADKA MES ishga tushdi · {}".format(esc(d.get("host"))), True

    return None, True


# ---------------------------------------------------------------- sozlama

def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    changed = False
    if not isinstance(cfg.get("chat_ids"), list):
        cfg["chat_ids"] = []
        changed = True
    if not cfg.get("join_code"):
        cfg["join_code"] = "{:06d}".format(random.SystemRandom().randrange(10 ** 6))
        changed = True
    events = dict(DEFAULT_EVENTS)
    events.update(cfg.get("events") or {})
    if events != cfg.get("events"):
        cfg["events"] = events
        changed = True
    if "summary_minutes" not in cfg:
        cfg["summary_minutes"] = 60
        changed = True
    if changed:
        save_config(path, cfg)
    return cfg


def save_config(path, cfg):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def chat_name(chat):
    return (chat.get("title")
            or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
            or chat.get("username") or str(chat.get("id")))


# ---------------------------------------------------------------- bot

class TelegramBot:
    def __init__(self, cfg_path, db_path, log=print, api=None, sleep=time.sleep):
        self.cfg_path = cfg_path
        self.db_path = db_path
        self.log = log
        self.cfg = load_config(cfg_path)
        self._api = api or self._http_api
        self._sleep = sleep
        self._q = collections.deque(maxlen=QUEUE_MAX)
        self._cv = threading.Condition()
        self._cfg_lock = threading.Lock()
        self._offset = 0
        self._stop = False
        self._net_warned_at = 0
        self._conflict_at = 0
        self._backoff = 5
        self.host = socket.gethostname()
        self.disabled = False
        self.username = None

    # ---------- Telegram API ----------
    def _http_api(self, method, payload=None, timeout=20):
        url = API_URL.format(token=self.cfg["token"], method=method)
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            body = urllib.request.urlopen(req, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read())
            except Exception:
                err = {}
            raise TelegramError(e.code, err.get("description", ""),
                                (err.get("parameters") or {}).get("retry_after"))
        res = json.loads(body)
        if not res.get("ok"):
            raise TelegramError(res.get("error_code", 0), res.get("description", ""))
        return res

    # ---------- ishga tushirish ----------
    def start(self):
        for target, name in ((self._sender, "tg-sender"), (self._poller, "tg-poller"),
                             (self._summary_loop, "tg-summary")):
            threading.Thread(target=target, daemon=True, name=name).start()
        self.log("Telegram: {} ta chat ulangan; yangi odam qo'shish kodi: {}".format(
            len(self.cfg["chat_ids"]), self.cfg["join_code"]))
        if not self.cfg["chat_ids"]:
            self.log("Telegram: hali hech kim ulanmagan - botni ochib Start bosing")
        self.notify("startup", host=socket.gethostname())

    def stop(self):
        self._stop = True
        with self._cv:
            self._cv.notify_all()

    # ---------- navbat ----------
    def notify(self, kind, **data):
        """MES hodisasi. Faqat navbatga qo'shadi - tarmoqqa chiqmaydi."""
        if self.disabled or not self.cfg["chat_ids"]:
            return
        if not self.cfg["events"].get(EVENT_GROUP.get(kind, kind), True):
            return
        try:
            text, silent = format_event(kind, data)
        except Exception as e:
            self.log("Telegram: xabar tuzilmadi ({}): {!r}".format(kind, e))
            return
        if text:
            self.enqueue(text, silent)

    def enqueue(self, text, silent=False, chat_ids=None):
        with self._cv:
            for cid in (chat_ids if chat_ids is not None else list(self.cfg["chat_ids"])):
                self._q.append((cid, text[:4000], silent, time.time()))
            self._cv.notify()

    def reply(self, chat_id, text):
        # Ikki kompyuter bitta botni talashsa, javob "noto'g'ri" kompyuterdan
        # kelib, odamni chalg'itadi (bir marta shunday bo'lgan: /holat bo'sh
        # bazadan "stanok yo'q" dedi). Ogohlantirish shu holatni darhol ko'rsatadi.
        if time.time() - self._conflict_at < CONFLICT_WARN_S:
            text += CONFLICT_NOTE
        self.enqueue(text, False, [chat_id])

    # ---------- yuboruvchi ----------
    def _send_next(self):
        """Navbatdagi bitta xabarni yuboradi.

        Qaytaradi: "empty" | "sent" | "dropped" | "retry" | "disabled".
        Testlar shu funksiyani to'g'ridan-to'g'ri chaqiradi.
        """
        with self._cv:
            if not self._q:
                return "empty"
            item = self._q[0]
        cid, text, silent, created = item
        late = time.time() - created
        if late > LATE_NOTE_S:
            text += "\n\n<i>⏱ {} kechikib yuborildi</i>".format(fmt_dur(late))
        try:
            self._api("sendMessage", {"chat_id": cid, "text": text, "parse_mode": "HTML",
                                      "disable_web_page_preview": True,
                                      "disable_notification": bool(silent)})
            status = "sent"
            self._net_warned_at = 0
        except TelegramError as e:
            if e.code == 429:
                self._sleep(min(60, e.retry_after or 5))
                return "retry"
            if e.code == 401:
                self.log("Telegram: token noto'g'ri yoki bekor qilingan - xabarlar to'xtatildi")
                self.disabled = True
                with self._cv:
                    self._q.clear()
                return "disabled"
            if e.code in (400, 403):
                self.log("Telegram: {} chatga yuborib bo'lmadi: {}".format(cid, e.description))
                status = "dropped"
            else:
                self._warn_network(e)
                self._sleep(10)
                return "retry"
        except Exception as e:
            self._warn_network(e)
            self._sleep(10)
            return "retry"
        with self._cv:
            if self._q and self._q[0] is item:
                self._q.popleft()
        return status

    def _warn_network(self, e):
        if time.time() - self._net_warned_at > 600:
            self._net_warned_at = time.time()
            self.log("Telegram: yuborib bo'lmadi ({!r}) - navbatda saqlanadi".format(e))

    def _sender(self):
        while not self._stop and not self.disabled:
            with self._cv:
                while not self._q and not self._stop:
                    self._cv.wait(5)
            if self._stop:
                return
            if self._send_next() in ("sent", "dropped"):
                self._sleep(SEND_INTERVAL)

    # ---------- buyruqlar ----------
    def _poller(self):
        try:
            me = self._api("getMe", timeout=20)["result"]
            self.username = me.get("username")
            self.log("Telegram: bot @{} ulandi".format(self.username))
        except TelegramError as e:
            if e.code == 401:
                self.log("Telegram: token noto'g'ri - bot o'chirildi")
                self.disabled = True
                return
        except Exception as e:
            self.log("Telegram: hozircha internet yo'q ({!r}), keyin qayta uriniladi".format(e))
        while not self._stop and not self.disabled:
            self._poll_once()

    def _poll_once(self):
        """Bitta getUpdates so'rovi va kelgan buyruqlarni bajarish (testlar uchun alohida)."""
        try:
            res = self._api("getUpdates", {"offset": self._offset, "timeout": 50,
                                           "allowed_updates": ["message"]}, timeout=65)
            self._backoff = 5
        except TelegramError as e:
            if e.code == 401:
                self.disabled = True
                return
            if e.code == 409:
                self._conflict_at = time.time()
                self.log("Telegram: bu bot boshqa kompyuterda ham ishlayapti (409) - "
                         "buyruqlar aralashib tushadi. Faqat bitta kompyuterda qoldiring.")
                self._sleep(60)
            else:
                self._sleep(self._backoff)
            return
        except Exception:
            self._sleep(self._backoff)
            self._backoff = min(60, self._backoff * 2)
            return
        for u in res.get("result", []):
            self._offset = u["update_id"] + 1
            try:
                self.handle_update(u)
            except Exception as e:
                self.log("Telegram: buyruq xatosi: {!r}".format(e))

    def handle_update(self, u):
        m = u.get("message") or {}
        chat = m.get("chat") or {}
        text = (m.get("text") or "").strip()
        if not chat or not text.startswith("/"):
            return
        cid = chat["id"]
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        registered = cid in self.cfg["chat_ids"]

        if cmd == "/start":
            return self._cmd_start(cid, chat_name(chat), arg.strip(), registered)
        if not registered:
            return self.reply(cid, "Bu bot PRISADKA MES uchun.\nUlanish: /start KOD")
        if cmd in ("/holat", "/status"):
            self.reply(cid, self.status_text())
        elif cmd in ("/hisobot", "/report"):
            self.reply(cid, self.report_text(local_midnight(), "Bugungi hisobot")
                       or "Bugun hali hech narsa qayd etilmagan.")
        elif cmd == "/kod":
            self.reply(cid, "Boshqa odamni ulash uchun u botga shuni yuborsin:\n"
                            "<code>/start {}</code>".format(self.cfg["join_code"]))
        elif cmd == "/stop":
            with self._cfg_lock:
                self.cfg["chat_ids"] = [c for c in self.cfg["chat_ids"] if c != cid]
                save_config(self.cfg_path, self.cfg)
            self.log("Telegram: chat uzildi: {}".format(cid))
            self.enqueue("Xabarlar to'xtatildi. Qayta ulanish: /start KOD", False, [cid])
        else:
            self.reply(cid, HELP)

    def _cmd_start(self, cid, name, code, registered):
        if registered:
            return self.reply(cid, "Siz allaqachon ulangansiz.\n\n" + HELP)
        if not self.cfg["chat_ids"] or code == self.cfg["join_code"]:
            with self._cfg_lock:
                self.cfg["chat_ids"].append(cid)
                save_config(self.cfg_path, self.cfg)
            self.log("Telegram: yangi chat ulandi: {} ({})".format(name, cid))
            return self.reply(cid, "✅ Ulandingiz. Endi PRISADKA MES xabarlari shu yerga "
                                   "keladi.\n\n" + HELP)
        self.log("Telegram: ruxsatsiz /start: {} ({})".format(name, cid))
        self.reply(cid, "Ulanish uchun kod kerak:\n/start KOD\n\n"
                        "Kodni MES administratoridan so'rang.")

    # ---------- bazadan ma'lumot ----------
    def _db(self):
        con = sqlite3.connect(self.db_path, timeout=5)
        con.row_factory = sqlite3.Row
        return con

    def status_text(self):
        con = self._db()
        try:
            now = time.time()
            midnight = local_midnight(now)
            machines = con.execute("SELECT * FROM machine_state ORDER BY machine_id").fetchall()
            if not machines:
                return ("Hali hech qaysi stanok ulanmagan.\n"
                        "💻 Javob bergan kompyuter: {}".format(esc(self.host)))
            lines = ["<b>Holat</b> · {} · 💻 {}".format(fmt_time(now), esc(self.host))]
            for mrow in machines:
                mid = mrow["machine_id"]
                st = mrow["state"]
                last = con.execute("SELECT ts FROM andon_event WHERE machine_id = ? "
                                   "ORDER BY id DESC LIMIT 1", (mid,)).fetchone()
                parts = con.execute("SELECT COUNT(*) FROM part_cycle WHERE machine_id = ? "
                                    "AND completed = 1 AND ts >= ?", (mid, midnight)).fetchone()[0]
                pending = con.execute("SELECT COUNT(*) FROM downtime WHERE machine_id = ? "
                                      "AND reason_code IS NULL", (mid,)).fetchone()[0]
                since = " · {} dan beri".format(fmt_dur(now - last["ts"])) if last else ""
                lines.append("")
                lines.append("{} <b>{}</b> — {}{}".format(
                    STATE_ICON.get(st, "⚪"), esc(mid), state_uz(st), since))
                if not mrow["online"]:
                    lines.append("⚠️ aloqa yo'q")
                if mrow["current_part_id"]:
                    lines.append("Detal: {}".format(esc(mrow["current_part_id"])))
                lines.append("Bugun detallar: {}".format(parts))
                if pending:
                    lines.append("Sababsiz to'xtashlar: {}".format(pending))
            return "\n".join(lines)
        finally:
            con.close()

    def report_text(self, since, title, until=None):
        """Davr hisoboti. Davrda hech narsa bo'lmagan bo'lsa None (jim o'tkaziladi)."""
        from . import db
        con = self._db()
        try:
            until = until or time.time()
            blocks = []
            for mrow in con.execute("SELECT * FROM machine_state ORDER BY machine_id").fetchall():
                mid = mrow["machine_id"]
                n_ev = con.execute("SELECT COUNT(*) FROM andon_event WHERE machine_id = ? "
                                   "AND ts >= ? AND ts < ?", (mid, since, until)).fetchone()[0]
                if not n_ev:
                    continue
                cs = con.execute("SELECT COUNT(*) n, AVG(process_s) p FROM part_cycle "
                                 "WHERE machine_id = ? AND completed = 1 AND ts >= ? AND ts < ?",
                                 (mid, since, until)).fetchone()
                av, proc_s, total_s = db.availability(con, mid, since)
                dt = con.execute("SELECT COUNT(*) n, COALESCE(SUM(COALESCE(duration_s, ? - started_at)), 0) s, "
                                 "SUM(CASE WHEN reason_code IS NULL THEN 1 ELSE 0 END) pend "
                                 "FROM downtime WHERE machine_id = ? AND started_at >= ? AND started_at < ?",
                                 (int(until), mid, since, until)).fetchone()
                top = con.execute("SELECT r.name_uz, SUM(d.duration_s) s FROM downtime d "
                                  "JOIN downtime_reason r ON r.code = d.reason_code "
                                  "WHERE d.machine_id = ? AND d.started_at >= ? AND d.started_at < ? "
                                  "GROUP BY r.name_uz ORDER BY s DESC LIMIT 3",
                                  (mid, since, until)).fetchall()
                b = ["{} <b>{}</b> — hozir {}".format(STATE_ICON.get(mrow["state"], "⚪"),
                                                      esc(mid), state_uz(mrow["state"]))]
                b.append("Detallar: {}{}".format(
                    cs["n"], " · o'rt. ishlov {}".format(fmt_dur(cs["p"])) if cs["n"] else ""))
                if av is not None:
                    b.append("Ishlov vaqti: {} %".format(round(av)))
                if dt["n"]:
                    b.append("To'xtashlar: {} ta, jami {}{}".format(
                        dt["n"], fmt_dur(dt["s"]),
                        " · sababsiz: {}".format(dt["pend"]) if dt["pend"] else ""))
                for r in top:
                    b.append("  · {} — {}".format(esc(r["name_uz"]), fmt_dur(r["s"])))
                blocks.append("\n".join(b))
            if not blocks:
                return None
            head = "📊 <b>{}</b> · {}–{} · 💻 {}".format(
                title, fmt_time(since), fmt_time(until), esc(self.host))
            return head + "\n\n" + "\n\n".join(blocks)
        finally:
            con.close()

    def _summary_loop(self):
        minutes = int(self.cfg.get("summary_minutes") or 0)
        if minutes <= 0:
            return
        period = minutes * 60
        offset = time.localtime().tm_gmtoff        # davrni mahalliy soatga tekislash
        while not self._stop and not self.disabled:
            now = time.time()
            next_t = ((int(now + offset) // period) + 1) * period - offset
            while time.time() < next_t and not self._stop:
                self._sleep(min(30, max(1, next_t - time.time())))
            if self._stop or not self.cfg["chat_ids"]:
                continue
            title = "Soatlik hisobot" if minutes == 60 else "{} daqiqalik hisobot".format(minutes)
            try:
                text = self.report_text(next_t - period, title, until=next_t)
            except Exception as e:
                self.log("Telegram: hisobot tuzilmadi: {!r}".format(e))
                continue
            if text:                                   # tinch davr - jim o'tkazamiz
                self.enqueue(text, silent=True)


def load_bot(cfg_path, db_path, log=print):
    """telegram.json bo'lsa botni qaytaradi, bo'lmasa None."""
    if not os.path.exists(cfg_path):
        return None
    try:
        cfg = load_config(cfg_path)
    except Exception as e:
        log("Telegram: {} o'qilmadi: {!r}".format(cfg_path, e))
        return None
    if not cfg.get("token"):
        log("Telegram: {} da token yo'q".format(cfg_path))
        return None
    return TelegramBot(cfg_path, db_path, log=log)
