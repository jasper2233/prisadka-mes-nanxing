"""Minimal MQTT 3.1.1 broker (prototip uchun).

Mosquitto o'rniga - hech narsa o'rnatmasdan ishlaydi. Qo'llab-quvvatlaydi:
QoS 0, retained xabarlar, LWT (Last Will), `+` va `#` wildcard, keepalive.

Ishlab chiqarishga emas, sinov va prototip uchun mo'ljallangan.
"""

import asyncio
import time

from . import mqtt_common as m


class Client:
    def __init__(self, broker, reader, writer):
        self.broker = broker
        self.reader = reader
        self.writer = writer
        self.cid = "?"
        self.subs = []
        self.will = None
        self.keepalive = 60
        self.alive_at = time.time()
        self.peer = writer.get_extra_info("peername")

    async def send(self, data):
        await m.drain(self.writer, data)

    def matches(self, topic):
        return any(m.topic_matches(f, topic) for f, _ in self.subs)


class Broker:
    def __init__(self, host="0.0.0.0", port=1883, log=print):
        self.host = host
        self.port = port
        self.log = log
        self.clients = set()
        self.retained = {}          # topic -> (payload, )
        self._local = []            # jarayon ichidagi obunachilar: (filter, cb)

    # ---------- jarayon ichidan eshitish (bridge uchun soket kerak emas) ----------
    def subscribe_local(self, topic_filter, callback):
        self._local.append((topic_filter, callback))
        for topic, payload in list(self.retained.items()):
            if m.topic_matches(topic_filter, topic):
                self._safe_local(callback, topic, payload, True)

    def _safe_local(self, cb, topic, payload, retained):
        try:
            cb(topic, payload, retained)
        except Exception as e:
            self.log("bridge xatosi: {}".format(e))

    # ---------- tarqatish ----------
    async def dispatch(self, topic, payload, retain):
        if retain:
            if payload:
                self.retained[topic] = payload
            else:
                self.retained.pop(topic, None)

        pkt = m.publish_packet(topic, payload)
        dead = []
        for c in self.clients:
            if c.matches(topic):
                try:
                    await c.send(pkt)
                except Exception:
                    dead.append(c)
        for c in dead:
            self.clients.discard(c)

        for f, cb in self._local:
            if m.topic_matches(f, topic):
                self._safe_local(cb, topic, payload, retain)

    def publish_nowait(self, topic, payload, retain=False):
        """Sinxron koddan (web handler) chaqirish uchun."""
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        asyncio.get_event_loop().create_task(
            self.dispatch(topic, payload, retain))

    # ---------- ulanish ----------
    async def handle(self, reader, writer):
        c = Client(self, reader, writer)
        try:
            ptype, flags, body = await m.read_packet(reader)
            if ptype != m.CONNECT:
                writer.close()
                return
            info = m.parse_connect(body)
            c.cid = info["client_id"] or "anon-{}".format(id(c) & 0xFFFF)
            c.keepalive = info["keepalive"] or 60
            c.will = info["will"]
            await c.send(m.packet(m.CONNACK, 0, bytes([0, 0])))
            self.clients.add(c)
            self.log("ulandi: {} ({})".format(c.cid, c.peer[0] if c.peer else "?"))

            while True:
                timeout = c.keepalive * 2 if c.keepalive else None
                ptype, flags, body = await asyncio.wait_for(
                    m.read_packet(reader), timeout=timeout)

                if ptype == m.PUBLISH:
                    topic, payload, retain, qos = m.parse_publish(flags, body)
                    await self.dispatch(topic, payload, retain)

                elif ptype == m.SUBSCRIBE:
                    pid, subs = m.parse_subscribe(body)
                    c.subs.extend(subs)
                    await c.send(m.packet(
                        m.SUBACK, 0,
                        pid.to_bytes(2, "big") + bytes([0] * len(subs))))
                    # obuna bo'lgan zahoti retained xabarlarni yuboramiz
                    for f, _ in subs:
                        for topic, payload in list(self.retained.items()):
                            if m.topic_matches(f, topic):
                                await c.send(m.publish_packet(
                                    topic, payload, retain=True))

                elif ptype == m.UNSUBSCRIBE:
                    pid = int.from_bytes(body[0:2], "big")
                    i = 2
                    drop = []
                    while i < len(body):
                        f, i = m.dec_str(body, i)
                        drop.append(f)
                    c.subs = [s for s in c.subs if s[0] not in drop]
                    await c.send(m.packet(m.UNSUBACK, 0, pid.to_bytes(2, "big")))

                elif ptype == m.PINGREQ:
                    await c.send(m.packet(m.PINGRESP, 0, b""))

                elif ptype == m.DISCONNECT:
                    c.will = None          # toza uzilish - LWT yuborilmaydi
                    break

        except (asyncio.IncompleteReadError, ConnectionError,
                asyncio.TimeoutError):
            pass
        except Exception as e:
            self.log("klient xatosi {}: {!r}".format(c.cid, e))
        finally:
            self.clients.discard(c)
            if c.will:
                self.log("LWT: {} -> {}".format(c.cid, c.will["topic"]))
                await self.dispatch(c.will["topic"], c.will["payload"],
                                    c.will["retain"])
            elif c.cid != "?":
                self.log("uzildi: {}".format(c.cid))
            try:
                writer.close()
            except Exception:
                pass

    async def serve(self):
        server = await asyncio.start_server(self.handle, self.host, self.port)
        self.log("MQTT broker: {}:{}".format(self.host, self.port))
        return server


async def main():
    b = Broker()
    s = await b.serve()
    async with s:
        await s.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nto'xtatildi")
