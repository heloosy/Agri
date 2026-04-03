"""
AgriSpark 2.0 — Session Manager
Stores per-call (IVR) and per-phone (WhatsApp) state in memory.
In production, swap _store for Redis.
"""

_store: dict = {}   # key → session dict


# ─── Generic helpers ──────────────────────────────────────────────────────────

def get(key: str) -> dict:
    return _store.get(key, {})


def set(key: str, data: dict) -> None:
    _store[key] = data


def update(key: str, **kwargs) -> dict:
    session = _store.get(key, {})
    session.update(kwargs)
    _store[key] = session
    return session


def delete(key: str) -> None:
    _store.pop(key, None)


# ─── IVR helpers ─────────────────────────────────────────────────────────────

def get_lang(call_sid: str) -> str:
    """Return stored language for call ('EN' or 'TH'), default EN."""
    return _store.get(call_sid, {}).get("lang", "EN")


def get_mode(call_sid: str) -> str:
    return _store.get(call_sid, {}).get("mode", "quick")


def get_step(call_sid: str) -> int:
    return _store.get(call_sid, {}).get("step", 1)


def increment_step(call_sid: str) -> int:
    session = _store.get(call_sid, {})
    session["step"] = session.get("step", 1) + 1
    _store[call_sid] = session
    return session["step"]


# ─── WhatsApp helpers ─────────────────────────────────────────────────────────

def append_wa_history(phone: str, role: str, text: str, max_turns: int = 10) -> None:
    """Append a message to WhatsApp conversation history."""
    session = _store.get(phone, {})
    history = session.get("history", [])
    history.append({"role": role, "text": text})
    # Keep last max_turns * 2 messages (each turn = user + model)
    history = history[-(max_turns * 2):]
    session["history"] = history
    _store[phone] = session


def get_wa_history(phone: str) -> list:
    return _store.get(phone, {}).get("history", [])
