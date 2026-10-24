"""Adopt automatically when safe, undo, questions, expiry, summary, fair outdated check, freshness + corrections."""
import asyncio, datetime as dt, json, os, re, subprocess, sys, time, urllib.request, urllib.error
from playwright.async_api import async_playwright

PY, PORT = sys.argv[1], sys.argv[2]
H = os.environ["HOME"]; M = H + "/somna"; BASE = "http://127.0.0.1:" + PORT
SHOTS = os.environ.get("SHOTS", "/tmp")
FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "   -> " + str(extra)[:500]))
    if not cond:
        FAILS.append(name)


def req(path, body=None, token=None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(BASE + path, data=data, method="POST" if data is not None else "GET")
    if token: r.add_header("X-Somna-Token", token)
    if data is not None: r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read()
            return resp.status, (raw.decode() if path == "/" else json.loads(raw or b"{}"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TOKEN = re.search(r'const TOKEN = "([^"]+)"', req("/")[1]).group(1)
J = lambda path, body=None: req(path, body, TOKEN)


def cycle(*a, env=None):
    return subprocess.run([PY, M + "/bin/somna", *a], capture_output=True, text=True, env=dict(os.environ, **(env or {})))


def last():
    out = [json.load(open(os.path.join(M, "cycles", d, "cycle.json"))) for d in os.listdir(M + "/cycles") if d.startswith("cyc_")]
    return sorted(out, key=lambda r: (r["created_at"], r.get("created_ns", 0)))[-1]


WEB = os.path.realpath(H + "/code/acme-shop"); GLOBEX = os.path.realpath(H + "/code/globex-infra")
pdir = H + "/.claude/projects/" + re.sub(r"[^a-zA-Z0-9]", "-", WEB)
CTX = M + "/memory/clients/acme/repos/shop.md"
J("/api/client", {"id": "acme", "name": "Acme Corp", "markers": ["acme"]})
J("/api/client", {"id": "globex", "name": "Globex", "markers": ["globex"]})
J("/api/assign", {"path": WEB, "client": "acme", "name": "shop"})
J("/api/assign", {"path": GLOBEX, "client": "globex"})
r = cycle("map", WEB); mid = re.search(r"somna review (cyc_\w+)", r.stdout).group(1)
check("map still waits for review (you started it)", last()["id"] == mid and not last().get("review"))
J("/api/adopt", {"id": mid})

# ---------- 1. adopt automatically when safe ----------
out = cycle("create", "--sessions", "a1,b1", env={"MOCK_TIDY": "1"})
r = last()
check("safe cycle saved automatically", (r.get("review") or {}).get("decision") == "adopted" and r["review"].get("auto") is True, r.get("review"))
check("change is in memory", "cycle acme update" in open(CTX).read())
check("CLI says so", "Saved automatically" in out.stdout, out.stdout[-300:])
check("auto adopt logged with actor auto", '"actor": "auto"' in open(M + "/logs/somna.jsonl").read() and "adopt.auto" in open(M + "/logs/somna.log").read())
sm = J("/api/summary")[1]
check("summary lists the automatic save", len(sm["auto"]) == 1 and sm["auto"][0]["changes"] >= 2 and "shop" in sm["auto"][0]["repos"], sm)
check("held questions survive the automatic save", sm["questions"] >= 2, sm)
auto_id = r["id"]

# ---------- 2. not safe -> waits, with reasons ----------
cycle("create", "--sessions", "a1")
r = last()
check("guardrail revert blocks the automatic save", not r.get("review") and any("outside its folders" in w for w in r.get("auto_blocked", [])), r.get("auto_blocked"))
J("/api/discard", {"id": r["id"]})
cycle("create", "--sessions", "a1", env={"MOCK_TIDY": "1", "MOCK_DECISIONS": "lowapplied"})
r = last()
check("low confidence applied blocks it", not r.get("review") and any("low-confidence" in w for w in r.get("auto_blocked", [])), r.get("auto_blocked"))
J("/api/discard", {"id": r["id"]})
cycle("create", "--sessions", "a1", env={"MOCK_TIDY": "1", "MOCK_DECISIONS": "none"})
r = last()
check("missing decisions block it", not r.get("review") and r.get("auto_blocked"), r.get("auto_blocked"))
check("summary shows what waits and why", any(b["id"] == r["id"] for b in J("/api/summary")[1]["blocked"]))
J("/api/discard", {"id": r["id"]})
J("/api/settings", {"settings": {"review_mode": "manual"}})
cycle("create", "--sessions", "a1", env={"MOCK_TIDY": "1"})
r = last()
check("manual mode: everything waits", not r.get("review") and not r.get("auto_blocked"), r.get("review"))
J("/api/discard", {"id": r["id"]})
s, j = J("/api/settings", {"settings": {"review_mode": "sometimes"}})
check("review mode validated", s == 400, j)
J("/api/settings", {"settings": {"review_mode": "auto"}})

# ---------- 3. undo ----------
before_undo = open(CTX).read()
s, j = J("/api/undo", {"id": auto_id})
check("undo accepted", s == 200 and "Undone" in j["message"], j)
check("memory back as before", "cycle acme update" not in open(CTX).read(), open(CTX).read()[-200:])
check("undo in changelog", "undid " + auto_id in open(M + "/CHANGELOG.md").read())
check("sessions will be read again", "a1" not in json.load(open(M + "/cycles/state.json")).get("read_sessions", {}))
s, j = J("/api/undo", {"id": auto_id})
check("cannot undo twice", s == 400, j)
check("summary no longer counts the undone save", not J("/api/summary")[1]["auto"])
cycle("create", "--sessions", "a1", env={"MOCK_TIDY": "1"})
r2 = last()
check("next cycle saved again automatically", (r2.get("review") or {}).get("auto"), r2.get("auto_blocked"))
s, fj = J("/api/file?path=memory/clients/acme/repos/shop.md")
J("/api/file", {"path": "memory/clients/acme/repos/shop.md", "content": fj["content"].replace("- cycle acme update", "- owner rewrote this line"), "sha": fj["sha"]})
s, j = J("/api/undo", {"id": r2["id"]})
check("undo refuses when later edits touch the same lines", s == 409 and "conflict" in j["error"], j)
check("nothing changed after a refused undo", "owner rewrote this line" in open(CTX).read())

# ---------- 4. questions and expiry ----------
q = J("/api/questions")[1]["questions"]
check("questions across cycles with destination and expiry", q and all("accept_to" in x and "expires_in_days" in x for x in q), q[:1])
s, j = J("/api/decision", {"id": q[0]["cycle"], "index": q[0]["index"], "answer": "dismiss"})
check("answer from the questions list", s == 200 and len(J("/api/questions")[1]["questions"]) == len(q) - 1)
J("/api/settings", {"settings": {"held_expiry_days": 1}})
for d_ in os.listdir(M + "/cycles"):
    pth = os.path.join(M, "cycles", d_, "cycle.json")
    if d_.startswith("cyc_") and os.path.exists(pth):
        rr = json.load(open(pth)); rr["created_at"] = (dt.datetime.utcnow() - dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"); json.dump(rr, open(pth, "w"))
sm = J("/api/summary")[1]
check("unanswered questions expire", sm["questions"] == 0 and len(J("/api/questions")[1]["questions"]) == 0, sm)
check("expiry logged", "questions.expired" in open(M + "/logs/somna.log").read())
J("/api/settings", {"settings": {"held_expiry_days": 7}})

# ---------- 5. fairer outdated check ----------
def session(sid, msgs, mode="w"):
    with open(pdir + "/" + sid + ".jsonl", mode) as f:
        for ts, role, text in msgs:
            f.write(json.dumps({"type": role, "sessionId": sid, "cwd": WEB, "timestamp": ts,
                                "message": {"role": role, "content": text if role == "user" else [{"type": "text", "text": text}]}}) + "\n")
session("old1", [("2026-09-27T09:00:00Z", "user", "OLD: compliance items open"), ("2026-09-27T09:30:00Z", "assistant", "noted")])
cycle("create", "--sessions", "old1,a1", env={"MOCK_DECISIONS": "dates"})
r = last()
by = {d["summary"]: d for d in r["decisions"]}
check("old session not yet curated is not dropped", not by["from an old session"].get("dropped") and not by["from an old session"].get("older_than_target"), by["from an old session"])
check("date only from Claude never drops", not by["compliance items open"].get("dropped"), by["compliance items open"])
J("/api/discard", {"id": r["id"]})
st = json.load(open(M + "/cycles/state.json")); st.setdefault("read_sessions", {})["old1"] = "2026-09-27T09:30:00Z"; json.dump(st, open(M + "/cycles/state.json", "w"))
cycle("create", "--sessions", "old1,a1", env={"MOCK_DECISIONS": "dates"})
r = last()
by = {d["summary"]: d for d in r["decisions"]}
check("old session already curated and older than the file is dropped", by["from an old session"].get("dropped") == "outdated" and "already curated" in by["from an old session"].get("drop_reason", ""), by["from an old session"])
J("/api/discard", {"id": r["id"]})

# ---------- 6. freshness at session start + corrections ----------
with open(CTX, "a") as f:
    f.write("\n## How to navigate it\n- app code in `envs/web/app.py`\n- network in `modules/gone/main.tf`, `modules/old-net/`, `scripts/deploy.sh`\n")
subprocess.run(["git", "-C", M, "commit", "-qam", "edit context"])
h = json.loads(cycle("hook", "session-start").stdout if False else subprocess.run([PY, M + "/bin/somna", "hook", "session-start"], input=json.dumps({"cwd": WEB}), capture_output=True, text=True).stdout)["hookSpecificOutput"]["additionalContext"]
check("session start says how fresh the context is", "Freshness: context as of" in h and "commit" in h and "branch main" in h, h[:600])
check("paths that no longer exist are named", "modules/gone/main.tf" in h and "scripts/deploy.sh" in h and "envs/web/app.py" not in h.split("no longer exist")[1].split("\n")[0], h[:700])
check("sessions are told to verify and report corrections", "starting map, not the truth" in h and "CORRECTION:" in h)
check("freshness logged", '"missing_paths": 3' in open(M + "/logs/somna.jsonl").read())
w = [x for x in J("/api/repos")[1]["repos"] if x["path"] == WEB][0]
check("Repos flags a context with gone paths", any(c["code"] == "stale_paths" for c in w["checks"]), [c["code"] for c in w["checks"]])
check("cycle prompt applies corrections first", "CORRECTION were checked against the code" in open(M + "/engine/prompt.md").read())
t0 = time.time(); [subprocess.run([PY, M + "/bin/somna", "hook", "session-start"], input=json.dumps({"cwd": WEB}), capture_output=True, text=True) for _ in range(3)]
check("session start stays fast", (time.time() - t0) / 3 < 1.5, round((time.time() - t0) / 3, 2))

cycle("create", "--sessions", "a1", env={"MOCK_MODE": "fail"})
fid = last()["id"]
check("a failed cycle shows in the summary", any(x["id"] == fid for x in J("/api/summary")[1].get("failed", [])), J("/api/summary")[1].get("failed"))

# ---------- 7. UI ----------
session("u1", [("2026-10-09T23:30:00Z", "user", "fresh work for the UI test"), ("2026-10-09T23:40:00Z", "assistant", "ok")])
cycle("create", "--sessions", "u1", env={"MOCK_TIDY": "1"})
auto2 = last()
check("fresh session saved automatically", (auto2.get("review") or {}).get("auto"), auto2.get("auto_blocked"))
cycle("create", "--sessions", "b1")


async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); errs = []
        pg = await b.new_page(viewport={"width": 1360, "height": 900})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(BASE + "/"); await pg.wait_for_timeout(1200)
        await pg.click('nav button[data-tab="review"]'); await pg.wait_for_timeout(900)
        t = await pg.inner_text("main")
        check("UI summary: saved automatically, waiting, questions", "While you were away" in t and "Saved automatically" in t and "Waiting for you" in t, t[:600])
        check("UI pill counts questions", "question" in await pg.inner_text("#pendingPill"))
        await pg.screenshot(path=SHOTS + "/summary.png", full_page=True)
        await pg.click('nav button[data-tab="questions"]'); await pg.wait_for_timeout(900)
        t = await pg.inner_text("main")
        check("UI Questions tab lists open questions", "Questions" in t and "Accept →" in t and "expires in" in t, t[:400])
        n0 = await pg.locator('[data-qa="accept"]').count()
        await pg.locator('[data-qa="accept"]').first.click(); await pg.wait_for_timeout(900)
        check("UI accept from Questions", await pg.locator('[data-qa="accept"]').count() == n0 - 1)
        await pg.screenshot(path=SHOTS + "/questions.png", full_page=True)
        await pg.click('nav button[data-tab="review"]'); await pg.wait_for_timeout(700)
        await pg.locator('[data-sum="undo"]').first.click(); await pg.wait_for_timeout(1500)
        rr = json.load(open(M + "/cycles/" + auto2["id"] + "/cycle.json"))
        check("UI Undo from the summary", bool(rr["review"].get("undone_at")), rr["review"])
        await pg.click('[data-sum="seen"]'); await pg.wait_for_timeout(900)
        check("UI Got it clears the automatic part", "Saved automatically" not in (await pg.inner_text("main")).split("Sessions read")[0])
        await pg.click('nav button[data-tab="settings"]'); await pg.wait_for_timeout(900)
        check("UI review mode in Settings", "Adopt automatically when safe" in await pg.inner_html("#f_review_mode"))
        await pg.click('nav button[data-tab="review"]'); await pg.wait_for_timeout(500)
        await pg.click('[data-help="summary"]'); await pg.wait_for_timeout(300)
        check("UI help explains the summary", "Undo puts memory back" in await pg.inner_text("#pop"))
        check("UI no page errors", not errs, errs)
        await b.close()

asyncio.run(ui())
print("SUMMARY", "all passed" if not FAILS else "FAILED: " + ", ".join(FAILS))
