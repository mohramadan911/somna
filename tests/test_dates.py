"""Dates on inputs, time rules, outdated evidence dropped, routing of held changes, incremental reading."""
import asyncio, json, os, re, subprocess, sys, time, urllib.request, urllib.error
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


WEB = os.path.realpath(H + "/code/acme-shop")
pdir = H + "/.claude/projects/" + re.sub(r"[^a-zA-Z0-9]", "-", WEB)
J("/api/client", {"id": "acme", "name": "Acme Corp", "markers": ["acme"]})
J("/api/assign", {"path": WEB, "client": "acme", "name": "shop"})
r = cycle("map", WEB); mid = re.search(r"somna review (cyc_\w+)", r.stdout).group(1)
J("/api/adopt", {"id": mid})


def session(sid, msgs, mode="w"):
    with open(pdir + "/" + sid + ".jsonl", mode) as f:
        for ts, role, text in msgs:
            f.write(json.dumps({"type": role, "sessionId": sid, "cwd": WEB, "timestamp": ts,
                                "message": {"role": role, "content": text if role == "user" else [{"type": "text", "text": text}]}}) + "\n")


session("old1", [("2026-09-27T09:00:00Z", "user", "OLD: three compliance items open"), ("2026-09-27T09:30:00Z", "assistant", "noted")])
session("new1", [("2026-10-08T14:00:00Z", "user", "NEW: compliance items closed"), ("2026-10-08T15:45:00Z", "assistant", "done")])
old_commit_env = dict(os.environ, GIT_AUTHOR_DATE="2026-09-20T10:00:00Z", GIT_COMMITTER_DATE="2026-09-20T10:00:00Z")
open(WEB + "/old.txt", "w").write("x\n")
subprocess.run("cd '%s' && git add old.txt && git commit -qm 'old bucket note'" % WEB, shell=True, env=old_commit_env)
OLDSHA = subprocess.run(["git", "-C", WEB, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()

J("/api/settings", {"settings": {"stale_after_days": 30}})
cycle("create", "--sessions", "new1,old1,a1", env={"MOCK_DECISIONS": "dates", "MOCK_COMMIT": OLDSHA})
r = last()
ddir = M + "/cycles/" + r["id"]

# ---------- dates on inputs ----------
d_new = open(ddir + "/sessions/acme/new1.md").read()
check("digest has first and last activity", "- first activity: 2026-10-08T14:00:00Z" in d_new and "- last activity: 2026-10-08T15:45:00Z" in d_new, d_new[:300])
check("every message carries its time", "[2026-10-08 14:00] **user:** NEW" in d_new and "[2026-10-08 15:45] **assistant:**" in d_new, d_new)
prompt = open(ddir + "/prompt-acme.md").read()
check("prompt has time rules and today's date", "## Time rules" in prompt and "Today is 20" in prompt and "Later sessions and commits win" in prompt)
tbl = prompt[prompt.index("oldest first:"):prompt.index("Last update of the files")]
check("sessions listed oldest first", tbl.index("old1") < tbl.index("new1") < tbl.index("a1"), tbl)
check("prompt lists when each file was last updated", "memory/clients/acme/repos/shop.md: 20" in prompt)
check("stale cleanup days from Settings", "more than 30 days old" in prompt)
check("decisions schema asks for evidence dates and scope", '"evidence_dates"' in prompt and '"scope"' in prompt)

# ---------- decisions: dates, drop, routing ----------
decs = r["decisions"]
by = {d["summary"]: d for d in decs}
old = by["compliance items open"]
check("a date only Claude gave never drops anything", not old.get("dropped") and old.get("evidence_newest") == "2026-09-27", old)
oc = by["old commit says state bucket in us-east-1"]
check("commit evidence dated from git, then dropped", oc.get("evidence_newest") == "2026-09-20" and oc.get("dropped") == "outdated", oc)
fresh = by["fresh but unsure"]
check("recent held change stays a question", not fresh.get("dropped") and fresh.get("evidence_newest") == "2026-10-09", fresh)
check("repo change routed to the repo inbox", fresh["accept_to"] == "memory/inbox/acme/shop.md", fresh.get("accept_to"))
gen = by["general AWS lesson"]
check("client-neutral lesson routed to general memory", gen["scope"] == "general" and gen["accept_to"] == "memory/scratch/notes.md", gen)
check("counts include dropped", r["decision_counts"]["dropped"] == 1 and r["decision_counts"]["held"] >= 2, r["decision_counts"])
check("drop logged", "decisions.dropped_outdated" in open(M + "/logs/somna.log").read())
gi = decs.index(gen)
s, j = J("/api/decision", {"id": r["id"], "index": gi, "answer": "accept"})
check("accepting the general lesson writes to general notes", s == 200 and "Check aws sts get-caller-identity" in open(M + "/memory/scratch/notes.md").read(), j)
s, j = J("/api/decision", {"id": r["id"], "index": decs.index(oc), "answer": "accept"})
check("a dropped change cannot be accepted", s == 400, j)
pending_id = r["id"]

# ---------- incremental reading ----------
J("/api/discard", {"id": pending_id})
session("inc1", [("2026-10-09T08:00:00Z", "user", "FIRST PART decision A"), ("2026-10-09T08:10:00Z", "assistant", "ok A")])
cycle("create", "--sessions", "inc1")
r1 = last()
J("/api/adopt", {"id": r1["id"]})
st = json.load(open(M + "/cycles/state.json"))
check("adopt remembers how far each session was read", st.get("read_sessions", {}).get("inc1") == "2026-10-09T08:10:00Z", st.get("read_sessions"))
session("inc1", [("2026-10-09T18:00:00Z", "user", "SECOND PART decision B"), ("2026-10-09T18:05:00Z", "assistant", "ok B")], mode="a")
cycle("create", "--sessions", "inc1")
r2 = last()
dg = open(M + "/cycles/" + r2["id"] + "/sessions/acme/inc1.md").read()
check("resumed session: earlier part compact, new part in full", "Already read in an earlier cycle" in dg and "[New since the earlier cycle]" in dg
      and "SECOND PART decision B" in dg and "FIRST PART decision A" in dg, dg)
m2 = [m for m in [i for i in r2["inputs"] if i["type"] == "sessions"][0]["sessions"] if m["id"] == "inc1"][0]
check("record shows what was already read", m2.get("already_read_until") == "2026-10-09T08:10:00Z" and m2.get("last_activity") == "2026-10-09T18:05:00Z", m2)
discarded = r2["id"]
cycle("create", "--sessions", "new1,old1,a1", env={"MOCK_DECISIONS": "dates", "MOCK_COMMIT": OLDSHA})
J("/api/discard", {"id": discarded})


async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); errs = []
        pg = await b.new_page(viewport={"width": 1360, "height": 900})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE + "/"); await pg.wait_for_timeout(1000)
        await pg.click("#pendingPill"); await pg.wait_for_timeout(1000)
        t = await pg.inner_text("main")
        check("UI shows evidence dates on decisions, file dates under Details", "Oct 9" in t and "file last updated: 20" in await pg.inner_html("main"), t[:600])
        check("UI Accept names the destination", "Accept → your notes" in t and "Accept → the shop context" in t)
        check("UI general lesson marked", "lesson for your notes" in t)
        html = await pg.inner_html("main")
        qsec = html[html.index('<div class="decs">'):html.index("Checked and dropped</strong>")]
        check("UI dropped changes kept out of the questions", "old commit says state bucket" not in qsec and "Checked and dropped" in t)
        check("UI tile counts dropped", " dropped" in t)
        await pg.locator("summary", has_text="Checked and dropped").click(); await pg.wait_for_timeout(300)
        check("UI dropped reason shows the dates", "older than the file's last update" in await pg.inner_text("main"))
        await pg.locator("summary", has_text="Sessions read").click(); await pg.wait_for_timeout(300)
        t2 = await pg.inner_text("main")
        check("UI sessions table has first and last activity", "First activity" in t2 and "Last activity" in t2)
        await pg.screenshot(path=SHOTS + "/dates-review.png", full_page=True)
        await pg.click("#runBtn"); await pg.check('input[name="shSrc"][value="pick"]'); await pg.wait_for_timeout(900)
        check("UI picker shows first and last activity", "→" in await pg.inner_text("#shList"))
        await pg.keyboard.press("Escape")
        await pg.click('nav button[data-tab="settings"]'); await pg.wait_for_timeout(900)
        check("UI cleanup setting", "Clean up current state after" in await pg.inner_text("main"))
        check("UI no page errors", not errs, errs)
        await b.close()

asyncio.run(ui())
print("SUMMARY", "all passed" if not FAILS else "FAILED: " + ", ".join(FAILS))
