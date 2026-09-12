# Wi-Fi + MQTT: bloklamaydigan qayta ulanish va oflayn navbat.
#
# Asosiy qoida: pump() asosiy tsikldan har ~2 ms da chaqiriladi va hech qachon
# bir necha soniyadan uzoq bloklamasligi kerak - aks holda chiroqlar o'qilmay
# qoladi va 8 s watchdog qurilmani qayta yuklaydi.

import network
import time
import json

try:
    from umqtt import simple as _mqtt
except ImportError:
    raise ImportError("umqtt.simple yo'q. Thonny'da: import mip; mip.install('umqtt.simple')")

MQTTClient = _mqtt.MQTTClient

# MicroPython epoxi 2000-01-01, CPython'da 1970-01-01
UNIX_OFFSET = 946684800 if time.gmtime(0)[0] == 2000 else 0
# NTP vaqti 1900 dan hisoblanadi -> qurilma epoxiga o'tkazish farqi
NTP_DELTA = 2208988800 + UNIX_OFFSET


class _TimedSocket:
    """umqtt.simple ichidagi `socket` modulining o'rnini bosadi.

    umqtt soketni o'zi yaratadi va unga timeout qo'ymaydi. Broker IP javob
    bermasa, connect() dagi TCP kutish yoki CONNACK/SUBACK o'qish o'n
    soniyalab bloklaydi -> watchdog reset tsikli. Shim har bir yangi soketga
    timeout qo'yadi.

    Vaqt hisobi: connect() da uchta bloklovchi bosqich bor (TCP + CONNACK +
    SUBACK), shuning uchun timeout 8 s / 3 dan kichik bo'lishi shart.
    """

    def __init__(self, mod, timeout_s):
        self._m = mod
        self._t = timeout_s

    def __getattr__(self, name):
        return getattr(self._m, name)

    def socket(self, *a, **kw):
        s = self._m.socket(*a, **kw)
        s.settimeout(self._t)
        return s


def _patch_mqtt_socket(timeout_s):
    try:
        if not isinstance(_mqtt.socket, _TimedSocket):
            _mqtt.socket = _TimedSocket(_mqtt.socket, timeout_s)
    except Exception as e:
        print("soket timeout qo'yilmadi:", e)


def _is_ip(host):
    """DNS nomi emasligini tekshiradi. Nom berilsa getaddrinfo bloklaydi."""
    parts = str(host).split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p or not p.isdigit() or int(p) > 255:
            return False
    return True


class Link:
    def __init__(self, cfg, feed=None, on_cmd=None):
        self.cfg = cfg
        self.feed = feed or (lambda: None)   # WDT.feed - uzoq kutishlarda chaqiriladi
        self.on_cmd = on_cmd                 # MES dan kelgan buyruq
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        self.mq = None
        self.buf = []
        self.dropped = 0
        self.time_ok = False
        self._next_try = 0
        self._backoff = cfg.RECONNECT_MIN_MS
        self._next_ntp = 0
        self._next_ping = 0
        self._wifi_at = None
        self._sock_timeout = getattr(cfg, "MQTT_SOCKET_TIMEOUT_S", 2)
        self._ping_ms = max(5000, cfg.MQTT_KEEPALIVE * 1000 // 3)
        _patch_mqtt_socket(self._sock_timeout)

        mid = cfg.MACHINE_ID
        self.t_event = cfg.TOPIC_EVENT.format(mid)
        self.t_state = cfg.TOPIC_STATE.format(mid)
        self.t_online = cfg.TOPIC_ONLINE.format(mid)
        self.t_cmd = cfg.TOPIC_CMD.format(mid)
        self._next_rx = 0

    # ---------- MES dan kelgan buyruq ----------
    def _on_msg(self, topic, msg):
        if self.on_cmd is None:
            return
        try:
            data = json.loads(msg)
        except Exception:
            return
        if isinstance(data, dict):
            try:
                self.on_cmd(data)
            except Exception as e:
                print("cmd xatosi:", e)

    # ---------- holat ----------
    @property
    def online(self):
        return self.mq is not None

    def rssi(self):
        try:
            return self.wlan.status("rssi") if self.wlan.isconnected() else None
        except Exception:
            return None

    def now_ts(self):
        """Unix epoch soniya. NTP hali sinxronlanmagan bo'lsa 0 qaytaradi
        (server o'zi vaqt qo'yishi uchun)."""
        return time.time() + UNIX_OFFSET if self.time_ok else 0

    # ---------- yuborish ----------
    def enqueue(self, topic, payload, retain=False):
        msg = json.dumps(payload)
        if retain:
            # Retained snapshot - faqat oxirgisi kerak. Oflayn paytda ularni
            # yig'ib borish RAM ni yeydi (har 30 s da bittadan) va haqiqiy
            # eventlarni buferdan siqib chiqaradi. Shuning uchun almashtiramiz.
            for i in range(len(self.buf)):
                if self.buf[i][2] and self.buf[i][0] == topic:
                    self.buf[i] = (topic, msg, True)
                    return
        if len(self.buf) >= self.cfg.BUFFER_MAX:
            self.buf.pop(0)          # eng eskisini tashlaymiz
            self.dropped += 1
        self.buf.append((topic, msg, retain))

    def _flush(self):
        while self.buf:
            topic, msg, retain = self.buf[0]
            try:
                self.mq.publish(topic, msg, retain=retain, qos=0)
            except Exception:
                self._drop_mqtt()
                return False
            self.buf.pop(0)
            self.feed()
        return True

    # ---------- ulanish ----------
    def _wifi_ready(self, now):
        """Bloklamaydi. True - Wi-Fi tayyor, False - hali ulanmoqda.

        Eski versiya bu yerda 15 s kutar edi; o'sha paytda chiroqlar o'qilmay,
        holat o'zgarishlari yo'qolar edi.
        """
        if self.wlan.isconnected():
            self._wifi_at = None
            return True
        limit = self.cfg.WIFI_TIMEOUT_S * 1000
        if self._wifi_at is None or time.ticks_diff(now, self._wifi_at) > limit:
            try:
                self.wlan.connect(self.cfg.WIFI_SSID, self.cfg.WIFI_PASS)
            except Exception:
                pass
            self._wifi_at = now
        return False

    def _connect_mqtt(self):
        cid = self.cfg.MACHINE_ID.encode()
        c = MQTTClient(cid, self.cfg.MQTT_HOST, port=self.cfg.MQTT_PORT,
                       user=self.cfg.MQTT_USER, password=self.cfg.MQTT_PASS,
                       keepalive=self.cfg.MQTT_KEEPALIVE)
        c.set_callback(self._on_msg)
        c.set_last_will(self.t_online, b"0", retain=True, qos=0)
        try:
            c.connect()
            c.subscribe(self.t_cmd, qos=0)
            c.publish(self.t_online, b"1", retain=True, qos=0)
        except Exception:
            # Yarim ochilgan soketni yopamiz. Aks holda har muvaffaqiyatsiz
            # urinishda bittadan soket oqib ketadi va resurs tugaydi.
            try:
                c.sock.close()
            except Exception:
                pass
            raise
        self.mq = c
        self._next_ping = time.ticks_add(time.ticks_ms(), self._ping_ms)

    def _drop_mqtt(self):
        c = self.mq
        self.mq = None
        if c is not None:
            try:
                c.disconnect()
            except Exception:
                pass
            try:
                c.sock.close()      # disconnect() xato bersa soket ochiq qolardi
            except Exception:
                pass
        self._next_try = time.ticks_add(time.ticks_ms(), self._backoff)
        self._backoff = min(self._backoff * 2, self.cfg.RECONNECT_MAX_MS)

    # ---------- NTP ----------
    def _ntp_query(self, host):
        """Soddalashtirilgan NTP so'rovi, aniq timeout bilan.

        `ntptime` moduli ishlatilmaydi: ba'zi buildlarda soketga timeout
        qo'ymaydi va javob kelmasa cheksiz bloklaydi.
        """
        import socket
        import struct
        addr = socket.getaddrinfo(host, 123)[0][-1]
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(self._sock_timeout)
            pkt = bytearray(48)
            pkt[0] = 0x1B                     # LI=0, VN=3, Mode=3 (client)
            s.sendto(pkt, addr)
            msg = s.recv(48)
        finally:
            s.close()
        secs = struct.unpack("!I", msg[40:44])[0]
        return secs - NTP_DELTA

    def _sync_time(self, now):
        host = self.cfg.NTP_HOST
        # DNS ISHLATILMAYDI: nom berilsa getaddrinfo soketni bloklab,
        # watchdog reset'ga olib keladi. NTP_HOST faqat IP bo'lishi kerak.
        if not _is_ip(host):
            print("NTP o'tkazildi: NTP_HOST IP bo'lsin, DNS nomi emas ->", host)
            self._next_ntp = time.ticks_add(now, 3600000)
            return
        ok = False
        self.feed()
        try:
            t = self._ntp_query(host)
            import machine
            tm = time.gmtime(t)
            machine.RTC().datetime(
                (tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
            self.time_ok = True
            ok = True
        except Exception as e:
            print("NTP xatosi:", e)
        self.feed()
        # Muvaffaqiyatsiz bo'lsa har tsiklda emas, 60 s dan keyin qayta urinamiz.
        self._next_ntp = time.ticks_add(
            now, self.cfg.NTP_RESYNC_S * 1000 if ok else 60000)

    # ---------- asosiy tsikl chaqiruvi ----------
    def pump(self):
        now = time.ticks_ms()

        if self.mq is None:
            if time.ticks_diff(now, self._next_try) < 0:
                return
            if not self._wifi_ready(now):
                self._next_try = time.ticks_add(now, 500)   # bloklamasdan kutamiz
                return
            try:
                self._connect_mqtt()
            except Exception:
                self._drop_mqtt()
                return
            self._backoff = self.cfg.RECONNECT_MIN_MS
            self._flush()
            return

        if not self.wlan.isconnected():
            self._drop_mqtt()
            return

        if time.ticks_diff(now, self._next_ping) >= 0:
            try:
                self.mq.ping()
            except Exception:
                self._drop_mqtt()
                return
            self._next_ping = time.ticks_add(now, self._ping_ms)

        # kiruvchi buyruqlar (bloklamaydi)
        if time.ticks_diff(now, self._next_rx) >= 0:
            self._next_rx = time.ticks_add(now, 100)
            try:
                self.mq.check_msg()
            except OSError as e:
                if not (e.args and e.args[0] in (11, 110)):   # EAGAIN / ETIMEDOUT
                    self._drop_mqtt()
                    return
            except Exception:
                self._drop_mqtt()
                return
            try:
                # check_msg() soketni non-blocking qoldiradi - qaytarish shart.
                # setblocking(True) o'rniga timeout: bloklovchi rejim tiklanadi,
                # lekin osib qolgan soket endi watchdog reset'ga olib kelmaydi.
                self.mq.sock.settimeout(self._sock_timeout)
            except Exception:
                pass

        if self.buf:
            self._flush()

        if time.ticks_diff(now, self._next_ntp) >= 0:
            self._sync_time(now)
