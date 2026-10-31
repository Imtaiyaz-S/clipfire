"""Job tracker routes. Registered by main.py only when the tracker is enabled."""
import re
from datetime import date

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

import jobs_store as js


def _url(v):
    v = (v or "").strip()
    return "https://" + v if v and not re.match(r"^https?://", v, re.I) else v


def _date(v):
    v = (v or "").strip()
    if v:
        try:
            date.fromisoformat(v)
        except ValueError:
            return None
    return v


def _pick(v, allowed, default):
    return v if v in allowed else default


def _clean_company(form):
    name = (form.get("name") or "").strip()
    if not name:
        return None, "Add the company name."
    return {
        "name": name,
        "website": _url(form.get("website")),
        "careers_url": _url(form.get("careers_url")),
        "linkedin": _url(form.get("linkedin")),
        "other_links": (form.get("other_links") or "").strip(),
        "notes": (form.get("notes") or "").strip(),
        "hiring": _pick(form.get("hiring"), js.HIRING, "unknown"),
        "dream": bool(form.get("dream")),
    }, None


def _clean_application(form):
    title = (form.get("title") or "").strip()
    if not title:
        return None, "Add the job title."
    applied, reply_date = _date(form.get("applied_on")), _date(form.get("reply_date"))
    if applied is None or reply_date is None:
        return None, "Dates must look like 2026-11-04."
    return {
        "title": title,
        "job_url": _url(form.get("job_url")),
        "applied_on": applied,
        "status": _pick(form.get("status"), js.STATUSES, "Applied"),
        "referral": _pick(form.get("referral"), js.REFERRAL, "none"),
        "referral_contact": (form.get("referral_contact") or "").strip(),
        "reply_received": bool(form.get("reply_received")),
        "reply_date": reply_date,
        "reply_notes": (form.get("reply_notes") or "").strip(),
        "notes": (form.get("notes") or "").strip(),
    }, None


def _clean_round(form, default_name):
    date_, follow = _date(form.get("date")), _date(form.get("follow_up_date"))
    if date_ is None or follow is None:
        return None, "Dates must look like 2026-11-04."
    return {
        "name": (form.get("name") or "").strip() or default_name,
        "date": date_,
        "interviewer": (form.get("interviewer") or "").strip(),
        "outcome": _pick(form.get("outcome"), js.OUTCOMES, "Pending"),
        "questions": (form.get("questions") or "").strip(),
        "follow_up_date": follow,
        "follow_up_update": (form.get("follow_up_update") or "").strip(),
        "notes": (form.get("notes") or "").strip(),
    }, None


def register(app, templates, render, require_local, store):
    templates.env.globals.update(
        hiring_labels=js.HIRING, statuses=js.STATUSES, referral_labels=js.REFERRAL,
        outcomes=js.OUTCOMES, tone=js.TONE, days_ago=js.days_ago, today=js.today,
    )
    local = [Depends(require_local)]

    def go(url):
        return RedirectResponse(url, status_code=303)

    def company_or_404(cid):
        c = js.get_company(cid)
        if not c:
            raise HTTPException(404, "That company isn't in your list.")
        return c

    def application_or_404(aid):
        c, a = js.get_application(aid)
        if not a:
            raise HTTPException(404, "That application doesn't exist.")
        return c, a

    def round_or_404(rid):
        c, a, r = js.get_round(rid)
        if not r:
            raise HTTPException(404, "That round doesn't exist.")
        return c, a, r

    # ---- dashboard -----------------------------------------------------------
    @app.get("/jobs")
    def dashboard(request: Request, f: str = ""):
        rows = [{**c, "info": js.summary(c)} for c in js.companies()]
        tabs = [
            ("", "All", lambda r: True),
            ("dream", "Dream", lambda r: r["dream"]),
            ("hiring", "Hiring now", lambda r: r["hiring"] == "yes"),
            ("todo", "Not applied yet", lambda r: r["info"]["apps"] == 0),
            ("process", "In process", lambda r: r["info"]["status"] in ("Interviewing", "Offer")),
        ]
        test = next((t[2] for t in tabs if t[0] == f), tabs[0][2])
        return render(
            request, "jobs.html", f=f, rows=[r for r in rows if test(r)],
            tabs=[(k, label, sum(1 for r in rows if fn(r))) for k, label, fn in tabs],
            applications=sum(r["info"]["apps"] for r in rows),
        )

    # ---- companies -----------------------------------------------------------
    def company_form(request, company, values, error=None):
        return render(request, "company_form.html", status_code=400 if error else 200,
                      company=company, f=values, error=error)

    @app.get("/jobs/companies/new", dependencies=local)
    def new_company(request: Request):
        return company_form(request, None, {"hiring": "unknown", "dream": False})

    @app.post("/jobs/companies", dependencies=local)
    async def create_company(request: Request):
        form = await request.form()
        data, error = _clean_company(form)
        if error:
            return company_form(request, None, dict(form), error)
        existing = js.find_by_name(data["name"])
        if existing:
            return go(f"/jobs/companies/{existing['id']}?notice=exists")
        c = js.add_company(data)
        return go(f"/jobs#c-{c['id']}")

    @app.get("/jobs/companies/{cid}")
    def company_page(request: Request, cid: str, notice: str = ""):
        c = company_or_404(cid)
        questions = [e for name, items in store.companies() if name.lower() == c["name"].lower() for e in items]
        return render(request, "company.html", c=c, notice=notice, questions=questions,
                      apps=[{**a, "stage": len(a["rounds"])} for a in c["applications"]])

    @app.get("/jobs/companies/{cid}/edit", dependencies=local)
    def edit_company(request: Request, cid: str):
        c = company_or_404(cid)
        return company_form(request, c, c)

    @app.post("/jobs/companies/{cid}", dependencies=local)
    async def save_company(request: Request, cid: str):
        c = company_or_404(cid)
        form = await request.form()
        data, error = _clean_company(form)
        if error:
            return company_form(request, c, dict(form), error)
        js.update_company(cid, data)
        return go(f"/jobs/companies/{cid}")

    @app.post("/jobs/companies/{cid}/hiring", dependencies=local)
    async def hiring(request: Request, cid: str):
        company_or_404(cid)
        form = await request.form()
        js.set_hiring(cid, _pick(form.get("hiring"), js.HIRING, "unknown"))
        return go(f"/jobs/companies/{cid}")

    @app.post("/jobs/companies/{cid}/delete", dependencies=local)
    def remove_company(cid: str):
        company_or_404(cid)
        js.delete_company(cid)
        return go("/jobs")

    # ---- applications ----------------------------------------------------------
    def application_form(request, company, application, values, error=None):
        return render(request, "application_form.html", status_code=400 if error else 200,
                      c=company, application=application, f=values, error=error)

    @app.get("/jobs/applications/new", dependencies=local)
    def new_application(request: Request, company: str = ""):
        c = company_or_404(company)
        return application_form(request, c, None, {"status": "Applied", "referral": "none", "applied_on": js.today()})

    @app.post("/jobs/applications", dependencies=local)
    async def create_application(request: Request):
        form = await request.form()
        c = company_or_404(form.get("company_id", ""))
        data, error = _clean_application(form)
        if error:
            return application_form(request, c, None, dict(form), error)
        a = js.add_application(c["id"], data)
        return go(f"/jobs/applications/{a['id']}")

    @app.get("/jobs/applications/{aid}")
    def application_page(request: Request, aid: str):
        c, a = application_or_404(aid)
        return render(request, "application.html", c=c, a=a)

    @app.get("/jobs/applications/{aid}/edit", dependencies=local)
    def edit_application(request: Request, aid: str):
        c, a = application_or_404(aid)
        return application_form(request, c, a, a)

    @app.post("/jobs/applications/{aid}", dependencies=local)
    async def save_application(request: Request, aid: str):
        c, a = application_or_404(aid)
        form = await request.form()
        data, error = _clean_application(form)
        if error:
            return application_form(request, c, a, dict(form), error)
        js.update_application(aid, data)
        return go(f"/jobs/applications/{aid}")

    @app.post("/jobs/applications/{aid}/delete", dependencies=local)
    def remove_application(aid: str):
        c, _ = application_or_404(aid)
        js.delete_application(aid)
        return go(f"/jobs/companies/{c['id']}")

    # ---- interview rounds --------------------------------------------------------
    def round_form(request, c, a, r, values, error=None):
        return render(request, "round_form.html", status_code=400 if error else 200,
                      c=c, a=a, r=r, f=values, error=error)

    @app.get("/jobs/rounds/new", dependencies=local)
    def new_round(request: Request, application: str = ""):
        c, a = application_or_404(application)
        return round_form(request, c, a, None, {"name": f"Round {len(a['rounds']) + 1}", "outcome": "Pending"})

    @app.post("/jobs/rounds", dependencies=local)
    async def create_round(request: Request):
        form = await request.form()
        c, a = application_or_404(form.get("application_id", ""))
        data, error = _clean_round(form, f"Round {len(a['rounds']) + 1}")
        if error:
            return round_form(request, c, a, None, dict(form), error)
        r = js.add_round(a["id"], data)
        return go(f"/jobs/applications/{a['id']}#r-{r['id']}")

    @app.get("/jobs/rounds/{rid}/edit", dependencies=local)
    def edit_round(request: Request, rid: str):
        c, a, r = round_or_404(rid)
        return round_form(request, c, a, r, r)

    @app.post("/jobs/rounds/{rid}", dependencies=local)
    async def save_round(request: Request, rid: str):
        c, a, r = round_or_404(rid)
        form = await request.form()
        data, error = _clean_round(form, r["name"])
        if error:
            return round_form(request, c, a, r, dict(form), error)
        js.update_round(rid, data)
        return go(f"/jobs/applications/{a['id']}#r-{rid}")

    @app.post("/jobs/rounds/{rid}/delete", dependencies=local)
    def remove_round(rid: str):
        _, a, _ = round_or_404(rid)
        js.delete_round(rid)
        return go(f"/jobs/applications/{a['id']}")
