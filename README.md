<p align="center"><img src="docs/brand/somna-banner.png" alt="Somna, memory that rests overnight" width="100%"></p>

# Somna

**Memory that rests overnight.** Somna gives Claude Code a curated memory on your Mac and keeps it
up to date while you sleep.

- Every Claude Code session starts with your general memory and, inside a mapped repo, that repo's
  context and its client's context. A session-start hook injects them, so nothing is added to the
  repos themselves.
- While working, agents append one-line updates to the repo's inbox.
- Every night a **cycle** reads the day's sessions and git activity, one client at a time, and
  proposes an updated memory. When nothing looks wrong it saves the change by itself; anything
  uncertain waits for you in a local review page.

Everything runs on your Mac: plain Markdown files in a git repo, a small Python script, launchd and
the Claude Code CLI you already use. No servers, no accounts, no extra services.

<p align="center"><img src="docs/somna-demo.gif" alt="Somna review page: running a cycle, live progress, answering a question and seeing what was saved" width="100%"></p>

> Somna is an independent open-source project. It is not affiliated with or endorsed by Anthropic.
> Claude and Claude Code are trademarks of Anthropic.

## Contents

- [Install](#install)
- [Make it yours](#make-it-yours)
- [The daily routine](#the-daily-routine)
- [Running a cycle by hand](#running-a-cycle-by-hand)
- [How a cycle works](#how-a-cycle-works)
- [Isolation and safety](#isolation-and-safety)
- [Settings](#settings)
- [Commands](#commands)
- [Logs and troubleshooting](#logs-and-troubleshooting)
- [Development](#development)
- [Uninstall](#uninstall)

## Install

Requirements: macOS, git and Python 3.9 or newer (both come with `xcode-select --install`), and
[Claude Code](https://docs.claude.com/en/docs/claude-code/overview) installed and signed in once.
`ripgrep` is optional.

```bash
git clone https://github.com/mohramadan911/somna.git
cd somna
./install.sh --ui-at-login      # nightly cycle at 02:00 + review page always on
somna doctor                    # "ok" everywhere; ".." lines are hints, "!!" needs fixing
```

Installer options:

| Option | What it does |
|---|---|
| `--hour 6 --minute 30` | Another nightly time (you can change it later in Settings) |
| `--no-schedule` | Run cycles only by hand |
| `--ui-at-login` | Keep the review page running at `http://127.0.0.1:4747` |
| `--agents-can-edit-memory` | Turn off the read-only rules for agents (see below) |

If the installer says `~/.local/bin` is not on your PATH, add
`export PATH="$HOME/.local/bin:$PATH"` to `~/.zshrc`. Re-running the installer is safe: it updates
the tooling and keeps your memory.

What the installer sets up:

| Where | What |
|---|---|
| `~/somna/` | Your memory repo (git). Starts with example files you replace |
| `~/.local/bin/somna` | The `somna` command |
| `~/.claude/CLAUDE.md` | A short block that imports `~/somna/memory/index.md` (a backup is kept) |
| `~/.claude/settings.json` | The context hooks, note permissions and read-only rules (a backup is kept) |
| `~/Library/LaunchAgents/com.somna.tick.plist` | Checks every 10 minutes whether a cycle is due |
| `~/Library/LaunchAgents/com.somna.ui.plist` | The review page, with `--ui-at-login` |

## Make it yours

Open `http://127.0.0.1:4747` (or run `somna ui`). The first time, the page opens on **Start here**:
nine steps with a tick for each one that is done. Every **?** explains what a button does, how long
it takes and what it changes.

1. **Memory:** replace the example files in `memory/me/`, `memory/work/` and
   `engine/steering.md`. Every file that ships with Somna is an example.
2. **Repos > Add client:** one per client or project group, with markers: words that identify it in
   folder names or git remotes (for example `acme, acme-corp`). Markers drive suggestions and
   ownership checks. Working on your own projects only? One client, or none, is fine.
3. **Work as usual.** Start each Claude Code session inside its repo (`cd ~/code/acme-shop && claude`).
4. **Map your repos.** Every git repo you worked in shows up under **Repos** after a cycle reads its
   sessions, or right away with **Scan past sessions**. Pick the client, **Confirm**, then **Map**:
   a read-only pass reads the repo once (README.md, CLAUDE.md, AGENTS.md and other key files) and
   proposes its context file. Adopt it, and from the next session the context is injected.

## The daily routine

By default a cycle **saves its changes by itself when nothing looks wrong** (Settings > Review mode:
"Adopt automatically when safe"). Safe means all of these hold:

- every applied change is medium or high confidence
- Claude wrote nothing outside its folders
- every changed file has a recorded reason
- no part of the run failed
- you did not edit the same memory while it ran

In the morning you get one line, in a notification and at the top of the page, for example
"Saved automatically: 7 changes in shop, infra. 1 question for you."

1. **Questions:** Accept (the button says where the change goes) or Dismiss. Unanswered questions
   expire after 7 days.
2. If a cycle waits for you, **Review it**: decisions, report and diff, then Adopt or Discard.
3. Do not like something that was saved? **Undo** puts memory back as it was (a git revert,
   history kept). The next cycle reads those sessions again.

Prefer to approve everything yourself? Set Review mode to "Ask me for everything".

## Running a cycle by hand

**Run cycle now** opens a small form:

- **Instructions for this cycle** (optional, up to 4,096 characters): what to focus on, what to
  keep, how to write. For this run only; standing rules live in `engine/steering.md`.
- **Model:** Claude Code's default or one from your provider's list.
- **Sessions to read:** new since the last cycle, or 1 to 100 sessions picked from a list. A session
  is one `claude` you started; its subagents are read as part of it.

From the terminal:

```bash
somna sessions                                   # recent sessions with their ids
somna create --sessions a1b2,c3d4 --model sonnet \
             --instructions "Focus on the checkout work. Keep the decision list as it is."
```

Runs happen in the background. A panel shows live progress: the step, which client is being
curated, Claude's event stream with the files it reads and writes, and tokens so far.
**Cancel run** stops it and deletes the partial output.

## How a cycle works

A cycle reads your current memory and your recent sessions, and writes an updated copy of memory on
a git branch (`cycle/<id>`). Your current memory is not touched until you adopt the copy; discard
it and nothing changes.

Each client goes through six stages, so nothing grades its own work:

| Stage | Who | What it does |
|---|---|---|
| **Recon** | code | Writes down what you did: each session's day, repo, your first message and the files it changed, plus the commits. Hunters read this first; the Review page shows it as "What you did". |
| **Hunt** | read-only Claude runs, one per kind | Separate searches for stale or contradicted facts, new facts, your corrections and preferences, and tidying (filing inbox notes, duplicates). They report findings as JSON with exact quotes; they never edit. A search with nothing to look at is skipped. |
| **Check** | code | Every finding's format, that the text it changes is really in the file, every quote word for word in the session, commit or file it names, and every file, line and function it names in the repo. Anything that fails is dropped with the reason. |
| **Disprove** | a read-only Claude run | Tries to break each finding: newer evidence, a quote that does not say what the summary claims, something memory already has, another client's fact. A refutation must quote its own source, or the finding becomes a question. |
| **Fresh check** | a new Claude run | Sees only the proposed change and its sources, not the summaries or the reasoning, and confirms or rejects it. |
| **Apply** | code | Applies what survived, adds "(as of date)" to context lines, and writes the report. Low confidence, a "not sure" from either check, or a change for another part of memory becomes a question. |

On a light night (1 or 2 small sessions in a client) one combined search replaces the separate ones
and the disprove step is skipped; the checks and the fresh check still run. Hunters, checks and the
fresh check only read, so a client's sessions never cause an edit outside the code-driven apply step.

Cost: the full pipeline is several Claude runs per client instead of one. Set a cheaper **model for
the checks** in Settings (they only read and compare), or switch **Pipeline** to "One pass" for a
single run per client that edits memory directly, without the independent checks.

**Reading the result.** Each change says in plain words what it does and why, where it goes ("the
shop context", "your notes on terraform"), and the moments behind it: the day, the repo and what you
asked. Ticks show which checks it passed. Ids and file paths are under Details. "Checked and dropped"
lists what did not survive and why. Accepting a question saves it straight to memory when nothing
else is waiting.

**Dates.** Every input carries its time. Lines in a context file end with "(as of YYYY-MM-DD)".
A newer line is never replaced by an older session or commit. Outdated evidence is dropped only
when Somna can prove it (every session behind it was already curated, and it is older than the
file's last update); dropped items stay visible on the Review page. "Current state" items older
than 45 days are removed unless newer evidence confirms them.

**Reading budget.** Each client run reads up to 400 KB of session text (about 100k tokens), and one
session at most 250 KB. Small sessions are read in full first. A session that does not fit is
shortened in order of value: long tool output first, your messages and Claude's answers last. The
full text stays on disk, and Claude is told where, so it can open what it needs. Resumed sessions
are read incrementally.

**Every session checks the context against the code.** At session start the hook compares the
context with the repo, without calling Claude: commits since the last update, the branch, and paths
named in the context that no longer exist. Claude is told to verify before relying on a fact, and to
add a `CORRECTION:` line to the inbox when the context is wrong. The next cycle applies it first.

**Versions and redact.** Every memory file has its history in git. **Memory > Versions** lists
them; **Redact** scrubs an old version's content from the whole history (adopt or discard waiting
proposals first, and force-push if you push the memory repo anywhere).

## Ask Somna

**Ask Somna** in the header opens a chat about your memory, your cycles and your settings:

- "What do you know about shop?", "Why is this a question?", "What changed this week?", "Why did last night
  cost $1.40?", "What does a session in shop get at start?"
- "Make nights cheaper", "The shop context still says Jenkins, we use GitHub Actions now", "From now on, always
  keep the decision list", "Run a cycle on today's sessions".

When it suggests a change you get a card with a button: settings show the old and new value, memory changes
show the exact lines, a run shows what it will read. Nothing happens until you click.

- **It reads what code gives it.** Your general notes always; a client's files only when your question or the
  item you have open is about that client. It has no file tools and cannot open anything else.
- **Its suggestions are checked.** Settings go through the same validation as the Settings page. A memory change
  goes through the same checks as a cycle's findings (the text exists, no duplicate, right place) and is saved
  under the memory lock, or queued for the next cycle when a proposal is waiting.
- **It stays on your Mac.** The conversation is in `~/somna/chat/history.jsonl`, never committed; **Clear**
  deletes it. Each question is one Claude Code call, on Haiku by default (Settings > Ask Somna and security audits).

"Ask about this" on every change, question, repo and audit opens the chat about that item. From the terminal:
`somna ask "what do you know about shop?"` (answers only; suggestions need the page).

## Security audit

**Repos > Run security audit** (or `somna audit <repo>`) audits one repo in the same staged way a cycle works:

| Stage | What happens |
|---|---|
| Recon | Code collects repo facts and Somna's context for the repo; a read-only run maps the attack surface (`architecture.md`) and picks the attack classes worth hunting |
| Hunt | One read-only run per attack class (HTTP and auth, cloud, supply chain, data isolation, AI and LLM features, and more) reports findings with exact code quotes |
| Check | Code checks every path is inside the repo, every line number is in range, every quote is at its line and every function is near it. The same place found twice is merged |
| Disprove | A run tries to break each finding; a refutation must quote the code that breaks it |
| Fresh check | A new run sees only the locations and the conditions, not the reasoning, severity or confidence, and confirms or rejects |
| Report | Code writes `report.md` and `findings.json`: confirmed, needs validation, rejected with the reason |

Nothing is executed and nothing in the repo or in memory changes. **Save to memory** adds confirmed findings to
the repo's context under "Security findings", so every later Claude Code session in that repo knows about them;
the nightly cycle only removes one when a commit or session shows it was fixed. Each audit is several Claude
runs, each capped by the audit spend limit in Settings. Only audit code you are allowed to test.

The `security-audit` skill lets you start it from inside Claude Code ("security audit this repo"). Somna's
audit follows the design Cloudflare described in
[Build your own vulnerability harness](https://blog.cloudflare.com/build-your-own-vulnerability-harness); it is
an independent implementation, read-only by design, without their sandboxed proof-of-concept runs.

## Isolation and safety

| Piece | Where | Who writes it |
|---|---|---|
| General memory | `memory/me/`, `memory/work/`, `memory/index.md` | the cycle (general run), you |
| Client context | `memory/clients/<client>/context.md` | that client's run, you |
| Repo context | `memory/clients/<client>/repos/<repo>.md` | Map, then the cycle, you |
| Repo inbox | `memory/inbox/<client>/<repo>.md` | agents during work |
| General notes | `memory/scratch/notes.md` | agents during work |
| Repo and client registry | `engine/repos.json` | Repos tab or `somna assign` |

- **One run per client.** Each client run sees only that client's sessions and may only write that
  client's folder and inbox. Runs go in parallel (3 at a time by default), each in its own git
  worktree. A general run handles everything else and may not touch client folders. Anything
  written outside the allowed scope is reverted and logged.
- **Memory is read-only for agents.** The installer adds deny rules so agents can read memory but
  only write the inbox and scratch notes. This protects memory from instructions hidden in a repo
  or web page. The rules cover Claude's file tools; a shell command could still write a file, so the
  review stays your safety net.
- **Repos stay clean.** Context is injected by a hook, so no files are added to your repos. Map runs
  with read, list and search tools only, and checks that the working tree did not change.
- **Ownership checks.** For each repo Somna compares the path and git remote with every client's
  markers and asks you when something does not fit.
- **Client data stays local.** A pre-push hook in `~/somna` blocks pushing `memory/clients/` and
  `memory/inbox/`. The review page listens on 127.0.0.1 only and needs a per-start token.
- **No self-learning loop.** A cycle's own Claude Code run is not saved as a session.

## Settings

Everything can be changed in the **Settings** page. Saving writes `engine/config.json` and commits
it, so every change can be undone.

**Schedule.** One launchd job checks every 10 minutes and starts what is due: the nightly cycle on
the days and time you pick (if the Mac was asleep, within 12 hours after waking), and an optional
weekly cycle with its own model, window and instructions.

**Models.** One for nightly and manual cycles, one for the weekly cycle, one for Map. The list
comes from whatever Claude Code on this Mac uses: the Models API with an `ANTHROPIC_API_KEY`, your
inference profiles on Amazon Bedrock (`CLAUDE_CODE_USE_BEDROCK=1`), or a built-in list with a
Claude account sign-in. **Check** runs a one-line test through your Claude Code.

| Key in config.json | Default | Meaning |
|---|---|---|
| `schedule.nightly` | on, 02:00, every day | Nightly cycle |
| `schedule.weekly` | off, Sunday 03:00, 7 days | Weekly cycle with its own `model` and `instructions` |
| `review_mode` | `auto` | `auto` = adopt when safe, `manual` = every cycle waits for you |
| `model` / `map_model` | `""` | Empty = Claude Code default |
| `max_budget_usd` / `map_max_budget_usd` | `null` | Spend cap per engine run, for example `1.0` |
| `max_turns` | `null` | Turn limit per engine run |
| `timeout_minutes` | `30` | Per engine run |
| `run_digest_budget_kb` | `400` | Session text one client run reads |
| `session_max_kb` | `250` | The most one session can take of that budget |
| `max_sessions` | `100` | Sessions per cycle, newest first |
| `parallel_runs` | `3` | Client runs at the same time |
| `per_client_runs` | `true` | `false` = one run for everything (no client contexts) |
| `hold_low_confidence` | `true` | Hold low-confidence changes as questions |
| `held_expiry_days` | `7` | Unanswered questions are dismissed after this many days |
| `stale_after_days` | `45` | Age at which "Current state" items are removed unless confirmed |
| `context_max_chars` | `7000` | Target size of a repo context |
| `remap_after_commits` | `40` | Suggest Re-map after this many commits |
| `stream_events` | `true` | Live event stream from Claude Code |
| `pipeline` | `staged` | `staged` = recon, hunt, check, disprove, fresh check, apply. `single` = one run per client |
| `hunters` | all four | Kinds of change searched for separately: `stale`, `new`, `corrections`, `tidy` |
| `hunt_model` / `check_model` | `""` | Models for the searches and for the checks. Empty = the cycle model |
| `small_night_kb` | `40` | At or below this much session text (1 or 2 sessions), one combined search and no disprove step |
| `max_engines` | `4` | Claude runs at the same time across all clients |
| `chat_model` | `haiku` | Model for Ask Somna |
| `audit_model` / `audit_check_model` | `""` | Models for audit searches and for the audit checks. Empty = the cycle model |
| `audit_max_budget_usd` | `3.0` | Spend cap per Claude run in an audit |
| `audit_max_classes` | `6` | Attack classes per audit |
| `ui_port` | `4747` | Review page port |

Cost: each client with sessions that day is one engine run. Cost and turns per run are shown in the
cycle record and the logs. A cheaper model and a spend cap keep nights cheap.

## Commands

```text
somna ui [--port 4747] [--no-open]           review page
somna create [--since-last | --since-hours N | --sessions id,id] [--instructions "..."] [--model M] [--dry-run]
somna sessions [--days 14]                   recent sessions and their ids
somna cancel <id>                            stop a running cycle or map
somna list [--limit N] [--include-archived]
somna review <id> | adopt <id> [--force] | discard <id>
somna try <id> [repo] [--open]               a session that uses a proposal before adopting it
somna decisions <id> | accept <id> <n> | dismiss <id> <n>
somna summary | questions | undo <id>        what was saved, what waits, put a save back
somna versions <file> | redact <file> <version>
somna schedule [--nightly on|off] [--nightly-time HH:MM] [--weekly on|off] [--weekly-day 0-6] [--weekly-time HH:MM]
somna models [--refresh] [--check <id>]      models from your provider, or test one
somna instructions <repo or client> ["text" | --clear]
somna repos                                  repos, clients and open questions
somna client <id> --name "<Name>" --markers "a,b"
somna assign <repo path or name> <client> [--name short-name] | --ignore
somna map <repo path or name>                read-only pass, proposes the context file
somna logs [--level warn] [--event hook] [--cycle <id>] [-f] [-v]
somna doctor
somna ask "<question>"                       Ask Somna from the terminal (answers only)
somna audit <repo path or name> [--classes http-auth,cloud]   security audit, read-only
```

## Logs and troubleshooting

- `~/somna/logs/somna.log` (readable) and `somna.jsonl` (structured), rotated at 5 MB.
- `~/somna/cycles/<id>/run.log` for every step of one cycle, and `engine.log` for Claude Code's raw
  output. The **Logs** tab has the same filters.

| Symptom | Fix |
|---|---|
| Context not injected in a repo | **Repos**: is it Confirmed and Mapped? `somna logs --event hook` shows what the hook did. |
| A repo is missing under Repos | Only git repos are listed. Sessions elsewhere feed general memory. |
| A cycle failed | **Review** shows the engine log. Often the Claude Code sign-in: run `claude` once. |
| Nothing ran overnight | If the Mac was asleep, it runs within 12 hours after waking. Health shows the next run; `~/somna/logs/schedule.log` has the scheduler's output. |
| A model check fails | The id is wrong for your setup (on Bedrock use the inference profile ARN) or you have no access to it. |
| Claude says it cannot edit a memory file | By design. Edit it in the page, or re-run `install.sh --agents-can-edit-memory`. |
| `somna: command not found` | Add `~/.local/bin` to your PATH. |
| Page not reachable | Run `somna ui`, or check `~/somna/logs/ui.log`. |

Claude Code's flags and transcript format can change between releases. Somna falls back to raw text
when the transcript format changes and logs every failure with its cause.

## Development

The tests run against a throwaway home folder with a stand-in for the Claude Code CLI
(`tests/mock_claude`), so they never call Claude. Browser tests need Playwright with Chromium.

```bash
MOCK_STEP_DELAY=1 tests/run.sh /tmp/somna-test 4800 test_e2e.py
```

`tests/run.sh <workdir> <port> <test file>` installs Somna into `<workdir>/home`, starts the page on
`<port>` and runs the test. Every client, repo and session in the tests is fictional. See
[tests/README.md](tests/README.md) for the options and what each suite covers.

## Coming from agent-memory-kit

If you ran the earlier version of this tool (the `dream` command in `~/agent-memory`), adopt or
discard anything waiting there, then:

```bash
scripts/migrate-from-agent-memory.sh --ui-at-login
```

It stops the old jobs and hooks, copies your memory with its full git history to `~/somna`, carries
over your settings, repos, clients and which sessions were already read, and installs Somna on top.
The old folder stays as a backup.

## Uninstall

`./uninstall.sh` removes the schedules, the command, the skill links, the CLAUDE.md block and
Somna's entries in `~/.claude/settings.json`. Your memory in `~/somna` stays; delete it yourself if
you want it gone.

## License

[MIT](LICENSE)
