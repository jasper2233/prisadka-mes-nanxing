# MQTT orqali o'zgartiriladigan va flash'da saqlanadigan sozlamalar.
# Faqat o'zgarganda yoziladi (flash resursini tejash uchun).

import json

PATH = "settings.json"


def load(cfg):
    s = {
        "idle_timeout_s": cfg.IDLE_TIMEOUT_S,
        "idle_timeout_enabled": cfg.IDLE_TIMEOUT_ENABLED,
    }
    try:
        with open(PATH) as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for k in s:
                if k in saved:
                    s[k] = saved[k]
    except Exception:
        pass
    return s


def save(s):
    try:
        with open(PATH, "w") as f:
            json.dump(s, f)
        return True
    except Exception:
        return False


def apply_cmd(s, data):
    """MES dan kelgan buyruqni tekshirib qo'llaydi. O'zgarish bo'lsa True."""
    changed = False

    if "idle_timeout_s" in data:
        try:
            v = int(data["idle_timeout_s"])
        except Exception:
            v = None
        # 30 soniya - 24 soat oralig'i
        if v is not None and 30 <= v <= 86400 and v != s["idle_timeout_s"]:
            s["idle_timeout_s"] = v
            changed = True

    if "idle_timeout_enabled" in data:
        v = bool(data["idle_timeout_enabled"])
        if v != s["idle_timeout_enabled"]:
            s["idle_timeout_enabled"] = v
            changed = True

    return changed
