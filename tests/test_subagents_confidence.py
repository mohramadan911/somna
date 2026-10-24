"""AGENTS.md, subagent folding, SubagentStart hook, parallel runs, confidence scoring."""
import asyncio, json, os, re, subprocess, sys, time, urllib.request, urllib.error
from playwright.async_api import async_playwright

PY, PORT = sys.argv[1], sys.argv[2]
H = os.environ["HOME"]; M = H + "/somna"; BASE = "http://127.0.0.1:" + PORT
SHOTS = os.environ.get("SHOTS", "/tmp")
FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "   -> " + str(extra)[:400]))
    if not cond:
        FAILS.append(name)


def req(path, body=None, token=None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(BASE + path, data=data, method="POST" if data is not None else "GET")
    if token: r.add_header("X-Somna-Token", token)
    if data is not None: r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r) as resp:
            raw = resp.read()
            return resp.status, (raw.decode() if path == "/" else json.loads(raw or b"{}"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TOKEN = re.search(r'const TOKEN = "([^"]+)"', req("/")[1]).group(1)
J = lambda path, body=None: req(path, body, TOKEN)


def cycle(*a, env=None, stdin=None):
    return subprocess.run([PY, M + "/bin/somna", *a], capture_output=True, text=True, env=dict(os.environ, **(env or {})), input=stdin)


def last():
    recs = [json.load(open(os.path.join(M, "cycles", d, "cycle.json"))) for d in os.listdir(M + "/cycles") if d.startswith("cyc_")]
    return sorted(recs, key=lambda r: (r["created_at"], r.get("created_ns", 0)))[-1]


def cfg(**kw):
    c = json.load(open(M + "/engine/config.json")); c.update(kw); json.dump(c, open(M + "/engine/config.json", "w"))


WEB = os.path.realpath(H + "/code/acme-shop"); GLOBEX = os.path.realpath(H + "/code/globex-infra")
J("/api/client", {"id": "acme", "name": "Acme Corp", "markers": ["acme"]})
J("/api/client", {"id": "globex", "name": "Globex", "markers": ["globex"]})
J("/api/assign", {"path": WEB, "client": "acme", "name": "shop"})
J("/api/assign", {"path": GLOBEX, "client": "globex"})

# ---------- 1. AGENTS.md ----------
open(WEB + "/AGENTS.md", "w").write("# Agent rules\n- run terraform fmt before commit\n")
subprocess.run("cd '%s' && git add AGENTS.md && git commit -qm agents" % WEB, shell=True)
r = cycle("map", WEB); mid = re.search(r"somna review (cyc_\w+)", r.stdout).group(1)
facts = json.load(open(M + "/cycles/" + mid + "/facts.json"))
check("1 map lists AGENTS.md as a key file", "AGENTS.md" in facts["key_files"], facts["key_files"])
J("/api/discard", {"id": mid})

# ---------- 2. subagent transcripts ----------
pdir = H + "/.claude/projects/" + re.sub(r"[^a-zA-Z0-9]", "-", WEB)
with open(pdir + "/s9.jsonl", "w") as f:
    f.write(json.dumps({"type": "user", "sessionId": "s9", "cwd": WEB, "timestamp": "2026-10-09T09:00:00Z", "message": {"role": "user", "content": "main conversation about the provider pin"}}) + "\n")
    f.write(json.dumps({"type": "assistant", "sessionId": "s9", "cwd": WEB, "message": {"role": "assistant", "content": [{"type": "text", "text": "delegating to a subagent"}]}}) + "\n")
os.makedirs(pdir + "/s9/subagents", exist_ok=True)
with open(pdir + "/s9/subagents/agent-x1.jsonl", "w") as f:
    f.write(json.dumps({"type": "user", "sessionId": "s9", "isSidechain": True, "agentId": "x1", "agentType": "Explore", "cwd": WEB, "message": {"role": "user", "content": "find the IAM issue"}}) + "\n")
    f.write(json.dumps({"type": "assistant", "sessionId": "s9", "isSidechain": True, "agentId": "x1", "agentType": "Explore", "cwd": WEB, "message": {"role": "assistant", "content": [{"type": "text", "text": "subagent found the IAM bug in modules/net"}]}}) + "\n")
ids = [x["id"] for x in J("/api/sessions?days=7")[1]["sessions"]]
check("2 subagent files are not listed as sessions", "agent-x1" not in ids and "s9" in ids, ids)
s9 = [x for x in J("/api/sessions?days=7")[1]["sessions"] if x["id"] == "s9"][0]
check("2 session list counts its subagents", s9["subagents"] == 1, s9)
cycle("create", "--sessions", "s9")
rr = last()
sess = [i for i in rr["inputs"] if i["type"] == "sessions"][0]
check("2 one input per terminal session", sess["session_ids"] == ["s9"] and sess["sessions"][0]["subagents"] == 1, sess)
dig = open(M + "/cycles/" + rr["id"] + "/sessions/acme/s9.md").read()
check("2 main conversation kept (not overwritten by the subagent)", "main conversation about the provider pin" in dig, dig[:300])
check("2 subagent folded in as a labelled section", "## Subagent 1 (Explore)" in dig and "IAM bug" in dig, dig[-300:])
n_all = cycle("create", "--since-hours", "48", "--dry-run").stdout
check("2 time-window runs do not count subagents", "sessions: 4 " in n_all, n_all)
J("/api/discard", {"id": rr["id"]})

# ---------- 3. SubagentStart hook ----------
st = json.load(open(H + "/.claude/settings.json"))
check("3 SubagentStart hook installed", any("hook subagent-start" in h["command"] for e in st["hooks"].get("SubagentStart", []) for h in e["hooks"]), st["hooks"].keys())
out = json.loads(cycle("hook", "subagent-start", stdin=json.dumps({"cwd": WEB, "agent_type": "Explore", "session_id": "s9"})).stdout or "{}")
check("3 subagent gets the repo context", out.get("hookSpecificOutput", {}).get("hookEventName") == "SubagentStart"
      and "Repo context for shop" in out["hookSpecificOutput"].get("additionalContext", ""), out)
check("3 subagent injection logged", "context injected into a subagent" in open(M + "/logs/somna.log").read())
hc = [c for c in J("/api/state")[1]["health"]["checks"] if c["title"] == "Repo context hook"][0]
check("3 health shows both hooks", hc["status"] == "ok" and "SubagentStart" in hc["detail"], hc)

# ---------- 4. parallel runs ----------
cfg(parallel_runs=3)
t0 = time.time()
p = subprocess.Popen([PY, M + "/bin/somna", "create", "--sessions", "a1,b1,c1"], env=dict(os.environ, MOCK_SLOW="3"),
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
seen_multi = False
for _ in range(60):
    pr = J("/api/progress")[1]
    if pr.get("running") and sum(1 for x in pr.get("steps", []) if x["state"] == "active") >= 2 and "running" in pr.get("step", ""):
        seen_multi = True
        break
    time.sleep(0.2)
p.communicate(timeout=60)
dur = time.time() - t0
rr = last()
check("4 three scopes run at the same time", dur < 7.5, round(dur, 1))
check("4 progress shows several scopes running", seen_multi, pr)
check("4 all parts completed", rr["status"] == "completed" and all(x["status"] == "completed" for x in rr["runs"]) and len(rr["runs"]) == 3, rr["runs"])
diff = open(M + "/cycles/" + rr["id"] + "/diff.patch").read()
check("4 proposal combines every scope", "clients/acme/repos/shop.md" in diff and "clients/globex/" in diff and "work/releases.md" in diff, diff[:300])
check("4 parallel plan logged", '"parallel": 3' in open(M + "/logs/somna.jsonl").read())
check("4 no scope worktrees left", not [d for d in os.listdir(M + "/.somna-worktrees") if "--" in d], os.listdir(M + "/.somna-worktrees"))

# ---------- 5. confidence scoring ----------
decs = rr.get("decisions") or []
check("5 decisions recorded per scope", {d["group"] for d in decs} >= {"acme", "globex", "general"}, decs[:2])
check("5 counts", rr["decision_counts"]["high"] >= 3 and rr["decision_counts"]["held"] == 3, rr["decision_counts"])
held = [i for i, d in enumerate(decs) if not d["applied"] and d["group"] == "acme"][0]
s, j = J("/api/decision", {"id": rr["id"], "index": held, "answer": "accept"})
check("5 accept a held change", s == 200 and "inbox/acme/shop.md" in j["message"], j)
check("5 accepted change queued in the repo inbox", "[owner accepted, from " + rr["id"] in open(M + "/memory/inbox/acme/shop.md").read())
s, j = J("/api/decision", {"id": rr["id"], "index": held, "answer": "accept"})
check("5 cannot answer twice", s == 400, j)
gh = [i for i, d in enumerate(decs) if not d["applied"] and d["group"] == "general"][0]
s, j = J("/api/decision", {"id": rr["id"], "index": gh, "answer": "dismiss"})
check("5 dismiss a held change", s == 200 and last()["decisions"][gh].get("dismissed_at"), j)
lh = [i for i, d in enumerate(decs) if not d["applied"] and d["group"] == "globex"][0]
check("5 CLI accept", "Accepted" in cycle("accept", rr["id"], str(lh)).stdout)
check("5 CLI decisions list", "held" in cycle("decisions", rr["id"]).stdout or "accepted" in cycle("decisions", rr["id"]).stdout)
prompt = open(M + "/cycles/" + rr["id"] + "/prompt-acme.md").read()
check("5 prompt asks for the decisions file and holds low confidence", "decisions-acme.json" in prompt and "Do NOT apply low-confidence" in prompt)
J("/api/discard", {"id": rr["id"]})

cycle("create", "--sessions", "a1", env={"MOCK_DECISIONS": "none"})
rr = last()
check("5 missing decisions file flagged", rr["runs"][0]["decisions"] == "missing" and any(d.get("synthetic") for d in rr["decisions"]), rr.get("decisions"))
J("/api/discard", {"id": rr["id"]})
cycle("create", "--sessions", "a1", env={"MOCK_DECISIONS": "lowapplied"})
rr = last()
check("5 low confidence applied anyway is flagged", any(d.get("rule_broken") for d in rr["decisions"]), rr["decisions"])
J("/api/discard", {"id": rr["id"]})
cfg(hold_low_confidence=False, parallel_runs=1)
cycle("create", "--sessions", "a1,b1")
rr = last()
prompt = open(M + "/cycles/" + rr["id"] + "/prompt-acme.md").read()
check("5 hold can be turned off", "You may apply low-confidence" in prompt)
check("4 sequential mode still works", rr["status"] == "completed" and len(rr["runs"]) == 2, rr["runs"])
cfg(hold_low_confidence=True, parallel_runs=3)


async def ui():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(); errs = []
        pg = await b.new_page(viewport={"width": 1360, "height": 900})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE + "/"); await pg.wait_for_timeout(900)
        txt = await pg.inner_text("main")
        check("UI decisions card", ("What changed" in txt or "Waiting for you" in txt) and "Confidence" in txt, txt[:400])
        n = await pg.locator('[data-dec="accept"]').count()
        check("UI held changes have Accept", n >= 1, n)
        await pg.screenshot(path=SHOTS + "/decisions.png", full_page=True)
        await pg.locator('[data-dec="accept"]').first.click(); await pg.wait_for_timeout(900)
        check("UI accept marks it accepted", "Accepted. The next cycle files it in" in await pg.inner_text("main"))
        await pg.click("#runBtn"); await pg.check('input[name="shSrc"][value="pick"]'); await pg.wait_for_timeout(800)
        check("UI session picker shows subagent count", "1 subagent" in await pg.inner_text("#shList"))
        check("UI no page errors", not errs, errs)
        await b.close()

asyncio.run(ui())
print("SUMMARY", "all passed" if not FAILS else "FAILED: " + ", ".join(FAILS))
