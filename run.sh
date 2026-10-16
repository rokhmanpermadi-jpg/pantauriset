#!/bin/bash
# Jalankan pemindaian sekali. Dipanggil oleh launchd (Mac) atau manual.
cd "$(dirname "$0")" || exit 1
mkdir -p logs
PY="$(command -v python3 || echo /usr/bin/python3)"
"$PY" scan.py "$@" >> "logs/scan_$(date +%Y-%m).log" 2>&1
