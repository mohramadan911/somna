# Tests

Every test installs Somna into a throwaway home folder, starts the review page and talks to it
over HTTP or through a headless browser. `mock_claude` stands in for the Claude Code CLI, so no
test calls Claude or costs anything. All clients, repos and sessions are fictional (Acme, Globex).

Requirements: Python 3.9+, git, and for the browser tests Playwright with Chromium
(`pip install playwright && playwright install chromium`).

```bash
# tests/run.sh <workdir> <port> <test file>
PRESCAN=1 tests/run.sh /tmp/somna-t1 4801 test_scopes.py
MOCK_STEP_DELAY=1 tests/run.sh /tmp/somna-t2 4802 test_e2e.py
```

| Variable | Meaning |
|---|---|
| `PRESCAN=1` | Scan the fake sessions once before the test. All suites except `test_e2e.py` expect it. |
| `SETUP=1` | Create the two sample clients and assign their repos first (`test_ui_motion.py` needs it) |
| `MOCK_STEP_DELAY=1` | Slow the mock down, so cancel and progress checks can catch a run in progress: `1` for `test_e2e.py` and `test_ui_review.py`, `2` for `test_ui_motion.py` |
| `SHOTS=<dir>` | Where browser tests save screenshots |
| `KIT=<dir>` | Install from another checkout |
| `PIPELINE=staged` | Use the staged pipeline (the default for real installs). The older suites were written for the one-pass pipeline and run without it |
| `SMALL_NIGHT_KB=0` | Always run the full staged pipeline, even for one small session |

| File | Covers |
|---|---|
| `test_e2e.py` | A full first-use journey through the page, checked against disk, git and the hook |
| `test_pipeline.py` | The staged pipeline: recon, hunters per class, every mechanical check, the disprove step, the fresh check, accepting questions, the plain-language review. Run with `PIPELINE=staged SMALL_NIGHT_KB=0 PRESCAN=1` |
| `test_scopes.py` | Repos, clients, scoped runs per client, guardrails, inbox merge, hook |
| `test_runs_and_store.py` | Instructions, models, chosen sessions, cancel, live events, limits, versions, redact, read-only memory |
| `test_subagents_confidence.py` | AGENTS.md, subagent folding, SubagentStart hook, parallel runs, confidence |
| `test_settings.py` | Start here guide, help, settings, schedule tick, model list and check |
| `test_reading_budget.py` | Session sizes, reading budget, trimming order |
| `test_dates.py` | Dates, outdated evidence, routing of held changes, incremental reading |
| `test_auto_adopt.py` | Adopt when safe, undo, questions, expiry, summary, freshness check |
| `test_answers.py` | Answer buttons on questions, moving a repo between clients |
| `test_save_fix.py` | Memory page shows a cycle's update and keeps your edit on a conflict |
| `test_ui_review.py`, `test_ui_motion.py` | Browser checks of the run sheet, dock, review page and motion. The motion checks are timing based and can flake on a busy machine; re-run before digging in |
