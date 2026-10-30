#!/usr/bin/env bash
# Start the game-day runner unless one is already running or waiting to start.
set -euo pipefail
busy=$(gh run list --workflow gameday.yml --limit 5 --json status \
  -q '[.[] | select(.status=="in_progress" or .status=="queued" or .status=="waiting" or .status=="pending")] | length' \
  --repo "$GITHUB_REPOSITORY")
if [ "$busy" = "0" ]; then
  gh workflow run gameday.yml --ref main --repo "$GITHUB_REPOSITORY"
  echo "Started the game-day runner."
else
  echo "Game-day runner already active."
fi
