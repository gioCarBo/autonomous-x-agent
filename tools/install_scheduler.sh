#!/usr/bin/env bash
# Installs the systemd user units that drive the agent on this machine.
# Idempotent. Run again after editing the unit files here.
set -eu
UNIT_DIR="$HOME/.config/systemd/user"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/x-agent-wake.service" <<EOF
[Unit]
Description=X agent wake (observe/decide/act cycle)

[Service]
Type=oneshot
ExecStart=$SRC/tools/scheduler.sh wake
TimeoutStartSec=90min
EOF

cat > "$UNIT_DIR/x-agent-wake.timer" <<EOF
[Unit]
Description=Run the X agent wake hourly

[Timer]
# Accelerated feedback phase: hourly wakes at :00 (owner decision, 2026-08-31).
OnCalendar=*-*-* *:00
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
EOF

cat > "$UNIT_DIR/x-agent-reflect.service" <<EOF
[Unit]
Description=X agent daily reflection

[Service]
Type=oneshot
ExecStart=$SRC/tools/scheduler.sh reflect
TimeoutStartSec=90min
EOF

cat > "$UNIT_DIR/x-agent-reflect.timer" <<EOF
[Unit]
Description=Run the X agent reflection each morning, before the first wake

[Timer]
# Judges the finished day, before the first wake; lock skips it if anything overlaps.
OnCalendar=*-*-* 06:30
Persistent=true
RandomizedDelaySec=180

[Install]
WantedBy=timers.target
EOF

# Dedicated agent Chrome: separate profile, CDP on 9223, no consent popups.
# The X login lives in ~/.config/chrome-agent-x (owner logged in once).
cat > "$UNIT_DIR/chrome-agent-x.service" <<EOF
[Unit]
Description=Chrome agent instance for the X influencer agent (dedicated profile, CDP 9223)
After=graphical-session.target

[Service]
Type=simple
Environment=DISPLAY=:0
Environment=XAUTHORITY=%h/.Xauthority
ExecStart=/opt/google/chrome/chrome --user-data-dir=%h/.config/chrome-agent-x --remote-debugging-port=9223 --no-first-run --no-default-browser-check --restore-last-session
Restart=always
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF

cat > "$UNIT_DIR/chrome-agent-restart.service" <<EOF
[Unit]
Description=Nightly restart of the agent Chrome

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl --user restart chrome-agent-x.service
EOF

cat > "$UNIT_DIR/chrome-agent-restart.timer" <<EOF
[Unit]
Description=Restart agent Chrome nightly to prevent CDP aging wedges

[Timer]
# CDP gets flaky after ~a day of uptime (17:03/18:03 wake stops, 2026-09-01);
# a 03:10 restart keeps it fresh. First wake after = 04:00.
OnCalendar=*-*-* 03:10
Persistent=false

[Install]
WantedBy=timers.target
EOF

# NOTE: never run the agent on a cloned Chrome profile — X invalidates
# parallel sessions of the same account (incident 2026-08-31). The agent
# drives the DEDICATED profile above; the owner's main Chrome is untouched.
#
# NOTE: ~/.config/opencode/skills/ must hold NO browser-use skill. opencode
# lists every skill there in each session's prompt, and post-ADR-0001 a
# skill that explains how to drive the browser by hand is a bypass within
# reach of an agent whose write verb just failed. Moved out on 2026-09-06
# to ~/.config/opencode/skills.disabled/ (reversible; not managed here).

systemctl --user daemon-reload
systemctl --user enable --now x-agent-wake.timer x-agent-reflect.timer chrome-agent-restart.timer
systemctl --user enable chrome-agent-x.service
systemctl --user list-timers 'x-agent-*' 'chrome-agent-*' --no-pager
