#!/bin/bash
set -e

# Load environment
export PATH="$HOME/.local/bin:$PATH"

# Run sync and index via installed CLI
granola-sync ~/Documents/granola-transcripts
python3 -c "from granola_tools.index import build_index; build_index()"

echo "$(date): Sync and index complete"
