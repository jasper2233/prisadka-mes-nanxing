-- PRISADKA MES — Andon ma'lumotlar bazasi (PostgreSQL)
-- Pico dan kelgan MQTT xabarlari shu jadvallarga yoziladi.

-- ============================================================
-- 1. Bahonalar (to'xtash sabablari) ro'yxati
--    MES da saqlanadi, vaqt o'tishi bilan to'ldirib boriladi.
-- ============================================================
CREATE TABLE downtime_reason (
    id         SERIAL PRIMARY KEY,
    code       TEXT UNIQUE NOT NULL,
    name_uz    TEXT NOT NULL,
    category   TEXT NOT NULL,   -- TEXNIK | XOMASHYO | TASHKILIY | REJALI | SIFAT
    -- qaysi holatlarga mos: OFF = uchchala chiroq ham o'chiq (stanok o'chirilgan)
    for_state  TEXT[] DEFAULT '{FAULT,STOPPED,OFF}',
    needs_note BOOLEAN DEFAULT FALSE,
    active     BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 100
);

INSERT INTO downtime_reason (code, name_uz, category, needs_note, sort_order) VALUES
    ('RAW_EMPTY',     'Xomashyo tugadi',              'XOMASHYO',   FALSE, 10),
    ('RAW_QUALITY',   'Xomashyo sifati mos emas',     'XOMASHYO',   TRUE,  20),
    ('DOSE_ERR',      'Dozalash xatosi',              'TEXNIK',     FALSE, 30),
    ('PUMP_FAIL',     'Nasos nosozligi',              'TEXNIK',     FALSE, 40),
    ('MIXER_FAIL',    'Aralashtirgich nosozligi',     'TEXNIK',     FALSE, 50),
    ('FILTER_CLOG',   'Filtr tiqildi',                'TEXNIK',     FALSE, 60),
    ('HEATER_FAIL',   'Qizdirgich nosozligi',         'TEXNIK',     FALSE, 70),
    ('TEMP_DEV',      'Harorat me''yordan chiqdi',    'TEXNIK',     FALSE, 80),
    ('PRESSURE_LOW',  'Havo bosimi past',             'TEXNIK',     FALSE, 90),
    ('LEAK',          'Germetiklik buzilgan',         'TEXNIK',     TRUE, 100),
    ('POWER_CUT',     'Elektr uzilishi',              'TEXNIK',     FALSE, 110),
    ('SCANNER_FAIL',  'QR skaner ishlamadi',          'TEXNIK',     FALSE, 120),
    ('SHIFT_END',     'Smena tugadi - stanok o''chirildi', 'REJALI',  FALSE, 125),
    ('RECIPE_CHANGE', 'Retsept almashinuvi',          'REJALI',     FALSE, 130),
    ('CLEANING',      'Tozalash / yuvish',            'REJALI',     FALSE, 140),
    ('MAINTENANCE',   'Rejali ta''mir (PM)',          'REJALI',     FALSE, 150),
    ('NO_OPERATOR',   'Operator yo''q',               'TASHKILIY',  FALSE, 160),
    ('BREAK',         'Tanaffus / smena almashinuvi', 'TASHKILIY',  FALSE, 170),
    ('QC_HOLD',       'Sifat nazorati ushlab turdi',  'SIFAT',      TRUE, 180),
    ('OTHER',         'Boshqa',                       'TASHKILIY',  TRUE, 999);

-- ============================================================
-- 2. Xom eventlar
-- ============================================================
-- MUHIM: `seq` Pico qayta yuklanganda noldan boshlanadi. Shuning uchun
-- yagona kalit (machine_id, session, seq) - `session` har yuklanishda
-- yangilanadigan 6 belgili id. Faqat seq bo'yicha kalit qo'yilsa,
-- reboot'dan keyingi haqiqiy eventlar dublikat deb rad etiladi.
CREATE TABLE andon_event (
    id              BIGSERIAL PRIMARY KEY,
    machine_id      TEXT NOT NULL,
    session         TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    state           TEXT NOT NULL,
    prev_state      TEXT,
    prev_duration_s INTEGER,
    lamps           JSONB,
    part_id         TEXT,
    UNIQUE (machine_id, session, seq)       -- takroriy yuborishdan himoya
);
CREATE INDEX ON andon_event (machine_id, ts DESC);

-- ts = 0 kelsa (NTP hali sinxronlanmagan) server received_at ni qo'yadi:
--   INSERT ... VALUES (..., CASE WHEN $ts = 0 THEN now() ELSE to_timestamp($ts) END, ...)
--   ON CONFLICT (machine_id, session, seq) DO NOTHING;

-- ============================================================
-- 3. To'xtashlar (sabab shu yerga yoziladi)
-- ============================================================
-- Ochilishi:  eventda `downtime_id` + `reason_required` keladi -> INSERT.
-- Yopilishi:  eventda `closes_downtime_id` keladi -> UPDATE ended_at/duration_s.
-- DIQQAT: bitta event ikkalasini ham olib kelishi mumkin (STOPPED -> FAULT
-- o'tishi eskisini yopadi va yangisini ochadi). Ikkala maydonni ham tekshiring.
CREATE TABLE downtime (
    downtime_id TEXT PRIMARY KEY,   -- Pico beradi: PRISADKA-01-a3f19c-142
    machine_id  TEXT NOT NULL,
    session     TEXT NOT NULL,
    state       TEXT NOT NULL,      -- FAULT | STOPPED | OFF
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ,
    duration_s  INTEGER,
    reason_code TEXT REFERENCES downtime_reason(code),
    comment     TEXT,
    set_by      TEXT,
    set_at      TIMESTAMPTZ
);
CREATE INDEX ON downtime (machine_id, started_at DESC);
CREATE INDEX ON downtime (reason_code) WHERE reason_code IS NULL;

-- ============================================================
-- 4. Detal sikllari
-- ============================================================
CREATE TABLE part_cycle (
    id         BIGSERIAL PRIMARY KEY,
    machine_id TEXT NOT NULL,
    session    TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    ts         TIMESTAMPTZ NOT NULL,
    part_id    TEXT,
    wait_s     INTEGER,            -- QR skandan ishlov boshlanguncha
    process_s  INTEGER,            -- sof ishlov vaqti
    completed  BOOLEAN,
    UNIQUE (machine_id, session, seq)
);
-- Eventdagi `part_count` boot'dan beri hisoblanadi va reboot'da nolga tushadi -
-- detallar sonini shu jadvaldagi qatorlardan sanang, event maydonidan emas.
CREATE INDEX ON part_cycle (machine_id, ts DESC);

-- ============================================================
-- 5. Hisobot so'rovlari
-- ============================================================

-- Sababsiz to'xtashlar (operator ekranida shu ro'yxat chiqadi)
-- SELECT downtime_id, machine_id, state, started_at, duration_s
-- FROM downtime
-- WHERE reason_code IS NULL AND ended_at IS NOT NULL
-- ORDER BY started_at;

-- Availability (OEE birinchi komponenti)
-- SELECT machine_id,
--        SUM(prev_duration_s) FILTER (WHERE prev_state = 'PROCESSING')::numeric
--          / NULLIF(SUM(prev_duration_s), 0) * 100 AS availability_pct
-- FROM andon_event
-- WHERE ts >= now() - INTERVAL '24 hours'
-- GROUP BY machine_id;

-- Eng ko'p vaqt yeyayotgan sabablar (Pareto)
-- SELECT r.name_uz, r.category, COUNT(*) AS holatlar, SUM(d.duration_s)/60 AS daqiqa
-- FROM downtime d JOIN downtime_reason r ON r.code = d.reason_code
-- WHERE d.started_at >= now() - INTERVAL '7 days'
-- GROUP BY r.name_uz, r.category
-- ORDER BY daqiqa DESC;

-- Sikl vaqti statistikasi
-- SELECT machine_id, COUNT(*) AS detallar,
--        ROUND(AVG(process_s)) AS ortacha_ishlov_s,
--        ROUND(AVG(wait_s))    AS ortacha_kutish_s,
--        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY process_s) AS p95_ishlov_s
-- FROM part_cycle
-- WHERE completed AND ts >= now() - INTERVAL '24 hours'
-- GROUP BY machine_id;
