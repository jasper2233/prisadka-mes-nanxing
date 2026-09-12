"""MES veb-interfeysi: monitor, operator ekrani, hisobot, sinov paneli.

Minimal asyncio HTTP server - tashqi kutubxonasiz. Sahifa `ui.html` da.
"""

import json
import os
import time

from . import db

UI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html")
DAY = 86400


class Web:
    def __init__(self, con, broker, host="0.0.0.0", port=8080, log=print):
        self.con = con
        self.broker = broker
        self.host = host
        self.port = port
        self.log = log

    # ---------------------------------------------------------- HTTP qatlami
    async def handle(self, reader, writer):
        try:
            line = await reader.readline()
            if not line:
                return
            try:
                method, path, _ = line.decode("latin-1").split(" ", 2)
            except ValueError:
                return
            headers = {}
            while True:
                h = await reader.readline()
                if h in (b"\r\n", b"\n", b""):
                    break
                k, _, v = h.decode("latin-1").partition(":")
                headers[k.strip().lower()] = v.strip()
            body = b""
            n = int(headers.get("content-length", 0) or 0)
            if n:
                body = await reader.readexactly(n)

            status, ctype, payload = self.route(method, path, body)
            writer.write(
                ("HTTP/1.1 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\n"
                 "Cache-Control: no-store\r\nConnection: close\r\n\r\n"
                 .format(status, ctype, len(payload))).encode("latin-1"))
            writer.write(payload)
            await writer.drain()
        except Exception as e:
            self.log("web xatosi: {!r}".format(e))
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def route(self, method, path, body):
        qs = ""
        if "?" in path:
            path, qs = path.split("?", 1)
        try:
            if method == "GET" and path in ("/", "/index.html"):
                with open(UI_PATH, "rb") as f:
                    return "200 OK", "text/html; charset=utf-8", f.read()
            if method == "GET" and path == "/api/snapshot":
                return self.json_ok(self.snapshot(parse_qs(qs)))
            if method == "POST" and path == "/api/reason":
                return self.json_ok(self.set_reason(json.loads(body or b"{}")))
            if method == "POST" and path == "/api/cmd":
                return self.json_ok(self.send_cmd(json.loads(body or b"{}")))
            if method == "POST" and path == "/api/scan":
                return self.json_ok(self.add_scan(json.loads(body or b"{}")))
            if method == "POST" and path == "/api/lamps":
                return self.json_ok(self.set_lamps(json.loads(body or b"{}")))
        except Exception as e:
            self.log("so'rov xatosi {} {}: {!r}".format(method, path, e))
            return ("400 Bad Request", "application/json",
                    json.dumps({"error": str(e)}).encode("utf-8"))
        return "404 Not Found", "text/plain; charset=utf-8", b"topilmadi"

    def json_ok(self, data):
        return ("200 OK", "application/json; charset=utf-8",
                json.dumps(data, ensure_ascii=False).encode("utf-8"))

    # ---------------------------------------------------------- ma'lumotlar
    def snapshot(self, q):
        now = db.now()
        since = now - DAY
        machines = []
        for r in self.con.execute(
                "SELECT * FROM machine_state ORDER BY machine_id").fetchall():
            m = dict(r)
            av, proc_s, total_s = db.availability(self.con, m["machine_id"], since)
            m["availability"] = av
            m["proc_s"] = proc_s
            m["total_s"] = total_s
            m["pending"] = self.con.execute(
                "SELECT COUNT(*) c FROM downtime "
                "WHERE machine_id = ? AND reason_code IS NULL",
                (m["machine_id"],)).fetchone()["c"]
            m["stale_s"] = now - (m["updated_at"] or now)
            m["cycle_stats"] = dict(db.cycle_stats(self.con, m["machine_id"], since))
            machines.append(m)

        mid = q.get("machine")
        where = "WHERE machine_id = ?" if mid else ""
        args = (mid,) if mid else ()

        pending = [dict(r) for r in db.pending_downtimes(self.con)]
        for d in pending:
            d["duration_s"] = d["duration_s"] if d["ended_at"] else now - d["started_at"]
            d["open"] = d["ended_at"] is None

        events = [dict(r) for r in self.con.execute(
            "SELECT * FROM andon_event {} ORDER BY id DESC LIMIT 60".format(where),
            args).fetchall()]
        cycles = [dict(r) for r in self.con.execute(
            "SELECT * FROM part_cycle {} ORDER BY id DESC LIMIT 30".format(where),
            args).fetchall()]
        scans = [dict(r) for r in self.con.execute(
            "SELECT * FROM part_scan {} ORDER BY id DESC LIMIT 15".format(where),
            args).fetchall()]
        done = [dict(r) for r in self.con.execute(
            "SELECT d.*, r.name_uz FROM downtime d "
            "LEFT JOIN downtime_reason r ON r.code = d.reason_code "
            "WHERE d.reason_code IS NOT NULL ORDER BY d.started_at DESC LIMIT 20"
        ).fetchall()]

        return {
            "now": now,
            "machines": machines,
            "pending": pending,
            "resolved": done,
            "reasons": [dict(r) for r in self.con.execute(
                "SELECT * FROM downtime_reason WHERE active = 1 "
                "ORDER BY sort_order").fetchall()],
            "events": events,
            "cycles": cycles,
            "scans": scans,
            "pareto": [dict(r) for r in db.reason_pareto(self.con, since)],
        }

    # ---------------------------------------------------------- amallar
    def set_reason(self, d):
        code = d.get("reason_code")
        row = self.con.execute(
            "SELECT needs_note FROM downtime_reason WHERE code = ?",
            (code,)).fetchone()
        if row is None:
            raise ValueError("noma'lum sabab: {}".format(code))
        comment = (d.get("comment") or "").strip()
        if row["needs_note"] and not comment:
            raise ValueError("bu sabab uchun izoh majburiy")
        cur = self.con.execute("""
            UPDATE downtime SET reason_code = ?, comment = ?, set_by = ?, set_at = ?
            WHERE downtime_id = ?""",
            (code, comment or None, d.get("set_by") or "operator",
             db.now(), d.get("downtime_id")))
        self.con.commit()
        if not cur.rowcount:
            raise ValueError("to'xtash topilmadi")
        self.log("sabab: {} -> {}".format(d.get("downtime_id"), code))
        return {"ok": True}

    def send_cmd(self, d):
        mid = d.get("machine_id")
        payload = d.get("payload") or {}
        if not mid or not isinstance(payload, dict) or not payload:
            raise ValueError("machine_id va payload kerak")
        topic = "mes/andon/{}/cmd".format(mid)
        self.broker.publish_nowait(topic, json.dumps(payload))
        self.log("cmd -> {}: {}".format(mid, payload))
        return {"ok": True, "topic": topic}

    def add_scan(self, d):
        """QR nakleyka o'qildi (haqiqiy MES da bu skanerdan keladi)."""
        mid = d.get("machine_id")
        part = (d.get("part_id") or "").strip()
        if not mid or not part:
            raise ValueError("machine_id va part_id kerak")
        self.con.execute(
            "INSERT INTO part_scan (machine_id, part_id, scanned_at) VALUES (?,?,?)",
            (mid, part, int(d.get("scanned_at") or db.now())))
        self.con.commit()
        self.log("QR skan: {} <- {}".format(mid, part))
        return {"ok": True}

    def set_lamps(self, d):
        """Virtual signal ustuni - simulyatorga yuboriladi (faqat sinov uchun)."""
        mid = d.get("machine_id")
        if not mid:
            raise ValueError("machine_id kerak")
        lamps = {k: d.get(k, "off") for k in ("green", "yellow", "red")}
        self.broker.publish_nowait("sim/{}/lamps".format(mid), json.dumps(lamps))
        return {"ok": True, "lamps": lamps}

    async def serve(self):
        import asyncio
        server = await asyncio.start_server(self.handle, self.host, self.port)
        self.log("MES veb: http://localhost:{}".format(self.port))
        return server


def parse_qs(qs):
    out = {}
    for pair in qs.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k] = v.replace("+", " ")
    return out
