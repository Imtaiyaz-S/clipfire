"""Learning notebook.

APP_MODE=local     -> add / edit / delete enabled (run on your computer)
anything else      -> read-only (default, used on Render)
"""
import os
import re
from pathlib import Path

import markdown as md
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.exceptions import HTTPException as StarletteHTTPException

import store

BASE = Path(__file__).parent
EDITABLE = os.getenv("APP_MODE", "readonly").lower() == "local"

app = FastAPI(title="Learning notebook", docs_url="/docs" if EDITABLE else None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

templates = Jinja2Templates(directory=BASE / "templates")
templates.env.filters["markdown"] = lambda text: Markup(
    md.markdown(text or "", extensions=["fenced_code", "tables", "sane_lists"])
)
TRACKER = EDITABLE or os.getenv("TRACKER_PUBLIC") == "1"  # job tracker: local only unless opted in
templates.env.globals.update(editable=EDITABLE, type_labels=store.KINDS, tracker_enabled=TRACKER)


def render(request: Request, name: str, status_code: int = 200, **extra):
    context = {"groups": store.grouped_topics(), "topic_names": store.topic_names(), **extra}
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def require_local():
    if not EDITABLE:
        raise HTTPException(403, "This copy is read-only. Add and edit notes on your computer, then push.")


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return render(request, "error.html", status_code=exc.status_code, code=exc.status_code, message=exc.detail)


# ---- reading ----------------------------------------------------------------
@app.get("/")
def home(request: Request):
    return render(
        request, "index.html",
        recent=store.recent(8), total=store.count(), topic_count=len(store.topics()),
        group_names=[g for g, _ in store.grouped_topics()],
    )


@app.get("/topic/{slug}")
def topic_page(request: Request, slug: str, kind: str = ""):
    topic = store.get_topic(slug)
    if not topic:
        raise HTTPException(404, "That topic doesn't exist.")
    kind = kind if kind in store.KINDS else ""
    counts = store.kind_counts(slug)
    return render(
        request, "topic.html", topic=topic, current_topic=slug, kind=kind,
        entries=store.entries_for(slug, kind or None), counts=counts, total=sum(counts.values()),
    )


@app.get("/search")
def search(request: Request, q: str = ""):
    return render(request, "search.html", q=q, results=store.search(q), topic_results=store.search_topics(q))


@app.get("/companies")
def companies(request: Request):
    return render(request, "companies.html", companies=store.companies())


@app.get("/revise")
def revise(request: Request, topic: str = "", n: int = 10):
    t = store.get_topic(topic) if topic else None
    return render(
        request, "revise.html", topic=t, current_topic=topic,
        entries=store.sample(max(1, min(n, 50)), t["slug"] if t else None),
    )


# ---- writing (local only) ---------------------------------------------------
def _clean(topic, kind, title, body, url, company):
    title, body, url, company = title.strip(), body.strip(), url.strip(), company.strip()
    if kind not in store.KINDS:
        return None, "Pick note, link or interview question."
    if not store.get_topic(topic):
        return None, "Pick a topic."
    if not title:
        return None, "Add a title."
    if kind == "link":
        if not url:
            return None, "Add the link's URL."
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
    else:
        url = ""
    if kind != "question":
        company = ""
    return {"topic": topic, "kind": kind, "title": title, "body": body, "url": url, "company": company}, None


def _form(request, entry, values, error=None):
    return render(
        request, "form.html", status_code=400 if error else 200, entry=entry, f=values, error=error,
        current_topic=values.get("topic"), company_options=[c for c, _ in store.companies()],
    )


@app.get("/new", dependencies=[Depends(require_local)])
def new_form(request: Request, topic: str = "", kind: str = "note"):
    values = {"topic": topic, "kind": kind if kind in store.KINDS else "note",
              "title": "", "body": "", "url": "", "company": ""}
    return _form(request, None, values)


@app.post("/entries", dependencies=[Depends(require_local)])
def create_entry(request: Request, topic: str = Form(""), kind: str = Form("note"), title: str = Form(""),
                 body: str = Form(""), url: str = Form(""), company: str = Form("")):
    data, error = _clean(topic, kind, title, body, url, company)
    if error:
        return _form(request, None, dict(topic=topic, kind=kind, title=title, body=body, url=url, company=company), error)
    entry = store.add_entry(data)
    return RedirectResponse(f"/topic/{entry['topic']}#e-{entry['id']}", status_code=303)


@app.get("/entries/{entry_id}/edit", dependencies=[Depends(require_local)])
def edit_form(request: Request, entry_id: str):
    entry = store.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "That entry doesn't exist.")
    return _form(request, entry, entry)


@app.post("/entries/{entry_id}", dependencies=[Depends(require_local)])
def save_entry(request: Request, entry_id: str, topic: str = Form(""), kind: str = Form("note"),
               title: str = Form(""), body: str = Form(""), url: str = Form(""), company: str = Form("")):
    entry = store.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "That entry doesn't exist.")
    data, error = _clean(topic, kind, title, body, url, company)
    if error:
        return _form(request, entry, dict(topic=topic, kind=kind, title=title, body=body, url=url, company=company), error)
    store.update_entry(entry_id, data)
    return RedirectResponse(f"/topic/{data['topic']}#e-{entry_id}", status_code=303)


@app.post("/entries/{entry_id}/delete", dependencies=[Depends(require_local)])
def remove_entry(entry_id: str):
    entry = store.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "That entry doesn't exist.")
    store.delete_entry(entry_id)
    return RedirectResponse(f"/topic/{entry['topic']}", status_code=303)


def _topic_form(request, values, error=None):
    return render(
        request, "topic_new.html", status_code=400 if error else 200, error=error, f=values,
        group_options=[g for g, _ in store.grouped_topics()],
    )


@app.get("/topics/new", dependencies=[Depends(require_local)])
def new_topic_form(request: Request, group: str = ""):
    return _topic_form(request, {"name": "", "group": group})


@app.post("/topics", dependencies=[Depends(require_local)])
def create_topic(request: Request, name: str = Form(""), group: str = Form("")):
    topic, error = store.add_topic(name, group)
    if error:
        return _topic_form(request, {"name": name, "group": group}, error)
    return RedirectResponse(f"/topic/{topic['slug']}", status_code=303)


@app.post("/topics/{slug}/delete", dependencies=[Depends(require_local)])
def remove_topic(slug: str):
    error = store.delete_topic(slug)
    if error:
        raise HTTPException(400, error)
    return RedirectResponse("/", status_code=303)


if TRACKER:
    import jobs

    jobs.register(app, templates, render, require_local, store)
