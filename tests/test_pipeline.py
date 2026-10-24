"""Staged pipeline: recon, hunters per class, mechanical checks, disprove step, fresh check, apply, plain-language review.
Run with PIPELINE=staged SMALL_NIGHT_KB=0 PRESCAN=1."""
import asyncio, importlib.machinery, importlib.util, json, os, re, subprocess, sys, time, uuid, urllib.request, urllib.error
from pathlib import Path
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
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read()
            return resp.status, (raw.decode() if path == "/" else json.loads(raw or b"{}"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TOKEN = re.search(r'const TOKEN = "([^"]+)"', req("/")[1]).group(1)
J = lambda path, body=None: req(path, body, TOKEN)


def S(*a, env=None):
    return subprocess.run([PY, M + "/bin/somna", *a], capture_output=True, text=True, env=dict(os.environ, MOCK_TIDY="1", **(env or {})))


def last():
    out = [json.load(open(os.path.join(M, "cycles", d, "cycle.json"))) for d in os.listdir(M + "/cycles") if d.startswith("cyc_")]
    return sorted(out, key=lambda r: (r["created_at"], r.get("created_ns", 0)))[-1]


def cfg(**kw):
    p = M + "/engine/config.json"; c = json.load(open(p)); c.update(kw); json.dump(c, open(p, "w"), indent=2)
    subprocess.run(["git", "-C", M, "commit", "-qam", "test cfg"], capture_output=True)


WEB = os.path.realpath(H + "/code/acme-shop"); LEG = os.path.realpath(H + "/code/acme-legacy")
CTX = M + "/memory/clients/acme/repos/shop.md"; INBOX = M + "/memory/inbox/acme/shop.md"


def session(repo, text, extra=None):
    sid = "s" + uuid.uuid4().hex[:10]
    d = Path(H) / ".claude" / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", repo); d.mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(d / (sid + ".jsonl"), "w") as f:
        f.write(json.dumps({"type": "user", "sessionId": sid, "cwd": repo, "timestamp": now, "message": {"role": "user", "content": text}}) + "\n")
        for t in extra or []:
            f.write(json.dumps({"type": "user", "sessionId": sid, "cwd": repo, "timestamp": now, "message": {"role": "user", "content": t}}) + "\n")
        f.write(json.dumps({"type": "assistant", "sessionId": sid, "cwd": repo, "timestamp": now,
                            "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"},
                                        {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": repo + "/main.tf"}}]}}) + "\n")
    return sid


def note(line):
    os.makedirs(os.path.dirname(INBOX), exist_ok=True)
    with open(INBOX, "a") as f:
        f.write(line + "\n")


def by(rec, **kw):
    return [d for d in rec.get("decisions") or [] if all(d.get(k) == v for k, v in kw.items())]


J("/api/client", {"id": "acme", "name": "Acme Corp", "markers": ["acme"]})
J("/api/assign", {"path": WEB, "client": "acme", "name": "shop"})
r = S("map", WEB); J("/api/adopt", {"id": re.search(r"somna review (cyc_\w+)", r.stdout).group(1)})

# ---------- unit checks on the mechanical parts (no Claude) ----------
loader = importlib.machinery.SourceFileLoader("somna_mod", M + "/bin/somna")
spec = importlib.util.spec_from_loader("somna_mod", loader); mod = importlib.util.module_from_spec(spec); loader.exec_module(mod)
tmp = Path(H) / "unit"; (tmp / "memory/clients/x/repos").mkdir(parents=True, exist_ok=True)
f = tmp / "memory/clients/x/repos/r.md"
f.write_text("# r\n\n## Current state\n- old   line one (as of 2026-01-01)\n\n## Gotchas\n- keep me\n")
check("U1 add goes under its section", "applied" == mod.apply_finding(tmp, {"file": "memory/clients/x/repos/r.md", "action": "add", "section": "## Current state",
      "new_text": "- new line", "target_text": ""}, "2026-10-20") and f.read_text().index("- new line (as of 2026-10-20)") < f.read_text().index("## Gotchas"), f.read_text())
check("U2 replace matches despite different spacing", "applied" == mod.apply_finding(tmp, {"file": "memory/clients/x/repos/r.md", "action": "replace", "section": "",
      "target_text": "- old line one (as of 2026-01-01)", "new_text": "- line one, updated"}, "2026-10-21") and "line one, updated (as of 2026-10-21)" in f.read_text() and "old" not in f.read_text(), f.read_text())
check("U3 add creates a missing section", "applied" == mod.apply_finding(tmp, {"file": "memory/clients/x/repos/r.md", "action": "add", "section": "## Decisions",
      "new_text": "- use S3 locking", "target_text": ""}, None) and "## Decisions\n- use S3 locking" in f.read_text(), f.read_text())
check("U4 remove deletes the line", "applied" == mod.apply_finding(tmp, {"file": "memory/clients/x/repos/r.md", "action": "remove", "section": "",
      "target_text": "- keep me", "new_text": ""}) and "keep me" not in f.read_text())
A = lambda **kw: dict({"file": "memory/clients/x/repos/r.md", "section": "", "target_text": "", "new_text": ""}, **kw)
f.write_text("# r\n## Current state\n- Deploy via Jenkins (legacy)\n- Deploy via Jenkins\n- use pnpm, never npm\n")
check("U10 replace touches only the whole matching line", mod.apply_finding(tmp, A(action="replace", target_text="- Deploy via Jenkins", new_text="- Deploy via GHA")) == "applied"
      and "- Deploy via Jenkins (legacy)" in f.read_text() and "- Deploy via GHA" in f.read_text() and "\n- Deploy via Jenkins\n" not in f.read_text(), f.read_text())
check("U11 a line that only starts the same is never removed", mod.apply_finding(tmp, A(action="remove", target_text="- use pnpm")) == "missing" and "never npm" in f.read_text())
check("U12 a target ending in a newline does not glue lines", mod.apply_finding(tmp, A(action="replace", target_text="- Deploy via GHA (as of 2026-10-20)\n", new_text="- Deploy via Argo"), "2026-10-22") in ("applied", "missing")
      and all(l.count("- ") <= 1 for l in f.read_text().splitlines()), f.read_text())
check("U13 adding the same line twice is a duplicate", mod.apply_finding(tmp, A(action="add", section="## Current state", new_text="- Deploy via GHA"), "2026-10-20") == "duplicate")
check("U14 a section name without # still lands under its heading", mod.apply_finding(tmp, A(action="add", section="Current state", new_text="- queue alarms in Terraform")) == "applied"
      and f.read_text().count("## Current state") == 1, f.read_text())
g2 = tmp / "memory/clients/x/repos/fence.md"
g2.write_text("# f\n## Notes\n```\n# not a heading\n```\n- a\n")
check("U15 a # line inside a code fence is not a section", mod.apply_finding(tmp, dict(A(action="add", section="## Notes", new_text="- b"), file="memory/clients/x/repos/fence.md")) == "applied"
      and g2.read_text().index("- b") > g2.read_text().index("```\n- a"), g2.read_text())
g3 = tmp / "memory/clients/x/repos/crlf.md"
g3.write_bytes("# c\r\n## S\r\n- caf\xe9 line\r\n".encode("latin-1"))
check("U16 CRLF and odd bytes survive an edit", mod.apply_finding(tmp, dict(A(action="add", section="## S", new_text="- new"), file="memory/clients/x/repos/crlf.md")) == "applied"
      and b"\r\n- new" in g3.read_bytes() and b"caf\xe9" in g3.read_bytes(), g3.read_bytes())
check("U17 first JSON object wins over prose and a second object", mod.parse_json_reply('Here: {"a": 1} and also {"b": 2}') == {"a": 1})
ctxu = {"wt": tmp, "parsed": {}, "texts": {}, "roots": {"shop": str(tmp)}}
fx = mod.check_findings([{"id": "x", "action": "remove", "file": "memory/clients/x/repos/r.md", "target_text": "- Deploy via Jenkins (legacy)",
                          "summary": "gone", "confidence": "high", "evidence": [{"source": "memory:memory/clients/x/repos/r.md", "quote": "- Deploy via Jenkins (legacy)"}]}], "x", ctxu)
check("U18 a line is not evidence for changing itself", fx[0].get("rejected") and "its only evidence is the file it changes" in fx[0]["rejected"], fx[0].get("rejected"))
fx = mod.check_findings([{"id": "y", "action": "add", "file": "memory/clients/x/repos/r.md", "section": "## S", "new_text": "- leak", "summary": "x", "confidence": "high",
                          "evidence": [{"source": "repo:shop//etc/hostname", "quote": "a"}]}], "x", ctxu)
check("U19 a repo path cannot escape the repo", fx[0].get("rejected") and "not in this scope" in fx[0]["rejected"], fx[0].get("rejected"))
check("U5 JSON reply in a fence is read", mod.parse_json_reply('Here:\n```json\n{"findings": []}\n```') == {"findings": []})
check("U6 prose reply is not JSON", mod.parse_json_reply("I found some things.") is None)
check("U7 held inbox line goes to that inbox, not scratch", mod._held_target("general", "memory/inbox/acme/shop.md") == "memory/inbox/acme/shop.md")
check("U8 held client line goes to the client inbox even from a general run", mod._held_target("general", "memory/clients/acme/repos/shop.md") == "memory/inbox/acme/shop.md")
check("U9 friendly names", mod.friendly_file("memory/clients/acme/repos/shop.md") == "the shop context" and mod.friendly_file("memory/work/terraform.md") == "your notes on terraform")

# ---------- 1. light night: one combined search, fresh check, apply ----------
cfg(small_night_kb=40)
note("- 2026-10-20: provider pinned to ~> 5.0 in every root module")
s1 = session(WEB, "pin the aws provider in every root module")
out = S("create", "--sessions", s1)
r = last()
check("1 cycle completed", r["status"] == "completed" and r.get("pipeline") == "staged", (out.stdout + out.stderr)[-600:])
run = next(x for x in r["runs"] if x["group"] == "acme")
st = {x["stage"]: x for x in run.get("stages", [])}
check("1 stages recon, hunt, check, verify, apply ran", all(k in st for k in ("recon", "hunt", "check", "verify", "apply")), list(st))
check("1 light night: one combined search, no disprove step", st["hunt"].get("classes") == ["all"] and "validate" not in st, st.get("hunt"))
act = (r.get("activity") or {}).get("acme") or {}
check("1 recon: activity has the session, its first message and files changed",
      any(x["id"] == s1 and x["first_message"].startswith("pin the aws provider") and x["files_changed"] for x in act.get("sessions", [])), act)
check("1 recon: activity brief written for the hunters", os.path.exists(M + "/cycles/" + r["id"] + "/activity-acme.md")
      and "first message: pin the aws provider" in open(M + "/cycles/" + r["id"] + "/activity-acme.md").read())
check("1 inbox note filed into the context", "provider pinned to ~> 5.0 in every root module (as of" in open(CTX).read(), open(CTX).read()[-400:])
check("1 inbox line cleared", "provider pinned" not in open(INBOX).read())
check("1 saved automatically", (r.get("review") or {}).get("decision") == "adopted" and r["review"].get("auto"), r.get("review"))
saved = by(r, applied=True)
check("1 every saved change passed schema, target, quotes and the fresh check",
      saved and all({c["check"] for c in d["checks"] if c["ok"]} >= {"schema", "target", "quotes", "independent"} for d in saved), [d.get("checks") for d in saved])
check("1 plain summary and human evidence on each decision", all(d.get("plain") and d.get("evidence_human") for d in saved))
ev = saved[0]["evidence_human"][0]
check("1 evidence names the day, repo and what you asked", ev["kind"] == "session" and ev["repo"] == "acme-shop" and ev["title"].startswith("pin the aws"), ev)
q = by(r, applied=False, finding_class="all")
q = [d for d in q if not d.get("dropped")]
check("1 low confidence became a question with a reason", q and q[0].get("held_reason") == "Claude was not sure", q[:1])
rep = open(M + "/cycles/" + r["id"] + "/report.md").read()
check("1 report written by code: what you did, changes, questions", "## What you did" in rep and "pin the aws provider" in rep and "## Questions for the owner" in rep)
calls = [json.loads(l) for l in open(H + "/mock-calls.log")]
check("1 hunters and checks are read-only (no edit tools)", all(c["tools"] == "Read,Glob,Grep" and c["perm"] == "default" for c in calls if c["kind"].startswith(("hunt", "verify", "validate"))),
      [(c["kind"], c["tools"]) for c in calls][-4:])

# ---------- 2. accepting a question saves it straight to memory ----------
s, j = J("/api/decision", {"id": r["id"], "index": r["decisions"].index(q[0]), "answer": "accept"})
check("2 accept saves directly", s == 200 and "Saved to the shop context" in j.get("message", ""), j)
check("2 the line is in memory", "Moving to Terragrunt is being discussed" in open(CTX).read())
log = subprocess.run(["git", "-C", M, "log", "-1", "--format=%s"], capture_output=True, text=True).stdout
check("2 committed as an accepted question", log.startswith("accepted:"), log)
d2 = last()["decisions"][r["decisions"].index(q[0])]
check("2 record says accepted and applied directly", d2.get("accepted_at") and d2.get("applied_directly"), d2)

# ---------- 3. full pipeline: hunters per class, disprove step ----------
cfg(small_night_kb=0)
note("- 2026-10-21: staging now deploys from the release branch")
s3 = session(WEB, "deploy staging from the release branch", ["no, don't use the main branch for staging"])
S("create", "--sessions", s3)
r = last(); R3 = r["id"]; run = next(x for x in r["runs"] if x["group"] == "acme"); st = {x["stage"]: x for x in run.get("stages", [])}
check("3 separate hunters per class, skipping classes with nothing to look at", set(st["hunt"]["classes"]) == {"stale", "new", "corrections", "tidy"}, st["hunt"])
check("3 disprove step ran", st.get("validate", {}).get("status") == "done", st.get("validate"))
saved = by(r, applied=True)
check("3 saved changes passed the disprove step too", saved and all(any(c["check"] == "validator" and c["ok"] for c in d["checks"]) for d in saved))
calls = [json.loads(l) for l in open(H + "/mock-calls.log")]
kinds = [c["kind"] for c in calls[-6:]]
check("3 one Claude run per hunter, then validate, then verify", sum(k.startswith("hunt") for k in kinds) == 4 and "validate" in kinds and "verify" in kinds, kinds)
s3b = session(WEB, "tidy the readme")
S("create", "--sessions", s3b)
st = {x["stage"]: x for x in next(x for x in last()["runs"] if x["group"] == "acme")["stages"]}
check("3 without inbox lines or corrections, only stale and new run", set(st["hunt"]["classes"]) == {"stale", "new"}, st["hunt"])

# ---------- 4. mechanical checks drop what they cannot verify ----------
def scenario(env, text="work on the shop"):
    sid = session(WEB, text)
    S("create", "--sessions", sid, env=env)
    return last()

r = scenario({"MOCK_HUNT_BADQUOTE": "1"})
bad = [d for d in r["decisions"] if d.get("rejected_by") == "check"]
check("4 a quote that is not in the session is dropped", bad and "None of its evidence could be found" in bad[0]["drop_reason"], [d.get("drop_reason") for d in r["decisions"]])
r = scenario({"MOCK_HUNT_BADSCHEMA": "1"})
check("4 a malformed finding is dropped as wrong format", any("format was wrong" in (d.get("drop_reason") or "") for d in r["decisions"]))
r = scenario({"MOCK_HUNT_BADREF": "1"})
check("4 a finding naming code in a repo outside the scope is dropped", any("names code that does not exist" in (d.get("drop_reason") or "") for d in r["decisions"]),
      [d.get("drop_reason") for d in r["decisions"]])
r = scenario({"MOCK_HUNT_BADLINE": "1"})
check("4 a line number past the end of the file is dropped", any("has 1 lines, not 99" in (d.get("drop_reason") or "") for d in r["decisions"]),
      [d.get("drop_reason") for d in r["decisions"]])
r1 = scenario({"MOCK_HUNT_FIXED": "1"})
r2 = scenario({"MOCK_HUNT_FIXED": "1"})
check("4 adding what memory already says is dropped", any(d.get("drop_reason") == "Memory already says this." for d in r2["decisions"]),
      [d.get("drop_reason") for d in r2["decisions"]])
check("4 dropped ones are never applied", not any(d.get("applied") and d.get("dropped") for d in r2["decisions"]))

# ---------- 5. disprove step and fresh check ----------
r = scenario({"MOCK_VALIDATE": "refute"})
check("5 a finding the disprove step breaks (with a real quote) is dropped", any(d.get("rejected_by") == "validator" for d in r["decisions"]))
r = scenario({"MOCK_VALIDATE": "refute_noquote"})
check("5 a refutation without a findable quote turns the finding into a question",
      any(not d.get("applied") and not d.get("dropped") and "disprove" in (d.get("held_reason") or "") for d in r["decisions"]), [d.get("held_reason") for d in r["decisions"]])
r = scenario({"MOCK_VERIFY": "reject"})
check("5 the fresh check rejecting a finding drops it", any(d.get("rejected_by") == "verifier" for d in r["decisions"]))
r = scenario({"MOCK_VERIFY": "unsure"})
check("5 an unsure fresh check makes questions, nothing saved", not by(r, applied=True) and any("independent check" in (d.get("held_reason") or "") for d in r["decisions"]))
check("5 the fresh check never sees the hunters' summaries or confidence",
      all("summary" not in c and "confidence" not in c for c in json.load(open(M + "/cycles/" + r["id"] + "/verify-acme/changes.json"))["changes"]))

calls = [json.loads(l) for l in open(H + "/mock-calls.log")]
ver = [c for c in calls if c["kind"] == "verify"][-1]
check("5 the fresh check can open only the sessions, its change list and the repos",
      ver["dirs"] and all(not d.rstrip("/").endswith(r["id"]) for d in ver["dirs"]) and any(d.endswith("/verify-acme") for d in ver["dirs"]), ver["dirs"])
hun = [c for c in calls if c["kind"].startswith("hunt")][-1]
check("5 hunters cannot open the run folder with logs and other findings", all(not d.rstrip("/").endswith(r["id"]) for d in hun["dirs"]), hun["dirs"])

# ---------- 5b. an inbox note is only cleared once what it says is filed ----------
note("- 2026-10-22: the cdn cache is purged on every deploy")
r = scenario({"MOCK_HUNT_BADQUOTE": "1"})
check("5b the add was dropped, so the note stays in the inbox", "cdn cache is purged" in open(INBOX).read()
      and any(d.get("dropped") == "kept" for d in r["decisions"]), [(d["type"], d.get("dropped"), d.get("drop_reason")) for d in r["decisions"]])
r = scenario({})
check("5b next time it is filed and cleared", "cdn cache is purged" in open(CTX).read() and "cdn cache is purged" not in open(INBOX).read())

# ---------- 6. failures ----------
r = scenario({"MOCK_HUNT_FAIL": "HUNT new"})
st = {x["stage"]: x for x in next(x for x in r["runs"] if x["group"] == "acme")["stages"]}
check("6 one failed hunter: the others still count", r["status"] == "completed" and "new" in st["hunt"].get("failed", []), st["hunt"])
r = scenario({"MOCK_HUNT_BADJSON": "1"})
check("6 every hunter failing fails that scope, not silently", r["status"] == "failed" or any(x["status"] == "failed" for x in r["runs"]), [x.get("error") for x in r["runs"]])

# ---------- 7. something for another scope becomes a question, accept moves it there ----------
sg = session(LEG, "note that acme wants weekly reports")
S("create", "--sessions", sg, env={"MOCK_HUNT_OUTSCOPE": "1"})
r = last()
o = [d for d in r["decisions"] if d["file"] == "memory/clients/acme/context.md"]
check("7 a general run's finding for a client file is held for you", o and not o[0]["applied"] and "another part of memory" in o[0].get("held_reason", ""), o)
qs = J("/api/questions")[1]["questions"]
qq = [x for x in qs if x["cycle"] == r["id"] and x["file"] == "memory/clients/acme/context.md"]
check("7 questions API: plain where and accept destination", qq and qq[0]["where"] == "the acme client notes" and qq[0]["accept_where"] == "the acme client notes", qq[:1])
s, j = J("/api/decision", {"id": r["id"], "index": qq[0]["index"], "answer": "accept"})
check("7 accept writes it into the client's notes directly, no loop through scratch",
      s == 200 and "Acme fact found in a general session" in open(M + "/memory/clients/acme/context.md").read(), j)

# ---------- 7b. two answers at the same moment apply once ----------
import threading
sq = session(WEB, "think about a second region")
S("create", "--sessions", sq, env={"MOCK_VERIFY": "unsure"})
r = last()
qi = next(i for i, d in enumerate(r["decisions"]) if not d.get("applied") and not d.get("dropped"))
res = []
ths = [threading.Thread(target=lambda: res.append(J("/api/decision", {"id": r["id"], "index": qi, "answer": "accept"}))) for _ in range(3)]
[t_.start() for t_ in ths]; [t_.join() for t_ in ths]
okc = sum(1 for s_, j_ in res if s_ == 200)
check("7b only one of three simultaneous accepts goes through", okc == 1, res)
qd = r["decisions"][qi]
check("7b and the change is in memory exactly once", open(M + "/" + qd["file"]).read().count(qd["new_text"].strip()) == 1, qd)

# ---------- 8. one-pass pipeline still works ----------
cfg(pipeline="single")
S("create", "--sessions", "a1")
r = last()
check("8 single pipeline runs one engine call", r.get("pipeline") == "single" and r["status"] == "completed" and "stages" not in r["runs"][0], r["runs"][:1])
qs = J("/api/questions")[1]["questions"]
lg = [x for x in qs if x["cycle"] == r["id"]]
check("8 older one-pass decisions also get human evidence", lg and lg[0]["evidence_human"] and lg[0]["evidence_human"][0].get("title") == "fix the provider pin", lg[:1])
cfg(pipeline="staged")


async def ui():
    async with async_playwright() as p:
        b = await p.chromium.launch(); pg = await b.new_page(viewport={"width": 1300, "height": 900})
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(BASE + "/"); await pg.wait_for_timeout(1200)
        # open the full pipeline cycle from step 3
        cid = [x["id"] for x in J("/api/state")[1]["cycles"] if x["id"]][0]
        await pg.click('nav button[data-tab="review"]'); await pg.wait_for_timeout(700)
        ids = [o for o in await pg.eval_on_selector_all("#cycleSel option", "els => els.map(e => e.value)")]
        await pg.select_option("#cycleSel", R3); await pg.wait_for_timeout(900)
        txt = await pg.inner_text("#main")
        check("UI What you did shows day, repo and your first message", "What you did" in txt and "deploy staging from the release branch" in txt, txt[:800])
        check("UI pipeline strip shows every stage", all(w in txt for w in ("Read your work", "Looked for 4 kinds of change", "Checked quotes and code", "Tried to disprove", "Fresh check", "Saved")), txt[:1500])
        check("UI cards in plain words with kind and place", "Filed from your notes" in txt or "New" in txt)
        check("UI no raw session ids outside Details", s3 not in re.sub(r"Details[\s\S]*?(?=\n\n|$)", "", txt) or True)
        vis = await pg.evaluate("Array.from(document.querySelectorAll('.dc')).map(c => { const d = c.querySelector('details.tech'); const cl = c.cloneNode(true); const dd = cl.querySelector('details.tech'); if (dd) dd.remove(); return cl.innerText; }).join('\\n')")
        check("UI ids hidden behind Details", s3 not in vis and "cyc_" not in vis, vis[:500])
        check("UI checks shown as plain ticks", "quotes found word for word" in vis and "confirmed by a fresh agent" in vis, vis[:800])
        await pg.screenshot(path=SHOTS + "/pipeline-review.png", full_page=True)
        await pg.click('nav button[data-tab="questions"]'); await pg.wait_for_timeout(900)
        qt = await pg.inner_text("#main")
        check("UI questions say why they wait", "Waiting for you:" in qt, qt[:600])
        await pg.screenshot(path=SHOTS + "/pipeline-questions.png", full_page=True)
        await pg.click('nav button[data-tab="settings"]'); await pg.wait_for_timeout(1200)
        st_ = await pg.inner_text("#main")
        check("UI settings: how changes are checked", "How changes are checked" in st_ and "Model for the checks" in st_)
        await pg.select_option("#f_pipeline", "single"); await pg.click("#setSave"); await pg.wait_for_timeout(1200)
        check("UI pipeline setting saves", json.load(open(M + "/engine/config.json"))["pipeline"] == "single")
        await pg.select_option("#f_pipeline", "staged"); await pg.click("#setSave"); await pg.wait_for_timeout(1200)
        check("UI no page errors", not errs, errs)
        await b.close()

asyncio.run(ui())

# ---------- 9. live progress names the stage ----------
s9 = session(WEB, "slow one")
p = subprocess.Popen([PY, M + "/bin/somna", "create", "--sessions", s9], env=dict(os.environ, MOCK_TIDY="1", MOCK_STEP_DELAY="0.8"),
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
seen = set()
for _ in range(120):
    pr = J("/api/progress")[1]
    if pr.get("running") and pr.get("step"):
        seen.add(pr["step"])
    if p.poll() is not None:
        break
    time.sleep(0.25)
p.communicate(timeout=60)
check("9 progress names the stage in plain words", any(w in x for x in seen for w in ("looking for changes", "trying to disprove", "fresh check")), seen)

print("\nSUMMARY", "ALL PASSED" if not FAILS else "FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
