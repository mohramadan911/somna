#!/usr/bin/env bash
# Somna: agent memory with nightly cycles for macOS. Safe to re-run.
# Usage: ./install.sh [--hour 2] [--minute 0] [--no-schedule] [--ui-at-login] [--agents-can-edit-memory] [--force-non-mac]
set -euo pipefail

KIT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEMORY_HOME="${SOMNA_HOME:-$HOME/somna}"
CLAUDE_DIR="$HOME/.claude"
BIN_DIR="$HOME/.local/bin"
LABEL="com.somna.tick"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
HOUR=2; MINUTE=0; TIME_SET=0; SCHEDULE=1; FORCE=0; UI_LOGIN=0; ACCESS=read_only
UI_LABEL="com.somna.ui"
UI_PLIST="$HOME/Library/LaunchAgents/$UI_LABEL.plist"

while [ $# -gt 0 ]; do
  case "$1" in
    --hour) HOUR="$2"; TIME_SET=1; shift 2;;
    --minute) MINUTE="$2"; TIME_SET=1; shift 2;;
    --no-schedule) SCHEDULE=0; shift;;
    --ui-at-login) UI_LOGIN=1; shift;;
    --agents-can-edit-memory) ACCESS=read_write; shift;;
    --force-non-mac) FORCE=1; shift;;
    *) echo "unknown option: $1"; exit 1;;
  esac
done

KIT_VERSION="$(grep -m1 '^VERSION = ' "$KIT_DIR/template/bin/somna" | cut -d'"' -f2)"
printf "\n\033[1mInstalling Somna %s from %s\033[0m\n" "$KIT_VERSION" "$KIT_DIR"
ok()   { printf "  \033[32mok\033[0m   %s\n" "$1"; }
warn() { printf "  \033[33m!!\033[0m   %s\n" "$1"; }
step() { printf "\n\033[1m%s\033[0m\n" "$1"; }

step "1. Checking this Mac"
if [ "$(uname -s)" != "Darwin" ] && [ "$FORCE" -ne 1 ]; then
  echo "This installer is for macOS. (Use --force-non-mac for testing.)"; exit 1
fi
command -v git >/dev/null || { echo "git missing. Run: xcode-select --install"; exit 1; }; ok "git"
command -v python3 >/dev/null || { echo "python3 missing. Run: xcode-select --install"; exit 1; }; ok "python3"
CLAUDE_BIN="$(command -v claude || true)"
for c in "$HOME/.local/bin/claude" "$HOME/.claude/local/claude" /opt/homebrew/bin/claude /usr/local/bin/claude; do
  [ -z "$CLAUDE_BIN" ] && [ -x "$c" ] && CLAUDE_BIN="$c"
done
if [ -n "$CLAUDE_BIN" ]; then ok "Claude Code CLI: $CLAUDE_BIN"; else warn "Claude Code CLI not found. Install it, sign in once, then re-run this script."; fi
command -v rg >/dev/null && ok "ripgrep" || warn "ripgrep not found (optional): brew install ripgrep"

step "2. Memory repo at $MEMORY_HOME"
if [ -d "$MEMORY_HOME/.git" ]; then
  ok "already exists, keeping your memory. Updating tooling only (bin/somna, ui/, engine prompts)."
  mkdir -p "$MEMORY_HOME/bin" "$MEMORY_HOME/ui" "$MEMORY_HOME/memory/inbox" "$MEMORY_HOME/memory/clients"
  cp "$KIT_DIR/template/bin/somna" "$MEMORY_HOME/bin/somna"
  cp "$KIT_DIR/template/ui/index.html" "$MEMORY_HOME/ui/index.html"
  cp "$KIT_DIR/template/engine/prompt.md" "$MEMORY_HOME/engine/prompt.md"
  cp "$KIT_DIR/template/engine/map-prompt.md" "$MEMORY_HOME/engine/map-prompt.md"
  for f in hunt-prompt.md validate-prompt.md verify-prompt.md; do cp "$KIT_DIR/template/engine/$f" "$MEMORY_HOME/engine/$f"; done
  [ -f "$MEMORY_HOME/engine/repos.json" ] || cp "$KIT_DIR/template/engine/repos.json" "$MEMORY_HOME/engine/repos.json"
  [ -f "$MEMORY_HOME/memory/inbox/README.md" ] || cp "$KIT_DIR/template/memory/inbox/README.md" "$MEMORY_HOME/memory/inbox/README.md"
  cp "$KIT_DIR/template/memory/clients/README.md" "$MEMORY_HOME/memory/clients/README.md"
  grep -qx "logs/" "$MEMORY_HOME/.gitignore" 2>/dev/null || printf "logs/\n" >> "$MEMORY_HOME/.gitignore"
  ( cd "$MEMORY_HOME"; T="bin ui engine/prompt.md engine/map-prompt.md engine/hunt-prompt.md engine/validate-prompt.md engine/verify-prompt.md engine/repos.json memory/inbox/README.md memory/clients/README.md .gitignore"
    if [ -n "$(git status --porcelain -- $T)" ]; then git add -- $T && git commit -qm "tooling: update from somna installer"; fi )
else
  mkdir -p "$MEMORY_HOME"
  cp -R "$KIT_DIR/template/." "$MEMORY_HOME/"
  ( cd "$MEMORY_HOME"
    git init -q -b main
    git config user.name >/dev/null 2>&1 || git config user.name "$(id -un)"
    git config user.email >/dev/null 2>&1 || git config user.email "$(id -un)@localhost"
    git add -A && git commit -qm "initial memory from somna" )
  ok "created and committed starter memory"
fi
chmod +x "$MEMORY_HOME/bin/somna"
python3 - "$MEMORY_HOME/engine/config.json" "$CLAUDE_BIN" << 'PY'
import json, sys
p, claude = sys.argv[1], sys.argv[2]
cfg = json.load(open(p))
if claude and not cfg.get("claude_bin"): cfg["claude_bin"] = claude
json.dump(cfg, open(p, "w"), indent=2)
PY
( cd "$MEMORY_HOME"; if [ -n "$(git status --porcelain -- engine/config.json)" ]; then git add engine/config.json && git commit -qm "config: record Claude Code path"; fi )
ok "engine/config.json updated"

# keep client files on this Mac: block pushes that contain them
HOOK="$MEMORY_HOME/.git/hooks/pre-push"
cat > "$HOOK" << 'HOOKEOF'
#!/bin/sh
if [ "${ALLOW_CLIENT_PUSH:-0}" != "1" ] && git ls-files memory/clients memory/inbox | grep -v -e '/README.md$' -e '^memory/clients/example/' -e 'example-client.md$' | grep -q .; then
  echo "pre-push: memory/clients/ or memory/inbox/ contain client files. Push blocked to keep them on this Mac."
  echo "Set ALLOW_CLIENT_PUSH=1 only if the remote is private and approved."
  exit 1
fi
HOOKEOF
chmod +x "$HOOK"; ok "pre-push hook keeps client folders and inboxes local"

step "3. Connecting Claude Code"
mkdir -p "$CLAUDE_DIR/skills"
CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"
BEGIN="<!-- somna:begin -->"; END="<!-- somna:end -->"
[ -f "$CLAUDE_MD" ] && cp "$CLAUDE_MD" "$CLAUDE_MD.bak.$(date +%Y%m%d%H%M%S)"
touch "$CLAUDE_MD"
python3 - "$CLAUDE_MD" "$BEGIN" "$END" "$MEMORY_HOME" << 'PY'
import re, sys
path, begin, end, home = sys.argv[1:5]
block = f"""{begin}
# Personal memory
My memory lives in {home}/memory. Start with the index below and open only the files a task needs.
@{home}/memory/index.md

- In a mapped repo, that repo's context and its client's context are injected at session start by a hook.
- General notes: append one dated line to {home}/memory/scratch/notes.md.
- Repo updates: append one dated line to the repo inbox named in the injected context.
- Do not edit other memory files directly. A nightly cycle curates them and I review the changes.
- Never write one client's details anywhere except that client's folder and inbox.
{end}"""
text = open(path).read()
if begin in text:
    text = re.sub(re.escape(begin) + ".*?" + re.escape(end), block, text, flags=re.S)
else:
    text = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
open(path, "w").write(text)
PY
ok "~/.claude/CLAUDE.md imports memory/index.md (backup kept if it existed)"
for s in "$MEMORY_HOME"/skills/*/; do
  name="$(basename "$s")"; target="$CLAUDE_DIR/skills/$name"
  if [ -e "$target" ] && [ ! -L "$target" ]; then warn "skill '$name' already exists in ~/.claude/skills, left untouched"
  else ln -sfn "${s%/}" "$target"; ok "skill linked: $name"; fi
done
SETTINGS="$CLAUDE_DIR/settings.json"
[ -f "$SETTINGS" ] && cp "$SETTINGS" "$SETTINGS.bak.$(date +%Y%m%d%H%M%S)"
PY_BIN="$(command -v python3)"
python3 "$KIT_DIR/lib/settings.py" install "$SETTINGS" "$MEMORY_HOME" "$PY_BIN" "${ACCESS:-read_only}"

step "4. The somna command"
mkdir -p "$BIN_DIR"; ln -sfn "$MEMORY_HOME/bin/somna" "$BIN_DIR/somna"; ok "linked $BIN_DIR/somna"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "add this to ~/.zshrc:  export PATH=\"\$HOME/.local/bin:\$PATH\"";; esac

step "5. Schedule"
if [ "$TIME_SET" -eq 1 ]; then
  "$PY_BIN" "$MEMORY_HOME/bin/somna" schedule --nightly-time "$(printf '%02d:%02d' "$HOUR" "$MINUTE")" >/dev/null && ok "nightly time set to $(printf '%02d:%02d' "$HOUR" "$MINUTE")"
fi
if [ "$SCHEDULE" -eq 1 ] && [ "$(uname -s)" = "Darwin" ]; then
  mkdir -p "$HOME/Library/LaunchAgents" "$MEMORY_HOME/logs"
  cat > "$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$MEMORY_HOME/bin/somna</string>
    <string>tick</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$BIN_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>SOMNA_HOME</key><string>$MEMORY_HOME</string>
    <key>SOMNA_ACTOR</key><string>schedule</string>
  </dict>
  <key>StartInterval</key><integer>600</integer>
  <key>StandardOutPath</key><string>$MEMORY_HOME/logs/schedule.log</string>
  <key>StandardErrorPath</key><string>$MEMORY_HOME/logs/schedule.log</string>
</dict>
</plist>
PLISTEOF
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  ok "scheduler checks every 10 minutes; times, days and the weekly run are in Settings ($("$PY_BIN" "$MEMORY_HOME/bin/somna" schedule | head -1))"
else
  warn "schedule skipped"
fi

if [ "$UI_LOGIN" -eq 1 ] && [ "$(uname -s)" = "Darwin" ]; then
  mkdir -p "$HOME/Library/LaunchAgents" "$MEMORY_HOME/logs"
  cat > "$UI_PLIST" << UIPLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$UI_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$MEMORY_HOME/bin/somna</string>
    <string>ui</string>
    <string>--no-open</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$BIN_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>SOMNA_HOME</key><string>$MEMORY_HOME</string>
    <key>SOMNA_ACTOR</key><string>ui</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$MEMORY_HOME/logs/ui.log</string>
  <key>StandardErrorPath</key><string>$MEMORY_HOME/logs/ui.log</string>
</dict>
</plist>
UIPLISTEOF
  launchctl bootout "gui/$(id -u)" "$UI_PLIST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$UI_PLIST"
  ok "review page always on at http://127.0.0.1:4747 (starts at login)"
fi

INSTALLED="$(grep -m1 '^VERSION = ' "$MEMORY_HOME/bin/somna" | cut -d'"' -f2)"
if [ "$INSTALLED" != "$KIT_VERSION" ]; then
  printf "  \033[31m!!\033[0m   installed version is %s, expected %s. Something went wrong.\n" "$INSTALLED" "$KIT_VERSION"; exit 1
fi
if launchctl print "gui/$(id -u)/$UI_LABEL" >/dev/null 2>&1; then
  launchctl kickstart -k "gui/$(id -u)/$UI_LABEL" >/dev/null 2>&1 && ok "review page restarted on the new version"
fi
ok "Somna $INSTALLED installed"
step "Done"
echo "  Next:  somna doctor                     check everything"
echo "         somna ui                         open the review page in your browser"
echo "         somna create --since-hours 72    or run a first cycle from the terminal"
