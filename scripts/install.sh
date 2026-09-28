#!/bin/sh
# macOS / Linux: AI Coop install (Windows uses the .ps1 scripts). Arguments go to posix_setup.py install; see --help.
set -e
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Python 3.10+: AI_COOP_PYTHON first, then common names and install locations (macOS's /usr/bin/python3 is often 3.9).
for py in "$AI_COOP_PYTHON" python3.14 python3.13 python3.12 python3.11 python3.10 python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  [ -n "$py" ] || continue
  command -v "$py" >/dev/null 2>&1 || continue
  if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    exec "$py" "$DIR/posix_setup.py" install "$@"
  fi
done
echo "AI Coop needs Python 3.10+. Install it (e.g. brew install python, or python.org) or set AI_COOP_PYTHON." >&2
exit 1
