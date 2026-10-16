#!/bin/sh
# Install this repo's agents into the global opencode config directory.
#
# A V2 plugin cannot register agents, so hoko's agents/*.md are discovered from
# ~/.config/opencode/agents/ instead. Symlinks keep one source of truth: edit a file in
# this repo and restart opencode, and the change is live. Re-running is safe; a real file
# already sitting at a target path is left untouched and reported.
#
# Override the config directory with OPENCODE_CONFIG_DIR.
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
CONFIG="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
TARGET="$CONFIG/agents"

mkdir -p "$TARGET"

linked=0
skipped=0
for file in "$ROOT"/agents/*.md; do
  name=$(basename "$file")
  link="$TARGET/$name"
  if [ -L "$link" ]; then
    rm "$link"
  elif [ -e "$link" ]; then
    echo "skip $link — a real file is already there; move it aside and re-run" >&2
    skipped=$((skipped + 1))
    continue
  fi
  ln -s "$file" "$link"
  linked=$((linked + 1))
done

echo "linked $linked agent(s) into $TARGET"
[ "$skipped" -eq 0 ] || echo "$skipped left untouched" >&2
