# Changelog

## 1.1.0 (2026-10-24)

A cycle now works in stages, so nothing grades its own work, and the review page reads like your week.

- **Staged pipeline** (the new default, `"pipeline": "staged"`):
  - Recon: code writes an activity brief per client before Claude is asked anything: each session's day, repo,
    your first message and the files it changed, plus the commits.
  - Hunt: separate read-only searches per kind of change (stale facts, new facts, your corrections, tidying).
    They report findings; they never edit. Searches with nothing to look at are skipped, and a light night
    (1 or 2 small sessions) uses one combined search.
  - Check: code checks every finding's format, that the text it changes is really there, every quote word for
    word against your sessions, commits and files, and every file, line and function it names in the repo.
  - Disprove: a read-only run tries to break each finding. A refutation has to quote its own source.
  - Fresh check: an agent that never saw the reasoning re-checks the change against the raw sources.
  - Apply: code applies what survived. Doubtful findings become questions; the rest are dropped with the reason.
- **Readable review:** "What you did" per client, each change in plain words with where it goes, the day, repo
  and what you asked as its evidence, ticks for each check passed, and ids moved behind Details. Changes are
  grouped by day. "Checked and dropped" lists what did not survive and why.
- **Accepting a question saves it straight to memory** when nothing else is waiting, instead of queuing it for
  the next cycle. Fixes a loop where a general line meant for a client's inbox came back as a question every night.
- Settings: pipeline, a model for finding changes, a (cheaper) model for the checks, the light-night threshold,
  and how many Claude runs go at once.
- `scripts/migrate-from-agent-memory.sh` moves an older agent-memory-kit install to Somna with its history.

## 1.0.0 (2026-10-17)

First public release.

- Nightly and weekly cycles that curate your Markdown memory from your Claude Code sessions,
  one isolated run per client, with a review page on 127.0.0.1.
- Repo and client context injected at session start and subagent start, with a freshness check
  against the code and a correction loop.
- Decisions with confidence and evidence dates; low-confidence changes become questions.
- Adopt automatically when safe, with a morning summary and Undo.
- Reading budget for long sessions, incremental reading of resumed sessions.
- Settings page for schedule, models, limits and review mode; model list from your provider.
- Read-only memory for agents, scope guardrails, versions and redact, pre-push hook that keeps
  client folders local.
