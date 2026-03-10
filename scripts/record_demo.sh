#!/usr/bin/env bash
# Record a cairn demo for the README using asciinema
# Usage: bash scripts/record_demo.sh
# Output: demo.cast (asciinema recording)
#
# To convert to GIF: agg demo.cast demo.gif
# To convert to SVG: svg-term --in demo.cast --out demo.svg
# To upload: asciinema upload demo.cast

set -euo pipefail

DEMO_DIR=$(mktemp -d)
CAST_FILE="${1:-demo.cast}"

cleanup() { rm -rf "$DEMO_DIR"; }
trap cleanup EXIT

# Create a fake project to demo in
mkdir -p "$DEMO_DIR/my-project"
cd "$DEMO_DIR/my-project"

# Record the demo
asciinema rec "$CAST_FILE" --command "bash -c '
echo \"$ cd my-project\"
sleep 0.5

echo \"\"
echo \"$ pip install cairn-ai\"
sleep 0.3
echo \"Successfully installed cairn-ai-0.3.1\"
sleep 0.5

echo \"\"
echo \"$ cairn init\"
sleep 0.3
cairn init 2>&1
sleep 1

echo \"\"
echo \"$ cairn status\"
sleep 0.3
cairn status 2>&1
sleep 1

echo \"\"
echo \"$ cairn verify\"
sleep 0.3
cairn verify 2>&1
sleep 1

echo \"\"
echo \"# Your agent now has persistent memory.\"
echo \"# Every session builds on the last.\"
sleep 2
'" --title "cairn — persistent memory for AI agents" --idle-time-limit 2

echo ""
echo "Recording saved to: $CAST_FILE"
echo "Convert to GIF:  agg $CAST_FILE demo.gif"
echo "Convert to SVG:  svg-term --in $CAST_FILE --out demo.svg"
echo "Upload:          asciinema upload $CAST_FILE"
