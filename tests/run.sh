#!/usr/bin/env bash
# Runs one test against a throwaway fake home with a mock Claude Code.
# usage: tests/run.sh <workdir> <port> <test.py> [extra args]
#   env PRESCAN=1  scan sessions once before the test
#   env SETUP=1    create the two sample clients and assign their repos
#   env KIT=<dir>  install from another checkout (default: this repo)
#   env PIPELINE=staged|single (default single), SMALL_NIGHT_KB=<kb> (0 = always the full staged pipeline)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
KIT="${KIT:-$(dirname "$HERE")}"
PYBIN=$(command -v python3.9 || command -v python3)
REALPATH=$PATH
source "$HERE/mkhome.sh" "$1" >/dev/null
export PATH=$PATH:$(dirname $(command -v git 2>/dev/null || echo /usr/bin/git))
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
mkdir -p $HOME/.local/bin
ln -sf $PYBIN $HOME/.local/bin/python3
(cd "$KIT" && ./install.sh --no-schedule --force-non-mac > "$1/install.log" 2>&1) || { cat "$1/install.log"; exit 1; }
# PIPELINE=staged runs the staged pipeline; the older suites were written for the single run and keep it
"$PYBIN" - "$HOME/somna/engine/config.json" "${PIPELINE:-single}" "${SMALL_NIGHT_KB:-40}" <<'PYCFG'
import json, sys
p, mode, small = sys.argv[1], sys.argv[2], float(sys.argv[3])
c = json.load(open(p)); c["pipeline"] = mode; c["small_night_kb"] = small
json.dump(c, open(p, "w"), indent=2)
PYCFG
(cd "$HOME/somna" && git add engine/config.json && git commit -qm "test: pipeline $PIPELINE" >/dev/null 2>&1 || true)
SOMNA_ACTOR=ui $PYBIN $HOME/somna/bin/somna ui --no-open --port $2 > "$1/ui.log" 2>&1 &
echo $! > "$1/ui.pid"
set +e
[ -n "$PRESCAN" ] && $PYBIN $HOME/somna/bin/somna create --since-hours 48 --dry-run > /dev/null
if [ -n "$SETUP" ]; then S="$PYBIN $HOME/somna/bin/somna"
  $S client acme --name "Acme Corp" --markers acme >/dev/null; $S client globex --name "Globex" --markers globex >/dev/null
  $S assign $HOME/code/acme-shop acme --name shop >/dev/null; $S assign $HOME/code/globex-infra globex >/dev/null; fi
sleep 1.2
PATH=$REALPATH:$PATH HOME=$HOME python3 "$HERE/$3" $PYBIN $2 "${@:4}"; rc=$?
kill $(cat "$1/ui.pid") 2>/dev/null || true
exit $rc
