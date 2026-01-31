#!/bin/bash
set -e
cd ~/code/granola-tools
source .venv/bin/activate

# Sync from Granola API
python3 sync.py ~/Documents/granola-transcripts

# Rebuild index
python3 build_index.py

echo "$(date): Sync and index complete"
