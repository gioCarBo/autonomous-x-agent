#!/usr/bin/env bash
# Launch mode (plan 2026-09-06, Q29): for the 48h around the external launch
# the wake timer fires every 15 minutes instead of hourly and the wake loop
# may answer up to the Floor's daily reply cap, notifications first.
#   tools/launch_mode.sh on   -> timer override */15 + state flag
#   tools/launch_mode.sh off  -> hourly again, flag cleared
# Run on the host that runs the timers (the Pi). Idempotent.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
OVR="$UNIT_DIR/x-agent-wake.timer.d"
case "${1:-}" in
  on)
    mkdir -p "$OVR"
    cat > "$OVR/launch.conf" <<EOF
[Timer]
OnCalendar=
OnCalendar=*-*-* *:00,15,30,45
RandomizedDelaySec=0
EOF
    python3 - "$ROOT/memory/state.json" <<'PY'
import json, sys, datetime
p = sys.argv[1]; d = json.load(open(p))
d["launch_mode"] = {"since": datetime.datetime.now().astimezone().isoformat(timespec="minutes"),
                    "replies_per_wake": 3, "note": "external launch: notifications first, answer everyone real, keep the voice gate"}
json.dump(d, open(p, "w"), ensure_ascii=False, indent=2); open(p, "a").write("\n")
PY
    ;;
  off)
    rm -f "$OVR/launch.conf"
    python3 - "$ROOT/memory/state.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d.pop("launch_mode", None)
json.dump(d, open(p, "w"), ensure_ascii=False, indent=2); open(p, "a").write("\n")
PY
    ;;
  *) echo "usage: $0 on|off" >&2; exit 2 ;;
esac
systemctl --user daemon-reload
systemctl --user restart x-agent-wake.timer
systemctl --user list-timers 'x-agent-wake*' --no-pager
echo "launch mode: $1"
