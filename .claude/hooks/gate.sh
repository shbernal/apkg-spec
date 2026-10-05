#!/usr/bin/env bash
# Stop hook. While eval/goal.json exists, the agent may stop only when the eval
# gate passes. Exit 2 blocks the stop and hands stderr back to the agent.
set -uo pipefail
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
[[ -f eval/goal.json ]] || exit 0

blocks_file=eval/.gate-blocks
blocks=$(( $(cat "$blocks_file" 2>/dev/null || echo 0) + 1 ))
max=$(python3 -c 'import json;print(json.load(open("eval/goal.json")).get("maxBlocks", 40))')
if (( blocks > max )); then
  echo "gate: $max blocked stops reached; letting the agent stop. Run \`uv run eval/goal.py stop\` or raise maxBlocks." >&2
  exit 0
fi

if output=$(uv run --quiet eval/run.py --gate 2>&1); then
  rm -f "$blocks_file"
  exit 0
fi
echo "$blocks" > "$blocks_file"
{
  echo "The goal gate has not passed (blocked stop $blocks of $max). Keep working."
  echo "$output" | grep -E '^(SCORE|GATE|BUILD|    [-…])' || echo "$output" | tail -20
} >&2
exit 2
