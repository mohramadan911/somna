"""Ask Somna (scoped bundle, answers, validated actions) and the security audit (recon, hunters, checks, disprove,
fresh check, report, save to memory). Run with PRESCAN=1 SETUP=1."""
import asyncio, json, os, re, subprocess, sys, time, urllib.request, urllib.error
from playwright.async_api import async_playwright

PY, PORT = sys.argv[1], sys.argv[2]
H = os.environ["HOME"]; M = H + "/somna"; BASE = "http://127.0.0.1:" + PORT
SHOTS = os.environ.get("SHOTS", "/tmp")
FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "   -> " + str(extra)[:600]))
    if not cond:
        FAILS.append(name)


def req(path, body=None, token=None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(BASE + path, data=data, method="POST" if data is not None else "GET")
    if token: r.add_header("X-Somna-Token", token)
    if data is not None: r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = resp.read()
            return resp.status, (raw.decode() if path == "/" else json.loads(raw or b"{}"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TOKEN = re.search(r'const TOKEN = "([^"]+)"', req("/")[1]).group(1)
J = lambda path, body=None: req(path, body, TOKEN)
S = lambda *a, env=None: subprocess.run([PY, M + "/bin/somna", *a], capture_output=True, text=True, env=dict(os.environ, MOCK_TIDY="1", **(env or {})))
git = lambda *a: subprocess.run(["git", "-C", M, *a], capture_output=True, text=True).stdout


def last(kind=None):
    out = [json.load(open(os.path.join(M, "cycles", d, "cycle.json"))) for d in os.listdir(M + "/cycles") if d.startswith("cyc_")]
    out = [r for r in out if not kind or r.get("type") == kind]
    return sorted(out, key=lambda r: (r["created_at"], r.get("created_ns", 0)))[-1]


def wait_idle(t=60):
    for _ in range(t * 4):
        if not J("/api/progress")[1].get("running"):
            return True
        time.sleep(0.25)
    return False


def ask(q, focus=None):
    s, j = J("/api/ask", {"question": q, "focus": focus, "tab": "review"})
    mat = json.loads(open(H + "/mock-ask.log").read().splitlines()[-1])["material"] if os.path.exists(H + "/mock-ask.log") else ""
    return s, j.get("entry") or j, mat


WEB = os.path.realpath(H + "/code/acme-shop"); GLOBEX = os.path.realpath(H + "/code/globex-infra")
CTX = M + "/memory/clients/acme/repos/shop.md"
for root in (WEB, GLOBEX):
    r = S("map", root); J("/api/adopt", {"id": re.search(r"somna review (cyc_\w+)", r.stdout).group(1)})
with open(CTX, "a") as f:
    f.write("\n## How it ships\n- Deploy via Jenkins\n")
git("commit", "-qam", "test: jenkins line")

# ---------- Ask Somna ----------
s, e, mat = ask("What do you know about my notes?")
check("A1 answers", s == 200 and e.get("answer"), e)
check("A1 general memory is always in the material", "### memory/index.md" in mat and "Settings" in mat)
check("A1 no client files when no client is named", "### memory/clients/" not in mat, re.findall(r"### memory/clients/\S+", mat)[:3])
s, e, mat = ask("What do you know about shop?")
check("A2 naming a repo brings in its client's files", "### memory/clients/acme/repos/shop.md" in mat and e.get("scope") == ["acme"], e.get("scope"))
check("A2 never another client's files", "memory/clients/globex/" not in mat.split("## Clients and repos")[0] and "### memory/clients/globex" not in mat)
calls = [json.loads(l) for l in open(H + "/mock-calls.log")]
check("A2 the chat runs with no tools at all", [c for c in calls if c["kind"] == "ask"][-1]["tools"] == "")

s, e, mat = ask("Make nights cheaper")
a = (e.get("actions") or [None])[0]
check("A3 a settings suggestion with before and after", a and a["type"] == "settings" and a["changes"][0]["key"] == "check_model" and a["changes"][0]["to"] == "haiku", e)
check("A3 nothing changed before the click", json.load(open(M + "/engine/config.json")).get("check_model", "") != "haiku")
s, j = J("/api/chat_action", {"entry": e["id"], "action": a["id"]})
check("A3 the click saves it through the normal settings check", s == 200 and json.load(open(M + "/engine/config.json"))["check_model"] == "haiku", j)
s, j = J("/api/chat_action", {"entry": e["id"], "action": a["id"]})
check("A3 a suggestion runs once", s != 200 and "already done" in j.get("error", ""), j)
s, j = J("/api/chat_action", {"entry": e["id"], "action": "a9"})
check("A3 a made-up suggestion id is refused", s != 200, j)

s, e, mat = ask("Turn on the nonsense setting")
check("A4 an invalid setting is left out with the reason", not e["actions"] and any("no setting called turbo_mode" in x for x in e.get("refused", [])), e)

s, e, mat = ask("The shop context still says Jenkins, we use GitHub Actions now")
a = next((x for x in e["actions"] if x["type"] == "memory"), None)
check("A5 a memory change comes as a checked suggestion", a and a["file"] == "memory/clients/acme/repos/shop.md" and a["where"] == "the shop context"
      and any(c["check"] == "target" and c["ok"] for c in a["checks"]), e)
s, j = J("/api/chat_action", {"entry": e["id"], "action": a["id"]})
txt = open(CTX).read()
check("A5 saving it changes exactly that line", s == 200 and "- Deploys run from GitHub Actions" in txt and "Deploy via Jenkins" not in txt, j)
check("A5 committed as a change from Ask Somna", git("log", "-1", "--format=%s").startswith("ask:"))
s, e, mat = ask("Add the sneaky line about shop")
check("A6 a change for a client outside the conversation is refused", not [x for x in e["actions"] if x["type"] == "memory"] and
      any("not about" in x for x in e.get("refused", [])), e)

s, e, mat = ask("Run a cycle now please, run")
a = next((x for x in e["actions"] if x["type"] == "run"), None)
check("A7 a run suggestion", a and a["since_hours"] == 24 and a["instructions"], e)
s, j = J("/api/chat_action", {"entry": e["id"], "action": a["id"]})
check("A7 the click starts a cycle", s == 200 and "started" in j.get("message", "").lower(), j)
wait_idle()
s, e, mat = ask("From now on always keep the decision list")
a = next((x for x in e["actions"] if x["type"] == "steer"), None)
s, j = J("/api/chat_action", {"entry": e["id"], "action": a["id"]})
check("A8 a standing rule lands in steering, committed", "Always keep the decision list as it is." in open(M + "/engine/steering.md").read() and git("log", "-1", "--format=%s").startswith("steering:"), j)

s, e, mat = ask("What does a session in shop see at start?")
check("A9 it can show what the hook injects", "What a Claude Code session in shop gets at start" in mat and "Repo context for shop" in mat, mat[-600:])
open(M + "/memory/inbox/acme/shop.md", "a").write("- 2026-10-20: a note\n")
r = S("create", "--sessions", "a1")
rec = last("cycle")
qi = next((i for i, d in enumerate(rec.get("decisions") or []) if not d.get("applied") and not d.get("dropped")), 0)
s, e, mat = ask("Why is this here?", {"cycle": rec["id"], "index": qi})
check("A10 the open item is in the material with its client's files", "The item the owner has open" in mat and "### memory/clients/acme/" in mat, mat[:300])
s, e, mat = ask("hello", None)
r = S("ask", "Say", "something", env={"MOCK_ASK_PROSE": "1"})
check("A11 a reply that is not JSON still shows as an answer", r.returncode == 0 and "Just some text, not JSON." in r.stdout and "suggestion" not in r.stdout, r.stdout + r.stderr)
hist = J("/api/chat")[1]["entries"]
check("A12 the conversation is kept on this Mac", len(hist) >= 10 and os.path.exists(M + "/chat/history.jsonl"))
check("A12 and never committed", "chat/" in open(M + "/.gitignore").read() and "chat/history.jsonl" not in git("ls-files"))
# memory busy: a proposal waits, so the change is queued instead
r = S("map", WEB)
check("A13 a proposal is waiting", any(x["needs_review"] for x in J("/api/state")[1]["cycles"]))
s, e, mat = ask("Please note that shop releases are tagged on Fridays")
a = next((x for x in e["actions"] if x["type"] == "memory"), None)
s, j = J("/api/chat_action", {"entry": e["id"], "action": a["id"]}) if a else (0, {})
check("A13 while memory is busy the change is queued for the next cycle, not forced in", s == 200 and "busy" in j.get("message", "")
      and "Releases are tagged on Fridays" in open(M + "/memory/inbox/acme/shop.md").read() and "Releases are tagged" not in open(CTX).read(), j)

# ---------- security audit ----------
J("/api/discard", {"id": last("map")["id"]})
r = S("audit", WEB)
A = last("audit")
st = {x["stage"]: x for x in A.get("stages", [])}
check("S1 audit completed with every stage", A["status"] == "completed" and all(k in st for k in ("recon", "hunt", "check", "validate", "verify")), (r.stdout + r.stderr)[-500:])
check("S1 recon picked the attack classes", [c["id"] for c in A["attack_classes"]] == ["http-auth", "supply-chain"], A.get("attack_classes"))
F = {f["title"]: f for f in A["audit_findings"]}
check("S1 real findings are confirmed", F["App prints without auth check"]["status"] == "confirmed" and F["Provider not pinned"]["status"] == "confirmed", {k: v["status"] for k, v in F.items()})
check("S1 the same place found twice is merged", F["Same app issue seen twice"]["status"] == "rejected" and "Same problem" in F["Same app issue seen twice"]["rejected"])
check("S1 a finding in a file that does not exist is rejected by code", "does not exist" in F["Made up file"].get("rejected", ""))
check("S1 report and findings.json written", os.path.exists(M + "/cycles/" + A["id"] + "/report.md") and
      len(json.load(open(M + "/cycles/" + A["id"] + "/findings.json"))["confirmed"]) == 2)
check("S1 the repo was not touched", not A.get("warning") and subprocess.run(["git", "-C", WEB, "status", "--porcelain"], capture_output=True, text=True).stdout == "")
calls = [json.loads(l) for l in open(H + "/mock-calls.log")]
au = [c for c in calls if c["kind"].startswith("audit")]
check("S1 every audit run only reads", au and all(c["tools"] == "Read,Glob,Grep" and c["perm"] == "default" for c in au), [(c["kind"], c["tools"]) for c in au])
ver = [c for c in au if c["kind"] == "audit verify"][-1]
check("S1 the fresh check opens only its own folder", len(ver["dirs"]) == 1 and ver["dirs"][0].endswith("/audit/verify"), ver["dirs"])
check("S1 nothing saved to memory yet", "## Security findings" not in open(CTX).read())

r = S("audit", WEB, env={"MOCK_AUDIT_BADLINE": "1", "MOCK_AUDIT_ESCAPE": "1"})
F = {f["title"]: f for f in last("audit")["audit_findings"]}
check("S2 a line past the end of the file is rejected", "lines, not 40" in F["Line past the end"].get("rejected", ""), F.get("Line past the end"))
check("S2 a path outside the repo is rejected", F["Escape"]["status"] == "rejected" and "does not exist" in F["Escape"].get("rejected", ""), F.get("Escape"))
check("S2 a finding seen in an earlier audit says so", F["App prints without auth check"].get("seen_in"))
r = S("audit", WEB, env={"MOCK_AUDIT_REFUTE": "1"})
F = {f["title"]: f for f in last("audit")["audit_findings"]}
check("S3 a finding the disprove step breaks with real code is rejected", F["Provider not pinned"].get("rejected_by") == "validator", F["Provider not pinned"])
r = S("audit", WEB, env={"MOCK_AUDIT_UNSURE": "1"})
F = {f["title"]: f for f in last("audit")["audit_findings"]}
check("S4 an unsure fresh check means needs validation", F["App prints without auth check"]["status"] == "needs_validation")
r = S("audit", WEB, "--classes", "cloud")
A2 = last("audit")
check("S5 --classes skips recon's choice", [c["id"] for c in A2["attack_classes"]] == ["cloud"], A2.get("attack_classes"))
r = S("audit", WEB, env={"MOCK_AUDIT_HUNTFAIL": "1"})
check("S6 every hunter failing fails the audit", last("audit")["status"] == "failed")
r = S("audit", WEB)
A = last("audit")
for c in J("/api/state")[1]["cycles"]:
    if c["needs_review"]:
        J("/api/discard", {"id": c["id"]})
s, j = J("/api/audit_save", {"id": A["id"]})
txt = open(CTX).read()
check("S7 saving puts confirmed findings in the repo context", s == 200 and "## Security findings" in txt and "[high] App prints without auth check: envs/web/app.py:1" in txt, j)
check("S7 only confirmed ones by default", "Made up file" not in txt and "Same app issue" not in txt)
s, j = J("/api/audit_save", {"id": A["id"]})
check("S7 saving twice does nothing", s != 200 and "nothing to save" in j.get("error", ""), j)
hook = subprocess.run([PY, M + "/bin/somna", "hook", "session-start"], input=json.dumps({"cwd": WEB, "session_id": "x"}), capture_output=True, text=True).stdout
check("S8 the next session in the repo knows about them", "App prints without auth check" in hook)
check("S9 the security-audit skill is installed and linked", os.path.islink(H + "/.claude/skills/security-audit") and
      "somna audit" in open(H + "/.claude/skills/security-audit/SKILL.md").read())


async def ui():
    async with async_playwright() as p:
        b = await p.chromium.launch(); pg = await b.new_page(viewport={"width": 1360, "height": 900})
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE + "/"); await pg.wait_for_timeout(1200)
        await pg.click("#askBtn"); await pg.wait_for_timeout(600)
        check("UI Ask opens with the history", await pg.is_visible("#ask") and "Make nights cheaper" in await pg.inner_text("#askLog"))
        await pg.fill("#askQ", "Make nights cheaper please"); await pg.click("#askSend")
        for _ in range(40):
            await pg.wait_for_timeout(250)
            if await pg.locator("#askLog [data-askact]").count():
                break
        # check_model is already haiku, so expect it to be left out
        t = await pg.inner_text("#askLog")
        check("UI answer shows with cost and what it read", "$0.004" in t and "read:" in t, t[-400:])
        await pg.screenshot(path=SHOTS + "/ask-panel.png")
        await pg.click("#askClose")
        await pg.click('nav button[data-tab="review"]'); await pg.wait_for_timeout(700)
        await pg.select_option("#cycleSel", A["id"]); await pg.wait_for_timeout(900)
        t = await pg.inner_text("#main")
        check("UI audit view: findings by status with severity and place", "Security audit of shop" in t and "Confirmed" in t and "envs/web/app.py:1" in t and "Checked and rejected" in t, t[:600])
        check("UI audit view: saved findings say so", "Saved to memory." in t)
        await pg.screenshot(path=SHOTS + "/audit-review.png", full_page=True)
        await pg.click('nav button[data-tab="repos"]'); await pg.wait_for_timeout(700)
        await pg.locator(".repo-btn", has_text="shop").first.click(); await pg.wait_for_timeout(600)
        t = await pg.inner_text(".repo-detail")
        check("UI repo shows Run security audit and the last audit", "Run security audit" in t and "Last audit" in t, t[-600:])
        await pg.click("[data-askrepo]"); await pg.wait_for_timeout(500)
        check("UI Ask about this repo focuses the chat", "About the repo" in await pg.inner_text("#askFocus") and (await pg.input_value("#askQ")).startswith("What do you know"))
        await pg.click("#askClose")
        await pg.click('nav button[data-tab="settings"]'); await pg.wait_for_timeout(1000)
        check("UI settings for Ask Somna and audits", "Model for Ask Somna" in await pg.inner_text("#main") and "Attack classes per audit" in await pg.inner_text("#main"))
        check("UI no page errors", not errs, errs)
        await b.close()

asyncio.run(ui())
print("\nSUMMARY", "ALL PASSED" if not FAILS else "FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
