#!/usr/bin/env bash
# Move an older agent-memory-kit install (the `dream` command, ~/agent-memory) to Somna (~/somna).
# Your memory, its git history, your settings, repos and clients come along. The old folder is left
# in place as a backup; delete it yourself once you are happy.
# Usage: scripts/migrate-from-agent-memory.sh [--from ~/agent-memory] [--to ~/somna] [installer options, like --ui-at-login]
set -euo pipefail

KIT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FROM="${AGENT_MEMORY_HOME:-$HOME/agent-memory}"
TO="${SOMNA_HOME:-$HOME/somna}"
PASS=()
need() { [ $# -ge 2 ] && [ -n "$2" ] || { echo "$1 needs a value"; exit 1; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --from) need "$@"; FROM="$2"; shift 2;;
    --to) need "$@"; TO="$2"; shift 2;;
    --hour|--minute) need "$@"; PASS+=("$1" "$2"); shift 2;;
    --ui-at-login|--no-schedule|--agents-can-edit-memory|--force-non-mac) PASS+=("$1"); shift;;
    *) echo "unknown option: $1"; exit 1;;
  esac
done
ok()   { printf "  \033[32mok\033[0m   %s\n" "$1"; }
step() { printf "\n\033[1m%s\033[0m\n" "$1"; }
die()  { printf "  \033[31m!!\033[0m   %s\n" "$1"; exit 1; }

step "1. Checking"
[ -d "$FROM/.git" ] || die "no agent-memory repo at $FROM (use --from <path>)"
FROM="$(cd "$FROM" && pwd)"
TO_PARENT="$(dirname "$TO")"
[ -d "$TO_PARENT" ] || die "the folder $TO_PARENT does not exist. Create it first, or pick another place with --to"
TO="$(cd "$TO_PARENT" && pwd)/$(basename "$TO")"
[ -e "$TO" ] && die "$TO already exists. Move it away first, or pick another place with --to"
case "$TO/" in "$FROM"/*) die "--to must not be inside $FROM";; esac
case "$TO/" in "$KIT_DIR"/*) die "--to must not be inside the Somna download ($KIT_DIR)";; esac
# a dream/* branch only matters when its run still waits for review; failed, canceled or crashed runs can
# leave branches behind, and those are cleaned up in the copy
WAITING="$(python3 -c '
import json, os, subprocess, sys
home = sys.argv[1]
refs = subprocess.run(["git", "-C", home, "branch", "--list", "dream/*", "--format=%(refname:short)"],
                      capture_output=True, text=True).stdout.split()
for b in refs:
    did = b.split("/", 1)[1]
    try:
        rec = json.load(open(os.path.join(home, "dreams", did, "dream.json")))
    except (OSError, ValueError):
        continue
    if rec.get("status") == "completed" and rec.get("outputs") and not rec.get("review") and not rec.get("archived_at"):
        print(did)
' "$FROM")"
if [ -n "$WAITING" ]; then
  die "a proposal is still waiting in the old tool: $(echo $WAITING). Adopt or discard it there first (dream ui), then run this again"
fi
if [ -n "$(git -C "$FROM" status --porcelain -- memory)" ]; then
  die "the old memory has unsaved edits. Commit or discard them first (cd $FROM && git status)"
fi
ok "old memory at $FROM, nothing waiting; new home will be $TO"

# copy first: if anything below fails, the old tool still works exactly as before
step "2. Copying your memory to $TO"
cp -R "$FROM" "$TO"
cd "$TO"
rm -rf .dream-worktrees bin/dream
git worktree prune 2>/dev/null || true
for b in $(git branch --list 'dream/*' --format='%(refname:short)'); do git branch -D "$b" >/dev/null 2>&1 || true; done
mkdir -p engine cycles
for f in config.json repos.json steering.md; do
  if [ -f "dreaming/$f" ]; then mv "dreaming/$f" "engine/$f"; fi
done
rm -rf dreaming
# old run records keep their old format; they stay readable in cycles-legacy/ but are not shown in the page
if [ -d dreams ]; then
  if [ -f dreams/state.json ]; then cp dreams/state.json cycles/state.json; fi
  mv dreams cycles-legacy
fi
python3 - engine/config.json << 'PY'
import json, sys
p = sys.argv[1]
try:
    c = json.load(open(p))
except (OSError, ValueError):
    c = {}
if not isinstance(c, dict):
    c = {}
pats = c.get("exclude_project_patterns") if isinstance(c.get("exclude_project_patterns"), list) else []
c["exclude_project_patterns"] = [str(x).replace("dream-worktrees", "somna-worktrees") for x in pats] or ["somna-worktrees"]
json.dump(c, open(p, "w"), indent=2)
PY
python3 - .gitignore << 'PY'
import sys
p = sys.argv[1]
try:
    lines = open(p).read().splitlines()
except OSError:
    lines = []
lines = [l for l in lines if l.strip() not in (".dream-worktrees/", "dreams/")]
for want in (".somna-worktrees/", "cycles/", "cycles-legacy/", "logs/"):
    if want not in lines:
        lines.append(want)
open(p, "w").write("\n".join(lines) + "\n")
PY
git add -A
git commit -qm "migrate from agent-memory-kit to Somna" || true
ok "memory copied with its full history"

step "3. Stopping the old tool"
STAMP="$(date +%Y%m%d%H%M%S)"
for f in "$HOME/.claude/CLAUDE.md" "$HOME/.claude/settings.json"; do
  if [ -f "$f" ]; then cp "$f" "$f.bak.$STAMP"; ok "backed up $(basename "$f") to $(basename "$f").bak.$STAMP"; fi
done
if [ "$(uname -s)" = "Darwin" ]; then
  for label in com.agentmemory.dream com.agentmemory.dream-ui; do
    plist="$HOME/Library/LaunchAgents/$label.plist"
    if [ -f "$plist" ]; then launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true; rm -f "$plist"; ok "stopped $label"; fi
  done
fi
if [ -L "$HOME/.local/bin/dream" ]; then rm -f "$HOME/.local/bin/dream"; ok "removed the dream command"; fi
for l in "$HOME"/.claude/skills/*; do
  if [ -L "$l" ]; then
    case "$(readlink "$l")" in "$FROM"/*) rm "$l"; ok "unlinked old skill $(basename "$l")";; esac
  fi
done
python3 - "$HOME/.claude/CLAUDE.md" "$HOME/.claude/settings.json" "$FROM" << 'PY'
import json, os, re, sys
md, st, old = sys.argv[1:4]
if os.path.exists(md):
    t = open(md).read()
    n = re.sub(r"\n*<!-- agent-memory:begin -->.*?<!-- agent-memory:end -->\n?", "\n", t, flags=re.S)
    if n != t:
        open(md, "w").write(n.strip() + "\n" if n.strip() else "")
        print("  \033[32mok\033[0m   removed the old block from ~/.claude/CLAUDE.md")
mine = re.compile(re.escape(old) + r"(?=[/\")*]|$)")
if os.path.exists(st) and os.path.getsize(st):
    try:
        c = json.load(open(st))
    except ValueError:
        print("  !!   ~/.claude/settings.json is not valid JSON, left as it is; remove the old dream hooks by hand")
        sys.exit(0)
    if isinstance(c, dict):
        h = c.get("hooks")
        if isinstance(h, dict):
            for ev in list(h):
                if isinstance(h[ev], list):
                    h[ev] = [e for e in h[ev] if not (isinstance(e, dict) and any(isinstance(x, dict) and "/bin/dream" in str(x.get("command", ""))
                                                                                 for x in (e.get("hooks") or [])))]
                    if not h[ev]:
                        del h[ev]
            if not h:
                del c["hooks"]
        pm = c.get("permissions")
        if isinstance(pm, dict):
            for k in ("allow", "deny", "additionalDirectories"):
                if isinstance(pm.get(k), list):
                    pm[k] = [r for r in pm[k] if not mine.search(str(r))]
                    if not pm[k]:
                        del pm[k]
        json.dump(c, open(st, "w"), indent=2)
        print("  \033[32mok\033[0m   removed the old hooks and rules from ~/.claude/settings.json")
PY

step "4. Installing Somna on top"
cd "$KIT_DIR"
SOMNA_HOME="$TO" ./install.sh ${PASS[@]+"${PASS[@]}"}
step "Done"
echo "  Your memory now lives in $TO and the old folder $FROM is untouched as a backup."
echo "  Check:  somna doctor     then open the page with: somna ui"
