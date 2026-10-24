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
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2;;
    --to) TO="$2"; shift 2;;
    --hour|--minute) PASS+=("$1" "$2"); shift 2;;
    --ui-at-login|--no-schedule|--agents-can-edit-memory|--force-non-mac) PASS+=("$1"); shift;;
    *) echo "unknown option: $1"; exit 1;;
  esac
done
ok()   { printf "  \033[32mok\033[0m   %s\n" "$1"; }
step() { printf "\n\033[1m%s\033[0m\n" "$1"; }
die()  { printf "  \033[31m!!\033[0m   %s\n" "$1"; exit 1; }

step "1. Checking"
[ -d "$FROM/.git" ] || die "no agent-memory repo at $FROM (use --from <path>)"
[ -e "$TO" ] && die "$TO already exists. Move it away first, or pick another place with --to"
if git -C "$FROM" branch --list 'dream/*' | grep -q .; then
  die "a proposal is still waiting in the old tool. Adopt or discard it there first (dream ui), then run this again"
fi
if [ -n "$(git -C "$FROM" status --porcelain -- memory)" ]; then
  die "the old memory has unsaved edits. Commit or discard them first (cd $FROM && git status)"
fi
ok "old memory at $FROM, nothing waiting"

step "2. Stopping the old tool"
if [ "$(uname -s)" = "Darwin" ]; then
  for label in com.agentmemory.dream com.agentmemory.dream-ui; do
    plist="$HOME/Library/LaunchAgents/$label.plist"
    if [ -f "$plist" ]; then launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true; rm -f "$plist"; ok "stopped $label"; fi
  done
fi
[ -L "$HOME/.local/bin/dream" ] && rm -f "$HOME/.local/bin/dream" && ok "removed the dream command"
for l in "$HOME"/.claude/skills/*; do
  [ -L "$l" ] && case "$(readlink "$l")" in "$FROM"/*) rm "$l"; ok "unlinked old skill $(basename "$l")";; esac
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
if os.path.exists(st) and os.path.getsize(st):
    c = json.load(open(st))
    h = c.get("hooks", {})
    for ev in list(h):
        h[ev] = [e for e in h[ev] if not any("/bin/dream" in x.get("command", "") for x in e.get("hooks", []))]
        if not h[ev]:
            del h[ev]
    if "hooks" in c and not c["hooks"]:
        del c["hooks"]
    pm = c.get("permissions", {})
    for k in ("allow", "deny", "additionalDirectories"):
        if k in pm:
            pm[k] = [r for r in pm[k] if old not in r]
            if not pm[k]:
                del pm[k]
    json.dump(c, open(st, "w"), indent=2)
    print("  \033[32mok\033[0m   removed the old hooks and rules from ~/.claude/settings.json")
PY

step "3. Copying your memory to $TO"
cp -R "$FROM" "$TO"
cd "$TO"
git worktree prune 2>/dev/null || true
rm -rf .dream-worktrees bin/dream
mkdir -p engine cycles
for f in config.json repos.json steering.md; do
  if [ -f "dreaming/$f" ]; then mv "dreaming/$f" "engine/$f"; fi
done
rm -rf dreaming
# old run records keep their old format; they stay readable in cycles-legacy/ but are not shown in the page
if [ -d dreams ]; then
  [ -f dreams/state.json ] && cp dreams/state.json cycles/state.json
  mv dreams cycles-legacy
fi
python3 - engine/config.json << 'PY'
import json, sys
p = sys.argv[1]
try:
    c = json.load(open(p))
except (OSError, ValueError):
    c = {}
pats = [x.replace("dream-worktrees", "somna-worktrees") for x in c.get("exclude_project_patterns", [])] or ["somna-worktrees"]
c["exclude_project_patterns"] = pats
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
git commit -qm "migrate from agent-memory-kit to Somna" && ok "memory copied with its full history"

step "4. Installing Somna on top"
cd "$KIT_DIR"
SOMNA_HOME="$TO" ./install.sh ${PASS[@]+"${PASS[@]}"}
step "Done"
echo "  Your memory now lives in $TO and the old folder $FROM is untouched as a backup."
echo "  Check:  somna doctor     then open the page with: somna ui"
