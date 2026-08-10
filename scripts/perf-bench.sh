#!/usr/bin/env bash
# Menu-shellmap FPS benchmark for local perf iteration.
# Launches Zero Hour windowed, samples engine-reported FPS via RTS_FPS_LOG,
# prints the average of the steady-state samples.
# Usage: ./scripts/perf-bench.sh [label]
set -euo pipefail

LABEL="${1:-unlabeled}"
MODE="${2:-menu}"   # menu | replay | replayzoom
GAME_DIR="/mnt/md0/steam_games/steamapps/common/Command & Conquer Generals - Zero Hour"
EXE="$GAME_DIR/generalszh.exe"
PROTON="/mnt/md0/steam_games/steamapps/common/Proton 9.0 (Beta)/proton"
PREFIX="/home/tim/.steam/steam/steamapps/compatdata/2787042533"
LOG="$(mktemp /tmp/fpsbench.XXXX.log)"
RESULTS="/home/tim/repos/GeneralsGameCode/perf-results.txt"

pkill -f "[g]eneralszh.exe" 2>/dev/null && sleep 3 || true
# A wineserver lingering after a killed run can hold the single-instance mutex
# and make every new launch exit instantly. Clear it when no game is running.
if ! pgrep -f "[g]eneralszh.exe" >/dev/null; then
    pkill -f "[w]ineserver" 2>/dev/null && sleep 4 || true
fi

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
if [ "$MODE" = "replay" ] || [ "$MODE" = "replayzoom" ]; then
    EXTRA_ARGS="-replay benchmark.rep"
fi
RTS_FPS_LOG="$LOG" \
STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.local/share/Steam" \
STEAM_COMPAT_DATA_PATH="$PREFIX" \
"$PROTON" run "$EXE" -win $EXTRA_ARGS >/dev/null 2>&1 &
GAMEPID=$!

if [ "$MODE" = "replayzoom" ]; then
    # After the match loads, zoom the camera out to the maximum before sampling
    sleep 18
    WID=$(DISPLAY=:0 xdotool search --name "Instance:02" 2>/dev/null | head -1)
    if [ -n "$WID" ]; then
        eval "$(DISPLAY=:0 xdotool getwindowgeometry --shell $WID)"
        CX=$((X + WIDTH/2)); CY=$((Y + HEIGHT/2))
        DISPLAY=:0 xdotool windowactivate $WID mousemove $CX $CY
        for k in $(seq 1 30); do DISPLAY=:0 xdotool click 5; sleep 0.1; done
    fi
    # discard pre-zoom samples: truncate the log, then sample the zoomed state
    : > "$LOG"
    sleep 30
else
    # 50s: ~12s load + intro skip-in, then steady shellmap samples
    sleep 50
fi
kill $GAMEPID 2>/dev/null || true
pkill -f "[g]eneralszh.exe" 2>/dev/null || true

# Skip warmup samples (loading/intro); replayzoom already truncated to steady state
if [ "$MODE" = "replayzoom" ]; then
    SAMPLES=$(tail -n +2 "$LOG")
else
    SAMPLES=$(tail -n +7 "$LOG")
fi
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
