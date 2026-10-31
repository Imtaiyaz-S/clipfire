"""Job tracker data. Separate file (data/jobs.json) so it stays out of git by default."""
import json
import os
import threading
import uuid
from datetime import date
from pathlib import Path

DATA_FILE = Path(os.getenv("JOBS_FILE") or Path(__file__).parent / "data" / "jobs.json")
HIRING = {"unknown": "Not checked", "yes": "Hiring", "no": "Not hiring"}
STATUSES = ["Saved", "Applied", "Interviewing", "Offer", "Rejected", "Withdrawn"]
REFERRAL = {"none": "Not asked", "asked": "Asked for a referral", "given": "Got a referral"}
OUTCOMES = ["Pending", "Passed", "Rejected"]
TONE = {  # chip colours
    "yes": "good", "no": "bad", "unknown": "neutral",
    "Offer": "good", "Interviewing": "active", "Applied": "info", "Saved": "neutral",
    "Rejected": "bad", "Withdrawn": "neutral", "Not applied": "neutral",
    "Pending": "info", "Passed": "good",
}
_RANK = {"Offer": 5, "Interviewing": 4, "Applied": 3, "Saved": 2, "Rejected": 1, "Withdrawn": 0}

_lock = threading.RLock()
_db = None


def today() -> str:
    return date.today().isoformat()


def days_ago(d: str) -> str:
    try:
        n = (date.today() - date.fromisoformat(d)).days
    except (TypeError, ValueError):
        return ""
    return "today" if n == 0 else "1 day ago" if n == 1 else f"{n} days ago"


def _id() -> str:
    return uuid.uuid4().hex[:8]


def _load() -> dict:
    global _db
    with _lock:
        if _db is None:
            _db = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {"companies": []}
        return _db


def _save() -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(_db, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, DATA_FILE)


# ---- companies --------------------------------------------------------------
def companies() -> list[dict]:
    return sorted(_load()["companies"], key=lambda c: (not c["dream"], c["name"].lower()))


def get_company(cid: str):
    return next((c for c in _load()["companies"] if c["id"] == cid), None)


def find_by_name(name: str):
    return next((c for c in _load()["companies"] if c["name"].lower() == name.strip().lower()), None)


def summary(c: dict) -> dict:
    apps = c["applications"]
    best = max((a["status"] for a in apps), key=lambda s: _RANK.get(s, 0), default=None)
    return {"apps": len(apps), "rounds": sum(len(a["rounds"]) for a in apps), "status": best or "Not applied"}


def add_company(data: dict) -> dict:
    with _lock:
        c = {"id": _id(), **data, "hiring_checked": today(), "applications": [], "created": today()}
        _load()["companies"].append(c)
        _save()
    return c


def update_company(cid: str, data: dict) -> None:
    with _lock:
        c = get_company(cid)
        if c["hiring"] != data["hiring"]:
            c["hiring_checked"] = today()
        c.update(data)
        _save()


def set_hiring(cid: str, value: str) -> None:
    with _lock:
        c = get_company(cid)
        c["hiring"], c["hiring_checked"] = value, today()
        _save()


def delete_company(cid: str) -> None:
    with _lock:
        _load()["companies"] = [c for c in _load()["companies"] if c["id"] != cid]
        _save()


# ---- applications -----------------------------------------------------------
def get_application(aid: str):
    for c in _load()["companies"]:
        for a in c["applications"]:
            if a["id"] == aid:
                return c, a
    return None, None


def add_application(cid: str, data: dict) -> dict:
    with _lock:
        a = {"id": _id(), **data, "rounds": []}
        get_company(cid)["applications"].append(a)
        _save()
    return a


def update_application(aid: str, data: dict) -> None:
    with _lock:
        get_application(aid)[1].update(data)
        _save()


def delete_application(aid: str) -> None:
    with _lock:
        c, _ = get_application(aid)
        c["applications"] = [a for a in c["applications"] if a["id"] != aid]
        _save()


# ---- rounds -----------------------------------------------------------------
def get_round(rid: str):
    for c in _load()["companies"]:
        for a in c["applications"]:
            for r in a["rounds"]:
                if r["id"] == rid:
                    return c, a, r
    return None, None, None


def add_round(aid: str, data: dict) -> dict:
    with _lock:
        _, a = get_application(aid)
        r = {"id": _id(), **data}
        a["rounds"].append(r)
        if a["status"] in ("Saved", "Applied"):
            a["status"] = "Interviewing"
        _save()
    return r


def update_round(rid: str, data: dict) -> None:
    with _lock:
        get_round(rid)[2].update(data)
        _save()


def delete_round(rid: str) -> None:
    with _lock:
        _, a, _ = get_round(rid)
        a["rounds"] = [r for r in a["rounds"] if r["id"] != rid]
        _save()
