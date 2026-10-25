"""Browser test: no page jumps during jobs, real progress, busy buttons, glass screenshots."""
import asyncio, json, os, re, sys, time
from playwright.async_api import async_playwright

PORT = sys.argv[2]
OUT = os.environ.get("SHOTS", "/tmp")
H = os.environ["HOME"]
URL = "http://127.0.0.1:" + PORT + "/"
FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "   -> " + str(extra)[:300]))
    if not cond:
        FAILS.append(name)


def add_session(repo, sid, text):
    d = H + "/.claude/projects/" + re.sub(r"[^a-zA-Z0-9]", "-", repo)
    os.makedirs(d, exist_ok=True)
    with open(d + "/" + sid + ".jsonl", "w") as f:
        f.write(json.dumps({"type": "user", "sessionId": sid, "cwd": repo, "message": {"role": "user", "content": text}}) + "\n")


WATCH = """() => { window.__mut = 0; window.__busySeen = 0;
  new MutationObserver((m) => { m.forEach((x) => { if (x.type === 'childList' && x.target.id === 'main') window.__mut++; }); })
    .observe(document.getElementById('main'), { childList: true });
  new MutationObserver(() => { if (document.querySelector('.btn.is-busy')) window.__busySeen++; })
    .observe(document.body, { attributes: true, subtree: true, attributeFilter: ['class'] }); }"""


async def follow_job(pg, label):
    pcts, saw_steps, titles = [], 0, set()
    for _ in range(80):
        await pg.wait_for_timeout(500)
        if await pg.is_visible("#dock"):
            t = (await pg.inner_text("#dPct")).strip()
            titles.add((await pg.inner_text("#dTitle")).strip())
            saw_steps = max(saw_steps, await pg.locator("#dock .stp").count())
            if t.endswith("%"):
                pcts.append(int(t[:-1]))
        if await pg.evaluate("document.getElementById('dock').classList.contains('done')"):
            break
    done = await pg.evaluate("document.getElementById('dock').classList.contains('done')")
    check(label + ": dock shows progress", len(pcts) >= 3, pcts)
    check(label + ": progress never goes backwards", all(b >= a for a, b in zip(pcts, pcts[1:])), pcts)
    check(label + ": reaches done", done and pcts and pcts[-1] == 100, pcts[-5:])
    check(label + ": dock lists steps", saw_steps >= 2, saw_steps)
    return pcts, titles


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        errs = []
        pg = await b.new_page(viewport={"width": 1360, "height": 760}, color_scheme="dark")
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(URL)
        await pg.wait_for_timeout(1000)
        await pg.screenshot(path=OUT + "/glass-dark-review.png", full_page=False)

        # ---- Map from the Repos tab: page must stay still
        await pg.click('nav button[data-tab="repos"]')
        await pg.wait_for_timeout(900)
        await pg.locator(".repo-btn", has_text="shop").first.click()
        await pg.wait_for_timeout(500)
        await pg.evaluate("window.scrollTo(0, 250)")
        await pg.evaluate(WATCH)
        y0 = await pg.evaluate("window.scrollY")
        await pg.click("#rMap")
        await pg.wait_for_timeout(1800)
        await pg.screenshot(path=OUT + "/glass-dark-dock.png", full_page=False)
        mut_mid = await pg.evaluate("window.__mut")
        pcts, titles = await follow_job(pg, "map")
        check("map: busy spinner shown on the clicked button", await pg.evaluate("window.__busySeen") > 0)
        check("map: no page re-render while running", mut_mid == 0, mut_mid)
        mut_end = await pg.evaluate("window.__mut")
        check("map: at most one quiet re-render when it finishes", mut_end <= 1, mut_end)
        y1 = await pg.evaluate("window.scrollY")
        check("map: scroll position kept", abs(y1 - y0) < 5, (y0, y1))
        check("map: dock title names the repo", any("Mapping" in t for t in titles), titles)
        await pg.click("#dOpen")
        await pg.wait_for_timeout(900)
        check("dock button opens the proposal", "Repo context for" in await pg.inner_text("main"))
        await pg.screenshot(path=OUT + "/glass-dark-map-review.png", full_page=False)
        await pg.click('[data-act="adopt"]')
        await pg.wait_for_timeout(1200)
        check("adopt from the page works", "Adopted" in await pg.inner_text("main"))

        # ---- Run cycle now with two scopes
        add_session(H + "/code/acme-shop", "m1", "deploy wave 3")
        add_session(H + "/code/globex-infra", "m2", "rotate queue certs")
        await pg.click('nav button[data-tab="history"]')
        await pg.wait_for_timeout(700)
        await pg.evaluate(WATCH)
        await pg.click("#runBtn")
        await pg.wait_for_timeout(200)
        await pg.click("#shStart")
        await pg.wait_for_timeout(1200)
        mut_mid = await pg.evaluate("window.__mut")
        pcts, titles = await follow_job(pg, "cycle")
        check("cycle: no page re-render while running", mut_mid == 0, mut_mid)
        check("cycle: dock names the client being curated", any("Running" in t for t in titles), titles)
        for _ in range(15):
            if await pg.inner_text("#runBtn") == "Run cycle now":
                break
            await pg.wait_for_timeout(200)
        check("cycle: run button disabled while running then back", await pg.inner_text("#runBtn") == "Run cycle now")

        # ---- quiet poll does not repaint when nothing changed
        await pg.click('nav button[data-tab="health"]')
        await pg.wait_for_timeout(500)
        await pg.evaluate(WATCH)
        await pg.evaluate("quiet()")
        await pg.wait_for_timeout(800)
        check("idle refresh does not repaint", await pg.evaluate("window.__mut") == 0)

        # ---- light theme + phone screenshots
        lp = await b.new_page(viewport={"width": 1360, "height": 860}, color_scheme="light")
        lp.on("pageerror", lambda e: errs.append(str(e)))
        await lp.goto(URL)
        await lp.wait_for_timeout(900)
        await lp.click('nav button[data-tab="repos"]')
        await lp.wait_for_timeout(900)
        await lp.hover("#scan")
        await lp.wait_for_timeout(250)
        await lp.screenshot(path=OUT + "/glass-light-repos.png", full_page=False)
        ph = await b.new_page(viewport={"width": 390, "height": 844}, color_scheme="dark")
        ph.on("pageerror", lambda e: errs.append(str(e)))
        await ph.goto(URL)
        await ph.wait_for_timeout(900)
        check("phone: no horizontal scroll", not await ph.evaluate("document.documentElement.scrollWidth > window.innerWidth"))
        await ph.screenshot(path=OUT + "/glass-phone.png", full_page=False)
        check("no page errors", not errs, errs)
        await b.close()
    print("SUMMARY", "all passed" if not FAILS else "FAILED: " + ", ".join(FAILS))


asyncio.run(main())
