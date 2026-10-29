#!/bin/bash
# GnuchanOS lid switch fix
# This script ensures lid switch events are properly handled

set -e

LID_STATE_FILE="/proc/acpi/button/lid/LID/state"
SYSFS_LID_STATE="/sys/class/power_supply/AC/online"

log() {
    echo "[$(date)] lid-fix: $1"
}

# Check if we're in a live build chroot
if mountpoint -q /live 2>/dev/null || [ -d /live ]; then
    log "Running in live environment, applying lid fix"
else
    log "Running on installed system"
fi

# Create systemd service for lid switch monitoring
cat > /etc/systemd/system/gnuchanos-lid-monitor.service <<'EOF'
[Unit]
Description=GnuchanOS Lid Switch Monitor
After=systemd-logind.service
Requires=systemd-logind.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'echo "Lid monitor active - ensuring systemd-logind handles lid events"'
# Force reload of logind configuration
ExecStart=/bin/systemctl daemon-reload
ExecStart=/bin/systemctl restart systemd-logind.service

[Install]
WantedBy=multi-user.target
EOF

# Also create acpid event handler as fallback
if [ -d /etc/acpi/events ]; then
    cat > /etc/acpi/events/lid <<'EOF'
event=button/lid.*
action=/etc/acpi/lid.sh
EOF

    cat > /etc/acpi/lid.sh <<'EOF'
#!/bin/bash
# ACPI lid event handler for GnuchanOS

LID_STATE=$(cat /proc/acpi/button/lid/LID/state 2>/dev/null | awk '{print $2}' || echo "unknown")

case "$LID_STATE" in
    "open")
        echo "Lid opened at $(date)" >> /var/log/lid-events.log
        # Wake up from suspend if needed
        ;;
    "closed")
        echo "Lid closed at $(date)" >> /var/log/lid-events.log
        # Use systemd-logind to suspend
        /usr/bin/loginctl suspend 2>/dev/null || true
        ;;
    *)
        echo "Unknown lid state: $LID_STATE at $(date)" >> /var/log/lid-events.log
        ;;
esac
EOF

    chmod +x /etc/acpi/lid.sh
    log "Created ACPI lid event handler as fallback"
fi

# Enable and start the service
systemctl enable gnuchanos-lid-monitor.service 2>/dev/null || true

log "Lid switch fix applied. System will suspend on lid close."
log "Check with: systemctl status systemd-logind"
log "Test with: loginctl suspend"