"""Tiny JSON-file store. One file (data/notes.json) holds topics and entries."""
from __future__ import annotations

import json
import os
import random
import re
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DATA_FILE = Path(os.getenv("DATA_FILE") or Path(__file__).parent / "data" / "notes.json")
KINDS = {"note": "Note", "link": "Link", "question": "Interview question"}

DEFAULT_TOPICS = {
    "AWS": [
        "AWS S3", "Bedrock", "EC2", "ECS", "AWS Batch", "Step Functions", "Lambda", "Glue",
        "SageMaker", "EMR", "VPC", "ECR", "EKS", "Managed Kafka (MSK)", "CloudWatch", "OpenSearch",
    ],
    "AI and agents": [
        "AI fundamentals", "LangGraph", "LangChain", "Strands", "AutoGen", "Azure AI", "Google ADK",
        "CrewAI", "RAG", "Vector databases", "ChromaDB", "Pinecone", "Milvus", "MCP",
        "Agentic AI", "NLP", "LSTM", "Transformers", "Azure AI Foundry",
    ],
    "Data and streaming": ["Databricks", "Snowflake", "Elasticsearch", "Kafka", "PySpark", "SQL", "Pandas"],
    "Python and web": ["Python", "Pydantic", "Django", "Flask", "FastAPI"],
    "Infrastructure": ["Terraform", "CloudFormation", "Docker"],
    "Engineering craft": ["Distributed systems", "Design patterns", "Consultant training"],
    "Interviews": ["General interview questions"],
}

_lock = threading.RLock()
_db: dict | None = None


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _seed() -> dict:
    topics = [
        {"slug": slugify(n), "name": n, "group": g}
        for g, names in DEFAULT_TOPICS.items()
        for n in names
    ]
    return {"topics": topics, "entries": []}


def _save() -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(_db, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, DATA_FILE)


def _load() -> dict:
    global _db
    with _lock:
        if _db is None:
            if DATA_FILE.exists():
                _db = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            else:
                _db = _seed()
                try:
                    _save()
                except OSError:
                    pass
        return _db


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ---- topics -----------------------------------------------------------------
def topics() -> list[dict]:
    return _load()["topics"]


def get_topic(slug: str) -> dict | None:
    return next((t for t in topics() if t["slug"] == slug), None)


def topic_names() -> dict[str, str]:
    return {t["slug"]: t["name"] for t in topics()}


def grouped_topics() -> list[tuple[str, list[dict]]]:
    counts = Counter(e["topic"] for e in _load()["entries"])
    groups: dict[str, list[dict]] = {}
    for t in topics():
        groups.setdefault(t["group"], []).append({**t, "count": counts.get(t["slug"], 0)})
    return list(groups.items())


def add_topic(name: str, group: str) -> tuple[dict | None, str | None]:
    name, group = name.strip(), group.strip() or "Other"
    slug = slugify(name)
    if not slug:
        return None, "Give the topic a name."
    with _lock:
        if get_topic(slug):
            return None, "That topic already exists."
        topic = {"slug": slug, "name": name, "group": group}
        _load()["topics"].append(topic)
        _save()
    return topic, None


def delete_topic(slug: str) -> str | None:
    with _lock:
        if any(e["topic"] == slug for e in _load()["entries"]):
            return "Delete or move this topic's entries first."
        _load()["topics"] = [t for t in topics() if t["slug"] != slug]
        _save()
    return None


# ---- entries ----------------------------------------------------------------
def _newest_first(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda e: e["created"], reverse=True)


def entries_for(slug: str, kind: str | None = None) -> list[dict]:
    items = [e for e in _load()["entries"] if e["topic"] == slug and (not kind or e["kind"] == kind)]
    return _newest_first(items)


def kind_counts(slug: str) -> Counter:
    return Counter(e["kind"] for e in _load()["entries"] if e["topic"] == slug)


def get_entry(entry_id: str) -> dict | None:
    return next((e for e in _load()["entries"] if e["id"] == entry_id), None)


def add_entry(data: dict) -> dict:
    with _lock:
        entry = {"id": uuid.uuid4().hex[:8], **data, "created": _now(), "updated": _now()}
        _load()["entries"].append(entry)
        _save()
    return entry


def update_entry(entry_id: str, data: dict) -> dict | None:
    with _lock:
        entry = get_entry(entry_id)
        if not entry:
            return None
        entry.update(data, updated=_now())
        _save()
    return entry


def delete_entry(entry_id: str) -> None:
    with _lock:
        _load()["entries"] = [e for e in _load()["entries"] if e["id"] != entry_id]
        _save()


def count() -> int:
    return len(_load()["entries"])


def recent(n: int = 8) -> list[dict]:
    return _newest_first(_load()["entries"])[:n]


def search(q: str) -> list[dict]:
    terms = q.lower().split()
    if not terms:
        return []
    names = topic_names()
    hits = []
    for e in _load()["entries"]:
        hay = " ".join(
            [e["title"], e.get("body", ""), e.get("company", ""), e.get("url", ""), names.get(e["topic"], "")]
        ).lower()
        if all(t in hay for t in terms):
            hits.append(e)
    return _newest_first(hits)


def search_topics(q: str) -> list[dict]:
    terms = q.lower().split()
    if not terms:
        return []
    return [t for t in topics() if all(x in f"{t['name']} {t['group']}".lower() for x in terms)]


def companies() -> list[tuple[str, list[dict]]]:
    grouped: dict[str, tuple[str, list[dict]]] = {}
    for e in _newest_first(_load()["entries"]):
        c = e.get("company", "").strip()
        if e["kind"] == "question" and c:
            grouped.setdefault(c.lower(), (c, []))[1].append(e)
    return sorted(grouped.values(), key=lambda x: x[0].lower())


def sample(n: int, slug: str | None = None) -> list[dict]:
    pool = [
        e for e in _load()["entries"]
        if e["kind"] in ("note", "question") and (not slug or e["topic"] == slug)
    ]
    return random.sample(pool, min(n, len(pool)))
