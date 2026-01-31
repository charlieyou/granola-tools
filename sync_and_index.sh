#!/bin/bash
set -e

export PATH="$HOME/.local/bin:$PATH"

granola sync
granola index

echo "$(date): Sync and index complete"
