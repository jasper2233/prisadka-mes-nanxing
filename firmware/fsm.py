# Stanok holati mashinasi.
#
#   qizil (yoniq yoki miltillash)  -> FAULT       avariya, MES da sabab talab qilinadi
#   yashil miltillash              -> AWAIT_PART  QR skan qilindi, detal kutilmoqda
#   yashil doimiy                  -> PROCESSING  detalga ishlov berilmoqda
#   sariq                          -> IDLE        kutish rejimi
#   sariq + timeout                -> STOPPED     o'chiq deb qayd etiladi
#   hammasi o'chiq                 -> OFF
#
# Prioritet: qizil > yashil > sariq.

import time

PROCESSING = "PROCESSING"
AWAIT_PART = "AWAIT_PART"
FAULT = "FAULT"
IDLE = "IDLE"
STOPPED = "STOPPED"
OFF = "OFF"

# Bu holatlar uchun MES da sabab (bahona) tanlanishi kerak.
# OFF ham shu yerda: uchchala chiroq ham o'chiq = stanok o'chirilgan.
# Smena tugadimi, elektr uzildimi, rejali ta'mirmi - buni faqat odam biladi.
REASON_STATES = (FAULT, STOPPED, OFF)


def new_session():
    """Har yuklanishda yangi tasodifiy sessiya id (6 hex belgi).

    `seq` reboot'dan keyin noldan boshlanadi. Shu sababli MES dagi yagona kalit
    (machine_id, session, seq) bo'lishi shart, aks holda qayta yuklanishdan
    keyingi eventlar eski yozuvlar bilan to'qnashadi va yo'qoladi.

    Ataylab flash'ga yozilmaydi: qurilma reset tsikliga tushib qolsa, hisoblagich
    flash resursini yeb qo'yardi.
    """
    try:
        import os
        return "".join("{:02x}".format(b) for b in os.urandom(3))
    except Exception:                       # urandom yo'q bo'lsa - zaxira variant
        return "{:06x}".format(time.ticks_ms() & 0xFFFFFF)


class Fsm:
    def __init__(self, cfg, st, emit, scanner=None, session=None):
        self.cfg = cfg
        self.emit = emit
        self.scanner = scanner
        self.session = session or new_session()
        self.apply(st)

        now = time.ticks_ms()
        self.state = None
        self.state_at = now
        self.seq = 0
        self.part_count = 0
        self.part_id = None

        self._cand = None
        self._cand_at = now
        self._idle_since = None
        self._wait_ms = 0
        self._proc_ms = 0
        self._dt_id = None

    def apply(self, st):
        """Sozlamalarni qo'llash (MQTT cmd kelganda ham chaqiriladi)."""
        self.idle_timeout_ms = int(st["idle_timeout_s"]) * 1000
        self.idle_timeout_on = bool(st["idle_timeout_enabled"])
        # OFF uchun alohida, uzunroq tasdiqlash vaqti - pastdagi izohga qarang
        self.off_confirm_ms = getattr(self.cfg, "OFF_CONFIRM_MS", 5000)

    def elapsed_s(self, now):
        return time.ticks_diff(now, self.state_at) // 1000

    # ---------- chiroqlardan holat ----------
    def _base(self, status, now):
        if status.get("red", "off") != "off":
            self._idle_since = None
            return FAULT

        green = status.get("green", "off")
        if green == "on":
            self._idle_since = None
            return PROCESSING
        if green == "blink":
            self._idle_since = None
            return AWAIT_PART

        if status.get("yellow", "off") != "off":
            # sariq uzluksiz yonayotgan vaqtni alohida sanaymiz,
            # shunda IDLE -> STOPPED o'tgach orqaga qaytib ketmaydi
            if self._idle_since is None:
                self._idle_since = now
            if self.idle_timeout_on and \
                    time.ticks_diff(now, self._idle_since) >= self.idle_timeout_ms:
                return STOPPED
            return IDLE

        self._idle_since = None
        return OFF

    # ---------- har o'qishda chaqiriladi ----------
    def update(self, now, status, ts):
        base = self._base(status, now)

        if base == self.state:
            self._cand = None
            return
        if base != self._cand:
            self._cand = base
            self._cand_at = now
            return
        # OFF ga uzunroq tasdiqlash kerak: PLC bir chiroqni o'chirib,
        # ikkinchisini yoqguncha oraliqda hamma chiroq o'chiq bo'lib qolishi
        # mumkin. Bu "stanok o'chdi" emas - shunchaki o'tish pallasi.
        need = self.off_confirm_ms if base == OFF else self.cfg.MIN_STATE_MS
        if time.ticks_diff(now, self._cand_at) < need:
            return
        self._commit(base, now, status, ts)

    def _commit(self, new, now, status, ts):
        prev = self.state or "BOOT"
        # Vaqt hisobi commit paytidan emas, nomzod PAYDO BO'LGAN paytdan olinadi.
        # Shu tufayli MIN_STATE_MS ni oshirsa ham davomiyliklar aniq qoladi
        # (event kechroq yuboriladi, lekin o'tish vaqti haqiqiy vaqt bo'ladi).
        at = self._cand_at
        dur = time.ticks_diff(at, self.state_at)
        self._cand = None

        # tugagan holatning vaqtini siklga yig'amiz
        if prev == AWAIT_PART:
            self._wait_ms += dur
        elif prev == PROCESSING:
            self._proc_ms += dur

        self.seq += 1
        ev = {
            "type": "state",
            "machine_id": self.cfg.MACHINE_ID,
            "site": self.cfg.SITE,
            "session": self.session,
            "seq": self.seq,
            "ts": ts,
            "state": new,
            "prev_state": prev,
            "prev_duration_s": dur // 1000,
            "lamps": dict(status),
            "part_id": self.part_id,
        }

        # ---- ochiq to'xtash yozuvini yopish ----
        # MUHIM: bu "yangi ochish" dan ALOHIDA tekshiriladi (elif emas).
        # STOPPED -> FAULT o'tishida ikkalasi ham bajarilishi kerak, aks holda
        # STOPPED yozuvi MES da abadiy ochiq qolib, hisobotdan tushib qoladi.
        if prev in REASON_STATES and self._dt_id:
            ev["closes_downtime_id"] = self._dt_id
            self._dt_id = None

        # ---- yangi to'xtash yozuvini ochish ----
        if new in REASON_STATES:
            self._dt_id = "{}-{}-{}".format(
                self.cfg.MACHINE_ID, self.session, self.seq)
            ev["downtime_id"] = self._dt_id
            ev["reason_required"] = True

        self.state = new
        self.state_at = at
        self.emit(ev)

        # ---- sikl yopiladimi? ----
        # FAULT - uzilish, sikl davom etadi (qizildan keyin ishlov davom etishi mumkin).
        # AWAIT_PART - yangi QR: agar ishlov bo'lgan bo'lsa, oldingi detal tugagan.
        if new == FAULT:
            pass
        elif new == PROCESSING:
            pass
        elif new == AWAIT_PART:
            if self._proc_ms:
                self._close_cycle(ts)
        elif self._proc_ms or self._wait_ms:
            self._close_cycle(ts)

        # ---- yangi detal raqamini skanerdan olish ----
        if self.scanner and self.part_id is None and new in (AWAIT_PART, PROCESSING):
            self.part_id = self.scanner.take(now, self.cfg.SCAN_MAX_AGE_MS)

    def _close_cycle(self, ts):
        # Detal faqat haqiqiy ishlov bo'lgandagina sanaladi. Bir necha yuz
        # millisekundlik "ishlov" - bu chiroq shovqini yoki miltillash
        # boshlanishi, detal emas.
        min_proc = getattr(self.cfg, "MIN_PROCESS_MS", 5000)
        completed = self._proc_ms >= min_proc
        if completed:
            self.part_count += 1
        self.seq += 1
        self.emit({
            "type": "cycle",
            "machine_id": self.cfg.MACHINE_ID,
            "site": self.cfg.SITE,
            "session": self.session,
            "seq": self.seq,
            "ts": ts,
            "part_id": self.part_id,
            "wait_s": self._wait_ms // 1000,      # QR skandan ishlov boshlanguncha
            "process_s": self._proc_ms // 1000,   # sof ishlov vaqti
            "completed": completed,               # False -> detal ishlovsiz olindi
            "part_count": self.part_count,        # boot'dan beri; MES qatorlarni o'zi sanaydi
        })
        self._wait_ms = 0
        self._proc_ms = 0
        self.part_id = None
