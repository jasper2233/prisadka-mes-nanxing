"""MES bazasi (SQLite).

Tuzilishi `docs/mes-schema.sql` (PostgreSQL) ning aynan o'zi - prototipda
PostgreSQL o'rnatmaslik uchun SQLite ishlatiladi. Vaqtlar unix soniyada
(INTEGER) saqlanadi.
"""

import os
import sqlite3
import sys
import time


def _data_dir():
    """.exe ichida ishlaganda baza vaqtinchalik papkaga tushmasligi kerak -
    aks holda dastur yopilganda hamma ma'lumot yo'qoladi."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


DEFAULT_PATH = os.path.join(_data_dir(), "mes-data.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS downtime_reason (
    code       TEXT PRIMARY KEY,
    name_uz    TEXT NOT NULL,
    category   TEXT NOT NULL,
    needs_note INTEGER DEFAULT 0,
    active     INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 100,
    -- qaysi holatlarga mos keladi: "Xomashyo tugadi" stanok o'chirilganiga
    -- bahona bo'lolmaydi, "Smena tugadi" esa avariyaga bahona bo'lolmaydi
    for_state  TEXT DEFAULT 'FAULT,STOPPED,OFF'
);

-- seq Pico qayta yuklanganda noldan boshlanadi, shuning uchun yagona kalitda
-- `session` ham bor (har yuklanishda yangilanadigan 6 belgili id).
CREATE TABLE IF NOT EXISTS andon_event (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id      TEXT NOT NULL,
    session         TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    ts              INTEGER NOT NULL,
    received_at     INTEGER NOT NULL,
    state           TEXT NOT NULL,
    prev_state      TEXT,
    prev_duration_s INTEGER,
    lamps           TEXT,
    part_id         TEXT,
    UNIQUE (machine_id, session, seq)
);
CREATE INDEX IF NOT EXISTS ix_event_machine ON andon_event (machine_id, ts DESC);

CREATE TABLE IF NOT EXISTS downtime (
    downtime_id TEXT PRIMARY KEY,
    machine_id  TEXT NOT NULL,
    session     TEXT NOT NULL,
    state       TEXT NOT NULL,
    started_at  INTEGER NOT NULL,
    ended_at    INTEGER,
    duration_s  INTEGER,
    reason_code TEXT REFERENCES downtime_reason(code),
    comment     TEXT,
    set_by      TEXT,
    set_at      INTEGER
);
CREATE INDEX IF NOT EXISTS ix_downtime_machine ON downtime (machine_id, started_at DESC);

CREATE TABLE IF NOT EXISTS part_cycle (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id TEXT NOT NULL,
    session    TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    ts         INTEGER NOT NULL,
    part_id    TEXT,
    wait_s     INTEGER,
    process_s  INTEGER,
    completed  INTEGER,
    UNIQUE (machine_id, session, seq)
);
CREATE INDEX IF NOT EXISTS ix_cycle_machine ON part_cycle (machine_id, ts DESC);

-- QR skan MES tizimidan keladi (stanok progasiga ham parallel ketadi).
-- Pico da skaner yo'q, shuning uchun detal raqami shu jadval orqali bog'lanadi.
CREATE TABLE IF NOT EXISTS part_scan (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id TEXT NOT NULL,
    part_id    TEXT NOT NULL,
    scanned_at INTEGER NOT NULL,
    consumed   INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_scan_machine ON part_scan (machine_id, scanned_at DESC);

-- Oxirgi retained snapshot + onlayn holati
CREATE TABLE IF NOT EXISTS machine_state (
    machine_id      TEXT PRIMARY KEY,
    site            TEXT,
    session         TEXT,
    state           TEXT,
    since_s         INTEGER,
    lamps           TEXT,
    part_count      INTEGER,
    current_part_id TEXT,       -- hozir ishlanayotgan detal
    closing_part_id TEXT,       -- yangi QR keldi, lekin oldingi sikl hali yopilmagan
    idle_timeout_s  INTEGER,
    idle_timeout_enabled INTEGER,
    uptime_s        INTEGER,
    queued          INTEGER,
    dropped         INTEGER,
    rssi            INTEGER,
    online          INTEGER DEFAULT 0,
    updated_at      INTEGER
);
"""

REASONS = [
    # (kod, nom, turkum, izoh majburiymi, tartib, qaysi holatlarga mos)
    ("RAW_EMPTY",     "Xomashyo tugadi",              "XOMASHYO",   0, 10,  "FAULT,STOPPED"),
    ("RAW_QUALITY",   "Xomashyo sifati mos emas",     "XOMASHYO",   1, 20,  "FAULT,STOPPED"),
    ("DOSE_ERR",      "Dozalash xatosi",              "TEXNIK",     0, 30,  "FAULT"),
    ("PUMP_FAIL",     "Nasos nosozligi",              "TEXNIK",     0, 40,  "FAULT"),
    ("MIXER_FAIL",    "Aralashtirgich nosozligi",     "TEXNIK",     0, 50,  "FAULT"),
    ("FILTER_CLOG",   "Filtr tiqildi",                "TEXNIK",     0, 60,  "FAULT"),
    ("HEATER_FAIL",   "Qizdirgich nosozligi",         "TEXNIK",     0, 70,  "FAULT"),
    ("TEMP_DEV",      "Harorat me'yordan chiqdi",     "TEXNIK",     0, 80,  "FAULT"),
    ("PRESSURE_LOW",  "Havo bosimi past",             "TEXNIK",     0, 90,  "FAULT,STOPPED"),
    ("LEAK",          "Germetiklik buzilgan",         "TEXNIK",     1, 100, "FAULT"),
    ("POWER_CUT",     "Elektr uzilishi",              "TEXNIK",     0, 110, "FAULT,STOPPED,OFF"),
    ("SCANNER_FAIL",  "QR skaner ishlamadi",          "TEXNIK",     0, 120, "STOPPED"),
    ("SHIFT_END",     "Smena tugadi - stanok o'chirildi", "REJALI",  0, 125, "OFF"),
    ("RECIPE_CHANGE", "Retsept almashinuvi",          "REJALI",     0, 130, "STOPPED,OFF"),
    ("CLEANING",      "Tozalash / yuvish",            "REJALI",     0, 140, "STOPPED,OFF"),
    ("MAINTENANCE",   "Rejali ta'mir (PM)",           "REJALI",     0, 150, "STOPPED,OFF"),
    ("NO_OPERATOR",   "Operator yo'q",                "TASHKILIY",  0, 160, "STOPPED,OFF"),
    ("BREAK",         "Tanaffus / smena almashinuvi", "TASHKILIY",  0, 170, "STOPPED,OFF"),
    ("QC_HOLD",       "Sifat nazorati ushlab turdi",  "SIFAT",      1, 180, "FAULT,STOPPED"),
    ("OTHER",         "Boshqa",                       "TASHKILIY",  1, 999, "FAULT,STOPPED,OFF"),
]


def connect(path=None):
    path = path or DEFAULT_PATH
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    # eski bazaga ustun qo'shish (prototip migratsiyasi)
    for stmt in ("ALTER TABLE machine_state ADD COLUMN closing_part_id TEXT",
                 "ALTER TABLE downtime_reason ADD COLUMN for_state TEXT "
                 "DEFAULT 'FAULT,STOPPED,OFF'"):
        try:
            con.execute(stmt)
        except Exception:
            pass
    # Ro'yxat kodda turadi, shuning uchun mavjud qatorlar ham yangilanadi.
    con.executemany(
        "INSERT INTO downtime_reason "
        "(code, name_uz, category, needs_note, sort_order, for_state) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(code) DO UPDATE SET name_uz=excluded.name_uz, "
        "category=excluded.category, needs_note=excluded.needs_note, "
        "sort_order=excluded.sort_order, for_state=excluded.for_state",
        REASONS)
    con.commit()
    return con


def now():
    return int(time.time())


# ---------------------------------------------------------------- so'rovlar

def pending_downtimes(con, limit=200):
    """Sababi ko'rsatilmagan to'xtashlar - operator ekranidagi ro'yxat."""
    return con.execute("""
        SELECT * FROM downtime
        WHERE reason_code IS NULL
        ORDER BY (ended_at IS NULL) DESC, started_at DESC
        LIMIT ?""", (limit,)).fetchall()


def availability(con, machine_id, since_s):
    """Availability = ishlov vaqti / umumiy qayd etilgan vaqt."""
    row = con.execute("""
        SELECT
          COALESCE(SUM(CASE WHEN prev_state='PROCESSING'
                            THEN prev_duration_s END), 0) AS proc_s,
          COALESCE(SUM(prev_duration_s), 0) AS total_s
        FROM andon_event
        WHERE machine_id = ? AND ts >= ? AND prev_state <> 'BOOT'
        """, (machine_id, since_s)).fetchone()
    total = row["total_s"] or 0
    return (round(row["proc_s"] * 100.0 / total, 1) if total else None,
            row["proc_s"], total)


def reason_pareto(con, since_s, limit=10):
    return con.execute("""
        SELECT r.name_uz, r.category, COUNT(*) AS holatlar,
               COALESCE(SUM(d.duration_s), 0) AS soniya
        FROM downtime d JOIN downtime_reason r ON r.code = d.reason_code
        WHERE d.started_at >= ?
        GROUP BY r.name_uz, r.category
        ORDER BY soniya DESC
        LIMIT ?""", (since_s, limit)).fetchall()


def cycle_stats(con, machine_id, since_s):
    return con.execute("""
        SELECT COUNT(*) AS detallar,
               ROUND(AVG(process_s)) AS ortacha_ishlov_s,
               ROUND(AVG(wait_s))    AS ortacha_kutish_s,
               MAX(process_s)        AS max_ishlov_s
        FROM part_cycle
        WHERE machine_id = ? AND completed = 1 AND ts >= ?
        """, (machine_id, since_s)).fetchone()
