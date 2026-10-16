#!/bin/bash
# Pasang jadwal otomatis di macOS (launchd): pemindaian setiap hari pukul 07:00.
# Pakai:   bash install_mac.sh          -> pasang / perbarui jadwal
#          bash install_mac.sh remove   -> hapus jadwal
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="id.pantauriset.scan"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
HOUR="${HOUR:-7}"
MINUTE="${MINUTE:-0}"

if [ "$1" = "remove" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Jadwal dihapus."
  exit 0
fi

chmod +x "$DIR/run.sh"
mkdir -p "$HOME/Library/LaunchAgents" "$DIR/logs"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$DIR/run.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>$HOUR</integer>
    <key>Minute</key><integer>$MINUTE</integer>
  </dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$DIR/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/launchd.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load "$PLIST"
echo "Jadwal terpasang: setiap hari pukul $(printf '%02d:%02d' "$HOUR" "$MINUTE") (saat Mac menyala)."
echo "Catatan: bila Mac tertidur pada jam itu, launchd menjalankannya segera setelah Mac bangun."
echo "Uji sekarang:  bash \"$DIR/run.sh\" --dry-run && tail -n 30 \"$DIR\"/logs/scan_*.log"
