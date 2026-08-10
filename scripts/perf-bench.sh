#!/usr/bin/env bash
# Menu-shellmap FPS benchmark for local perf iteration.
# Launches Zero Hour windowed, samples engine-reported FPS via RTS_FPS_LOG,
# prints the average of the steady-state samples.
# Usage: ./scripts/perf-bench.sh [label]
set -euo pipefail

LABEL="${1:-unlabeled}"
MODE="${2:-menu}"   # menu | replay
GAME_DIR="/mnt/md0/steam_games/steamapps/common/Command & Conquer Generals - Zero Hour"
EXE="$GAME_DIR/generalszh.exe"
PROTON="/mnt/md0/steam_games/steamapps/common/Proton 9.0 (Beta)/proton"
PREFIX="/home/tim/.steam/steam/steamapps/compatdata/2787042533"
LOG="$(mktemp /tmp/fpsbench.XXXX.log)"
RESULTS="/home/tim/repos/GeneralsGameCode/perf-results.txt"

pkill -f generalszh.exe 2>/dev/null && sleep 3 || true

# Lift the render FPS cap for the duration of the benchmark, restore on exit
OPTIONS_INI="$PREFIX/pfx/drive_c/users/steamuser/Documents/Command and Conquer Generals Zero Hour Data/Options.ini"
ORIG_LIMIT=$(grep -oP '^FramesPerSecondLimit = \K.*' "$OPTIONS_INI" || echo "")
sed -i 's/^FramesPerSecondLimit = .*/FramesPerSecondLimit = 1000000/' "$OPTIONS_INI"
restore_limit() {
    if [ -n "$ORIG_LIMIT" ]; then
        sed -i "s/^FramesPerSecondLimit = .*/FramesPerSecondLimit = $ORIG_LIMIT/" "$OPTIONS_INI"
    fi
}
trap restore_limit EXIT

# Replay playback runs as client instance 2, which reads Options_Instance02.ini
cp "$OPTIONS_INI" "$(dirname "$OPTIONS_INI")/Options_Instance02.ini"

cd "$GAME_DIR"
EXTRA_ARGS=""
if [ "$MODE" = "replay" ]; then
    EXTRA_ARGS="-replay benchmark.rep"
fi
RTS_FPS_LOG="$LOG" \
STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.local/share/Steam" \
STEAM_COMPAT_DATA_PATH="$PREFIX" \
"$PROTON" run "$EXE" -win $EXTRA_ARGS >/dev/null 2>&1 &
GAMEPID=$!

# 50s: ~12s load + intro skip-in, then steady shellmap samples
sleep 50
kill $GAMEPID 2>/dev/null || true
pkill -f generalszh.exe 2>/dev/null || true

# Skip the first 6 samples (loading/intro), average the rest
SAMPLES=$(tail -n +7 "$LOG")
COUNT=$(echo "$SAMPLES" | grep -c . || true)
if [ "$COUNT" -lt 5 ]; then
    echo "BENCH FAILED: only $COUNT steady samples in $LOG"
    exit 1
fi
AVG=$(echo "$SAMPLES" | awk '{s+=$1; n++} END {printf "%.1f", s/n}')
MIN=$(echo "$SAMPLES" | sort -n | head -1)
MAX=$(echo "$SAMPLES" | sort -n | tail -1)
LINE="$(date '+%F %T')  $LABEL($MODE)  avg=$AVG min=$MIN max=$MAX samples=$COUNT"
echo "$LINE" | tee -a "$RESULTS"
rm -f "$LOG"
