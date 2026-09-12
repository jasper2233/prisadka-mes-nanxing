"""Minimal sinxron MQTT klient (QoS 0).

Pico dagi `umqtt.simple` bilan bir xil uslubda ishlaydi: `check()` bloklamaydi,
`publish()` darhol yuboradi. Simulyator va buyruq utilitalari shuni ishlatadi.
"""

import socket
import time

from . import mqtt_common as m


class Client:
    def __init__(self, host="127.0.0.1", port=1883, client_id="py-client",
                 keepalive=60, will=None, on_message=None):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.keepalive = keepalive
        self.will = will                    # (topic, payload, retain)
        self.on_message = on_message
        self.sock = None
        self.buf = bytearray()
        self._next_ping = 0
        self._pid = 1

    # ---------------------------------------------------------- ulanish
    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=5)
        flags = 0x02                        # clean session
        payload = m.enc_str(self.client_id)
        if self.will:
            topic, msg, retain = self.will
            flags |= 0x04 | (0x20 if retain else 0)
            if isinstance(msg, str):
                msg = msg.encode()
            payload += m.enc_str(topic) + len(msg).to_bytes(2, "big") + msg
        var = (m.enc_str("MQTT") + bytes([4, flags]) +
               self.keepalive.to_bytes(2, "big"))
        self.sock.sendall(m.packet(m.CONNECT, 0, var + payload))

        self.sock.settimeout(5)
        ptype, _, body = self._read_blocking()
        if ptype != m.CONNACK or body[1] != 0:
            raise ConnectionError("broker CONNECT ni rad etdi: {}".format(body))
        self.sock.setblocking(False)
        self._next_ping = time.time() + self.keepalive / 2
        return self

    def _read_blocking(self):
        """Faqat CONNACK uchun - qolgani check() orqali."""
        head = self._recv_exact(1)
        b0 = head[0]
        mult, length = 1, 0
        while True:
            ch = self._recv_exact(1)[0]
            length += (ch & 0x7F) * mult
            if not ch & 0x80:
                break
            mult *= 128
        return (b0 >> 4), (b0 & 0x0F), self._recv_exact(length) if length else b""

    def _recv_exact(self, n):
        out = b""
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError("ulanish uzildi")
            out += chunk
        return out

    def close(self):
        if self.sock:
            try:
                self.sock.setblocking(True)
                self.sock.sendall(m.packet(m.DISCONNECT, 0, b""))
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    # ---------------------------------------------------------- yuborish
    def _send(self, data):
        if not self.sock:
            raise ConnectionError("ulanmagan")
        self.sock.setblocking(True)
        try:
            self.sock.sendall(data)
        finally:
            try:
                self.sock.setblocking(False)
            except Exception:
                pass

    def publish(self, topic, payload, retain=False):
        self._send(m.publish_packet(topic, payload, retain=retain))

    def subscribe(self, topic):
        pid = self._pid
        self._pid += 1
        body = pid.to_bytes(2, "big") + m.enc_str(topic) + bytes([0])
        self._send(m.packet(m.SUBSCRIBE, 0x02, body))

    # ---------------------------------------------------------- qabul qilish
    def check(self):
        """Bloklamaydi. Kelgan xabarlarni on_message ga uzatadi."""
        if not self.sock:
            return
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ConnectionError("broker ulanishni yopdi")
                self.buf += chunk
        except BlockingIOError:
            pass
        except (socket.timeout, OSError) as e:
            if isinstance(e, ConnectionError):
                raise
        self._parse()

        if time.time() >= self._next_ping:
            self._send(m.packet(m.PINGREQ, 0, b""))
            self._next_ping = time.time() + self.keepalive / 2

    def _parse(self):
        while True:
            if len(self.buf) < 2:
                return
            mult, val, i = 1, 0, 1
            while True:
                if i >= len(self.buf):
                    return                  # paket to'liq kelmagan
                ch = self.buf[i]
                val += (ch & 0x7F) * mult
                i += 1
                if not ch & 0x80:
                    break
                mult *= 128
            total = i + val
            if len(self.buf) < total:
                return
            b0 = self.buf[0]
            body = bytes(self.buf[i:total])
            del self.buf[:total]
            if (b0 >> 4) == m.PUBLISH and self.on_message:
                topic, payload, retain, _ = m.parse_publish(b0 & 0x0F, body)
                self.on_message(topic, payload, retain)
