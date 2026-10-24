"""End-to-end from a fresh install: a user journey done only through the page, checked against disk, git and the hook."""
import asyncio, json, os, re, subprocess, sys, time, urllib.request
from playwright.async_api import async_playwright

PY, PORT = sys.argv[1], sys.argv[2]
H = os.environ["HOME"]; M = H + "/somna"; BASE = "http://127.0.0.1:" + PORT
SHOTS = os.environ.get("SHOTS", "/tmp")
FAILS = []
WEB = os.path.realpath(H + "/code/acme-shop"); GLOBEX = os.path.realpath(H + "/code/globex-infra"); LEG = os.path.realpath(H + "/code/acme-legacy")


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "   -> " + str(extra)[:400]))
    if not cond:
        FAILS.append(name)


def get(path):  # read-only, only to wait or verify
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def gitlog(n=1, *paths):
    return subprocess.run(["git", "-C", M, "log", "-%d" % n, "--format=%s", "--", *paths], capture_output=True, text=True).stdout


def hook(cwd):
    r = subprocess.run([PY, M + "/bin/somna", "hook", "session-start"], input=json.dumps({"cwd": cwd}), capture_output=True, text=True)
    return (json.loads(r.stdout or "{}").get("hookSpecificOutput") or {}).get("additionalContext", "")


def recs():
    out = [json.load(open(os.path.join(M, "cycles", d, "cycle.json"))) for d in os.listdir(M + "/cycles") if d.startswith("cyc_")]
    return sorted(out, key=lambda r: (r["created_at"], r.get("created_ns", 0)))


def add_session(repo, sid, text):
    d = H + "/.claude/projects/" + re.sub(r"[^a-zA-Z0-9]", "-", repo)
    os.makedirs(d, exist_ok=True)
    with open(d + "/" + sid + ".jsonl", "w") as f:
        f.write(json.dumps({"type": "user", "sessionId": sid, "cwd": repo, "message": {"role": "user", "content": text}}) + "\n")


reg = lambda: json.load(open(M + "/engine/repos.json"))


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); errs = []
        pg = await b.new_page(viewport={"width": 1360, "height": 900})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        main_t = lambda: pg.inner_text("main")

        async def tab(name):
            await pg.click('nav button[data-tab="%s"]' % name); await pg.wait_for_timeout(900)

        async def wait_job(t=60):
            await pg.wait_for_timeout(600)
            for _ in range(t * 4):
                if not get("/api/progress").get("running"):
                    await pg.wait_for_timeout(2600)
                    return True
                await pg.wait_for_timeout(250)
            return False

        async def pick_repo(name):
            await tab("repos")
            await pg.locator(".repo-btn", has_text=name).first.click(); await pg.wait_for_timeout(500)

        await pg.goto(BASE + "/"); await pg.wait_for_timeout(1200)
        t = await main_t()
        check("A fresh install opens on Start here at 2 of 9", "Start here" in t and "2 of 9 done" in t, t[:200])

        # B. personal memory via the editor
        await pg.click('[data-step="personal"]'); await pg.wait_for_timeout(900)
        await pg.click('.files button[data-path="memory/me/preferences.md"]'); await pg.wait_for_timeout(400)
        await pg.click("#startEdit"); await pg.wait_for_timeout(200)
        cur = await pg.input_value("#editor")
        await pg.fill("#editor", cur + "\n- Prefers short status updates.\n")
        await pg.click("#saveEdit"); await pg.wait_for_timeout(900)
        check("B editor saves to disk", "Prefers short status updates" in open(M + "/memory/me/preferences.md").read())
        check("B editor commits to git", "edit memory/me/preferences.md" in gitlog(1, "memory/me/preferences.md"))

        # C. clients through the form
        for cid, name, mk in (("acme", "Acme Corp", "acme, acme-corp"), ("globex", "Globex", "globex")):
            await tab("repos")
            if not await pg.is_visible("#cId"):
                await pg.click("#addClient"); await pg.wait_for_timeout(300)
            await pg.fill("#cId", cid); await pg.fill("#cName", name); await pg.fill("#cMarkers", mk)
            await pg.click("#cSave"); await pg.wait_for_timeout(700)
        check("C clients saved with markers", reg()["clients"].get("acme", {}).get("markers") == ["acme", "acme-corp"] and "globex" in reg()["clients"], reg()["clients"])

        # D. scan
        await tab("repos"); await pg.click("#scan")
        check("D scan finished", await wait_job())
        await tab("repos")
        t = await main_t()
        check("D scan found the three repos", all(n in t for n in ("acme-shop", "globex-infra", "acme-legacy")), t[:400])

        # E. confirm clients
        for repo, cid, short in (("acme-shop", "acme", "shop"), ("globex-infra", "globex", "globex-infra")):
            await pick_repo(repo)
            await pg.select_option("#rClient", cid); await pg.fill("#rName", short)
            await pg.click("#rAssign"); await pg.wait_for_timeout(800)
        r = reg()["repos"]
        check("E repos confirmed to the right clients", r[WEB]["status"] == "confirmed" and r[WEB]["client"] == "acme" and r[WEB]["name"] == "shop" and r[GLOBEX]["client"] == "globex", {k: (v.get("client"), v.get("status")) for k, v in r.items()})
        check("E inbox created", os.path.exists(M + "/memory/inbox/acme/shop.md"))

        # P. ownership question answered in the page
        await pick_repo("acme-legacy")
        await pg.select_option("#rClient", "acme"); await pg.click("#rAssign"); await pg.wait_for_timeout(800)
        await pick_repo("acme-legacy")
        t = await pg.inner_text(".repo-detail")
        check("P mismatch question shown (acme folder, globex remote)", "Is the mapping right" in t and "Yes, it belongs to" in t, t[:400])
        await pg.click('[data-q="confirm"]'); await pg.wait_for_timeout(800)
        check("P answer stored", reg()["repos"][LEG].get("owner_confirmed") == "acme")

        # F. map and adopt
        await pick_repo("acme-shop")
        await pg.click("#rMap")
        for _ in range(25):
            await pg.wait_for_timeout(200)
            if "read-only" in (await pg.inner_text("#dInfo")):
                break
        check("F dock explains the map", "read-only" in (await pg.inner_text("#dInfo")))
        check("F map finished", await wait_job())
        await pg.click("#dOpen"); await pg.wait_for_timeout(900)
        check("F proposal opens from the dock", "Repo context for shop" in await main_t())
        await pg.click('[data-act="adopt"]'); await pg.wait_for_timeout(1200)
        ctx = M + "/memory/clients/acme/repos/shop.md"
        check("F adopted context on disk", os.path.exists(ctx) and "Terraform for the shop stack" in open(ctx).read())
        check("F hook injects the adopted context", "Terraform for the shop stack" in hook(WEB))
        check("F map head recorded", bool(reg()["repos"][WEB].get("mapped_head")))

        # G. instructions for agents
        await pick_repo("acme-shop")
        await pg.fill("#riRepo", "Ask before touching modules/net."); await pg.fill("#riClient", "Small PRs with an ADR link.")
        await pg.click("#riSave"); await pg.wait_for_timeout(900)
        h = hook(WEB)
        check("G hook carries repo and client instructions", "Ask before touching modules/net." in h and "Small PRs with an ADR link." in h, h[:300])

        # H. settings
        await tab("settings")
        await pg.fill("#nTime", "03:00"); await pg.check("#wOn"); await pg.select_option("#wDay", "6"); await pg.fill("#wTime", "04:00")
        await pg.fill("#f_max_budget_usd", "1.5"); await pg.click("#setSave"); await pg.wait_for_timeout(1200)
        c = json.load(open(M + "/engine/config.json"))
        check("H settings on disk", c["schedule"]["nightly"]["time"] == "03:00" and c["schedule"]["weekly"]["enabled"] and c["schedule"]["weekly"]["time"] == "04:00" and c["max_budget_usd"] == 1.5, c.get("schedule"))
        await pg.click('[data-check="f_model"]'); await pg.wait_for_timeout(1500)
        check("H model check through Claude Code", "works with your Claude Code" in await pg.inner_text("#f_modelChk"))
        s = subprocess.run([PY, M + "/bin/somna", "schedule"], capture_output=True, text=True).stdout
        check("H backend schedule matches the page", "03:00" in s and "Sun" in s, s)

        # I. cycle from the run form, decisions, accept, try, adopt
        await pg.click("#runBtn"); await pg.wait_for_timeout(300)
        await pg.fill("#shInstr", "Focus on the provider pin.")
        await pg.check('input[name="shSrc"][value="pick"]'); await pg.wait_for_timeout(800)
        for title in ("fix the provider pin", "add queue alarms"):
            await pg.locator("#shList .srow", has_text=title).locator("input").check()
        await pg.click("#shStart")
        check("I cycle finished", await wait_job())
        r = recs()[-1]
        check("I run used the form inputs", r.get("instructions") == "Focus on the provider pin." and [i for i in r["inputs"] if i["type"] == "sessions"][0]["session_ids"] == ["a1", "b1"] or
              sorted([i for i in r["inputs"] if i["type"] == "sessions"][0]["session_ids"]) == ["a1", "b1"], r.get("instructions"))
        check("I spend cap from Settings reached Claude Code", any(json.loads(l).get("budget") == "1.5" for l in open(H + "/mock-calls.log")))
        if await pg.is_visible("#dOpen"):
            await pg.click("#dOpen"); await pg.wait_for_timeout(900)
        t = await main_t()
        check("I review shows decisions, held changes and try", "Waiting for you" in t and "Try it before adopting" in t, t[:300])
        await pg.locator('[data-dec="accept"]').first.click(); await pg.wait_for_timeout(900)
        queued = [d for d in recs()[-1]["decisions"] if d.get("accepted_at")]
        check("I accepted change queued in an inbox", queued and "[owner accepted" in open(M + "/" + queued[0]["accepted_to"]).read(), queued)
        await pg.click('[data-act="adopt"]'); await pg.wait_for_timeout(1300)
        check("I adopt merged the cycle", "cycle acme update" in open(ctx).read() and recs()[-1]["review"]["decision"] == "adopted")
        check("I changelog written", "adopted " + recs()[-1]["id"] in open(M + "/CHANGELOG.md").read())
        check("I accepted note survived the adopt", "[owner accepted" in open(M + "/" + queued[0]["accepted_to"]).read())

        # J. concurrency: memory edited while a proposal waits
        add_session(WEB, "j1", "wave 3 cutover done")
        await pg.click("#runBtn"); await pg.wait_for_timeout(200); await pg.click("#shStart")
        check("J cycle finished", await wait_job())
        pending = get("/api/state")["pending"]
        await tab("memory")
        await pg.click('.files button[data-path="memory/clients/acme/context.md"]'); await pg.wait_for_timeout(400)
        await pg.click("#startEdit"); cur = await pg.input_value("#editor")
        await pg.fill("#editor", cur + "\n- Owner edit while the proposal waits.\n"); await pg.click("#saveEdit"); await pg.wait_for_timeout(900)
        await pg.click("#pendingPill"); await pg.wait_for_timeout(900)
        check("J review warns memory changed", await pg.locator('[data-act="force"]').count() == 1)
        await pg.click('[data-act="force"]'); await pg.wait_for_timeout(1300)
        rr = [x for x in recs() if x["id"] == pending[0]][0]
        check("J merge anyway keeps both", rr["review"]["decision"] == "adopted" and rr["review"]["forced"] and "Owner edit while the proposal waits" in open(M + "/memory/clients/acme/context.md").read())

        # K. cancel from the dock
        add_session(GLOBEX, "k1", "rotate certs")
        await pg.click("#runBtn"); await pg.wait_for_timeout(200); await pg.click("#shStart")
        for _ in range(40):
            await pg.wait_for_timeout(200)
            if await pg.is_visible("#dCancel"):
                break
        await pg.wait_for_timeout(400)
        await pg.click("#dCancel"); await wait_job()
        check("K cancel from the dock", recs()[-1]["status"] == "canceled" and not os.path.exists(M + "/.somna-worktrees/" + recs()[-1]["id"]), recs()[-1]["status"])

        # L. versions and redact
        await tab("memory")
        await pg.click('.files button[data-path="memory/me/preferences.md"]'); await pg.wait_for_timeout(300)
        await pg.click("#startEdit"); cur = await pg.input_value("#editor")
        await pg.fill("#editor", cur + "token=sk-EXAMPLE-LEAK-42\n"); await pg.click("#saveEdit"); await pg.wait_for_timeout(800)
        await pg.click("#startEdit"); cur = await pg.input_value("#editor")
        await pg.fill("#editor", cur.replace("token=sk-EXAMPLE-LEAK-42\n", "")); await pg.click("#saveEdit"); await pg.wait_for_timeout(800)
        await pg.click("#showVers"); await pg.wait_for_timeout(900)
        await pg.locator("[data-redact]").first.click(); await pg.wait_for_timeout(3000)
        revs = subprocess.run(["git", "-C", M, "rev-list", "--all"], capture_output=True, text=True).stdout.split()
        leak = subprocess.run(["git", "-C", M, "grep", "-l", "sk-EXAMPLE-LEAK-42", *revs], capture_output=True, text=True).stdout
        check("L redact from the page removes the secret from history", leak.strip() == "", leak)
        check("L memory still consistent after redact", "Prefers short status updates" in open(M + "/memory/me/preferences.md").read()
              and subprocess.run(["git", "-C", M, "fsck", "--no-progress"], capture_output=True).returncode == 0)

        # O. backend failure handling shown in the page
        add_session(WEB, "o1", "x"); add_session(GLOBEX, "o2", "y")
        subprocess.run([PY, M + "/bin/somna", "create", "--sessions", "o1,o2"], env=dict(os.environ, MOCK_MODE="failclient", MOCK_VIOLATE=""), capture_output=True)
        await pg.reload(); await pg.wait_for_timeout(1200)
        await tab("history"); await pg.locator("tr.click").first.click()
        await pg.wait_for_timeout(900)
        t = await main_t()
        check("O failed client parts shown, the rest reviewable", "Some parts failed" in t or "This run failed" in t, t[:400])

        # M. logs and health
        await tab("logs")
        check("M logs show the journey", "adopt.done" in await main_t())
        await tab("health")
        t = await main_t()
        check("M health has no hard failures", "×" not in t, t[:500])
        await tab("start")
        t = await main_t()
        check("N Start here complete", "9 of 9 done" in t, t[:200])
        await pg.screenshot(path=SHOTS + "/e2e-start.png")
        check("no page errors during the journey", not errs, errs)
        await b.close()

asyncio.run(main())
print("SUMMARY", "all passed" if not FAILS else "FAILED: " + ", ".join(FAILS))
