"""Yig'ilgan ma'lumotni fayllarga chiqarish (CSV / JSON).

Ikki vazifasi bor:

1. **Bugun:** MES PRO muhandislariga namuna fayl berish \u2014 ular jadval
   tuzilishini ko'rib, qayerga yozishni aytishadi.
2. **Keyin:** shu modul MES PRO bazasiga yozadigan joyga aylanadi.
   `rows_for()` funksiyalari o'zgarmaydi, faqat yozish usuli almashadi.

Ishlatish:
    python -m mes.export                      # oxirgi 1 kun, CSV
    python -m mes.export --days 7 --format json
    python -m mes.export --machine PRISADKA-01 --out D:/eksport
"""

import argparse
import csv
import io
import json
import os
import sys
import time

from . import db

# Chiqariladigan oqimlar. MES PRO tomoniga aynan shu maydonlar beriladi.
STREAMS = {
    "downtime": """
        SELECT d.downtime_id, d.machine_id, d.session, d.state,
               d.started_at, d.ended_at, d.duration_s,
               d.reason_code, r.name_uz AS reason_name, r.category AS reason_category,
               d.comment, d.set_by, d.set_at
        FROM downtime d
        LEFT JOIN downtime_reason r ON r.code = d.reason_code
        WHERE d.started_at >= ? {mf}
        ORDER BY d.started_at""",
    "part_cycle": """
        SELECT id, machine_id, session, seq, ts, part_id,
               wait_s, process_s, completed
        FROM part_cycle
        WHERE ts >= ? {mf}
        ORDER BY ts""",
    "andon_event": """
        SELECT id, machine_id, session, seq, ts, received_at, state,
               prev_state, prev_duration_s, part_id, lamps
        FROM andon_event
        WHERE ts >= ? {mf}
        ORDER BY ts""",
}

TIME_COLS = ("started_at", "ended_at", "set_at", "ts", "received_at", "scanned_at")


def iso(v):
    """Unix soniyani o'qiladigan ko'rinishga o'tkazadi."""
    if not v:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(v)))


def rows_for(con, stream, since_ts, machine=None):
    sql = STREAMS[stream].format(mf="AND machine_id = ?" if machine else "")
    args = (since_ts, machine) if machine else (since_ts,)
    out = []
    for r in con.execute(sql, args).fetchall():
        d = dict(r)
        for c in TIME_COLS:
            if c in d:
                d[c + "_iso"] = iso(d[c])
        out.append(d)
    return out


def write_csv(path, rows):
    if not rows:
        # bo'sh bo'lsa ham fayl yaratamiz - ustunlar ko'rinib tursin
        open(path, "w", encoding="utf-8-sig").close()
        return 0
    # utf-8-sig: Excel o'zbekcha matnni to'g'ri ochishi uchun
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def write_json(path, rows):
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    return len(rows)


def main():
    p = argparse.ArgumentParser(description="MES ma'lumotini fayllarga chiqarish")
    p.add_argument("--days", type=float, default=1, help="necha kunlik (standart 1)")
    p.add_argument("--machine", default=None, help="faqat shu stanok")
    p.add_argument("--format", choices=("csv", "json"), default="csv")
    p.add_argument("--out", default="eksport", help="papka")
    p.add_argument("--db", default=None)
    args = p.parse_args()

    con = db.connect(args.db)
    since = db.now() - int(args.days * 86400)
    os.makedirs(args.out, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M")
    total = 0
    print("Davr: {} dan hozirgacha".format(iso(since)))
    if args.machine:
        print("Stanok: {}".format(args.machine))
    print("-" * 52)
    for stream in STREAMS:
        rows = rows_for(con, stream, since, args.machine)
        name = "{}-{}.{}".format(stream, stamp, args.format)
        path = os.path.join(args.out, name)
        n = write_csv(path, rows) if args.format == "csv" else write_json(path, rows)
        total += n
        print("  {:14} {:>6} qator  ->  {}".format(stream, n, path))
    print("-" * 52)
    print("Jami {} qator. Papka: {}".format(total, os.path.abspath(args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
