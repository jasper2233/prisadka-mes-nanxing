"""MQTT 3.1.1 paketlarini kodlash/dekodlash.

Broker ham, klient ham shu moduldan foydalanadi. Faqat prototip uchun kerak
bo'lgan qism: QoS 0, retained, LWT, wildcard obuna. Tashqi kutubxona yo'q.
"""

import asyncio

CONNECT = 1
CONNACK = 2
PUBLISH = 3
PUBACK = 4
SUBSCRIBE = 8
SUBACK = 9
UNSUBSCRIBE = 10
UNSUBACK = 11
PINGREQ = 12
PINGRESP = 13
DISCONNECT = 14


# ---------------------------------------------------------------- kodlash

def enc_len(n):
    """Remaining Length - o'zgaruvchan uzunlikdagi son."""
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            return bytes(out)


def enc_str(s):
    if isinstance(s, str):
        s = s.encode("utf-8")
    return len(s).to_bytes(2, "big") + s


def packet(ptype, flags, payload):
    return bytes([(ptype << 4) | flags]) + enc_len(len(payload)) + payload


def publish_packet(topic, payload, retain=False, qos=0, pid=None):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    flags = (1 if retain else 0) | (qos << 1)
    body = enc_str(topic)
    if qos:
        body += pid.to_bytes(2, "big")
    return packet(PUBLISH, flags, body + payload)


# ---------------------------------------------------------------- dekodlash

def dec_str(buf, i):
    n = int.from_bytes(buf[i:i + 2], "big")
    i += 2
    return buf[i:i + n].decode("utf-8", "replace"), i + n


async def read_packet(reader):
    """Bitta to'liq paketni o'qiydi. Ulanish uzilsa None qaytaradi."""
    head = await reader.readexactly(1)
    b0 = head[0]
    mult = 1
    length = 0
    while True:
        ch = (await reader.readexactly(1))[0]
        length += (ch & 0x7F) * mult
        if not ch & 0x80:
            break
        mult *= 128
        if mult > 128 ** 4:
            raise ValueError("remaining length juda uzun")
    body = await reader.readexactly(length) if length else b""
    return (b0 >> 4), (b0 & 0x0F), body


def parse_publish(flags, body):
    """-> (topic, payload, retain, qos)"""
    qos = (flags >> 1) & 0x03
    retain = bool(flags & 0x01)
    topic, i = dec_str(body, 0)
    if qos:
        i += 2                      # packet id - QoS 0 da ishlatilmaydi
    return topic, body[i:], retain, qos


def parse_connect(body):
    """-> dict(client_id, keepalive, will, clean, user, password)"""
    proto, i = dec_str(body, 0)
    level = body[i]
    i += 1
    flags = body[i]
    i += 1
    keepalive = int.from_bytes(body[i:i + 2], "big")
    i += 2
    client_id, i = dec_str(body, i)

    will = None
    if flags & 0x04:
        wt, i = dec_str(body, i)
        wlen = int.from_bytes(body[i:i + 2], "big")
        i += 2
        wp = body[i:i + wlen]
        i += wlen
        will = {"topic": wt, "payload": wp,
                "retain": bool(flags & 0x20), "qos": (flags >> 3) & 0x03}

    user = password = None
    if flags & 0x80:
        user, i = dec_str(body, i)
    if flags & 0x40:
        plen = int.from_bytes(body[i:i + 2], "big")
        i += 2
        password = body[i:i + plen]

    return {"proto": proto, "level": level, "client_id": client_id,
            "keepalive": keepalive, "will": will,
            "clean": bool(flags & 0x02), "user": user, "password": password}


def parse_subscribe(body):
    """-> (packet_id, [(filter, qos), ...])"""
    pid = int.from_bytes(body[0:2], "big")
    i = 2
    subs = []
    while i < len(body):
        f, i = dec_str(body, i)
        subs.append((f, body[i]))
        i += 1
    return pid, subs


# ---------------------------------------------------------------- topiklar

def topic_matches(filt, topic):
    """MQTT wildcard: `+` bitta bo'lak, `#` qolgan hammasi."""
    if filt == topic:
        return True
    f = filt.split("/")
    t = topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return i <= len(t)
        if i >= len(t):
            return False
        if part != "+" and part != t[i]:
            return False
    return len(f) == len(t)


async def drain(writer, data):
    """Yozib, buferi to'lgan ulanishda osilib qolmaslik uchun."""
    writer.write(data)
    try:
        await asyncio.wait_for(writer.drain(), timeout=5)
    except (asyncio.TimeoutError, ConnectionError):
        raise ConnectionError("yozib bo'lmadi")
