#!/usr/bin/env bash
# Link the files in global/ into the Claude Code config folder.
# Back up each existing file that is not already a link to this repo.
# Safe to run again: links that are already correct stay as they are.
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
backup_dir="$target_dir/backups/ai-workflow-$(date +%Y%m%d-%H%M%S)"
files=(CLAUDE.md AGENTS.md settings.json)

mkdir -p "$target_dir"
backed_up=0

for name in "${files[@]}"; do
  src="$repo_dir/global/$name"
  dest="$target_dir/$name"

  if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
    echo "ok      $dest"
    continue
  fi

  if [ -e "$dest" ] || [ -L "$dest" ]; then
    mkdir -p "$backup_dir"
    mv "$dest" "$backup_dir/$name"
    backed_up=1
    echo "backup  $dest -> $backup_dir/$name"
  fi

  ln -s "$src" "$dest"
  echo "linked  $dest -> $src"
done

if [ "$backed_up" -eq 1 ]; then
  echo
  echo "Compare the backups with global/ and copy any changes you want to keep:"
  echo "  diff -r \"$backup_dir\" \"$repo_dir/global\""
fi
