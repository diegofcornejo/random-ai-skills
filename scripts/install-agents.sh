#!/usr/bin/env bash
# Install the companion subagents / commands of this repo for agents that
# `npx skills` does not cover (it only installs skills).
#
#   Claude Code: prefer the plugin (`/plugin marketplace add diegofcornejo/skills`).
#                This script is the fallback: agents/*.md -> ~/.claude/agents/
#   OpenCode:    opencode/agents/*.md   -> ~/.config/opencode/agents/
#                opencode/commands/*.md -> ~/.config/opencode/commands/
#
# Skills themselves are installed with:
#   npx skills add https://github.com/diegofcornejo/skills
#
# Usage: scripts/install-agents.sh [--claude] [--opencode] [--copy] [--force] [--dry-run]
#   (no target flag = both targets)
#   --copy     copy files instead of symlinking (symlinks track `git pull` automatically)
#   --force    replace existing files (the old file is backed up as <file>.bak.<timestamp>)
#   --dry-run  print what would happen, change nothing
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
OPENCODE_DIR="${OPENCODE_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode}"

do_claude=0 do_opencode=0 mode=link force=0 dry=0
for arg in "$@"; do
  case "$arg" in
    --claude) do_claude=1 ;;
    --opencode) do_opencode=1 ;;
    --copy) mode=copy ;;
    --force) force=1 ;;
    --dry-run) dry=1 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done
if [[ $do_claude -eq 0 && $do_opencode -eq 0 ]]; then do_claude=1 do_opencode=1; fi

installed=0 skipped=0
run() { if [[ $dry -eq 1 ]]; then echo "  [dry-run] $*" >&2; else "$@"; fi; }

install_file() {
  local src="$1" dest_dir="$2" dest
  dest="$dest_dir/$(basename "$src")"
  run mkdir -p "$dest_dir"

  # Already pointing at this repo: nothing to do.
  if [[ -L "$dest" && "$(readlink "$dest")" == "$src" ]]; then
    echo "  = $dest (already linked)" >&2; return
  fi
  if [[ -e "$dest" || -L "$dest" ]]; then
    if [[ $force -eq 0 ]]; then
      echo "  ! $dest exists — skipped (use --force to back it up and replace)" >&2
      skipped=$((skipped + 1)); return
    fi
    local backup
    backup="$dest.bak.$(date +%Y%m%d%H%M%S)"
    run mv "$dest" "$backup"
    echo "  ~ backed up existing file to $backup" >&2
  fi
  if [[ $mode == link ]]; then run ln -s "$src" "$dest"; else run cp "$src" "$dest"; fi
  echo "  + $dest ($mode)" >&2
  installed=$((installed + 1))
}

install_dir() {
  local src_dir="$1" dest_dir="$2" f
  [[ -d "$src_dir" ]] || return 0
  shopt -s nullglob
  for f in "$src_dir"/*.md; do install_file "$f" "$dest_dir"; done
  shopt -u nullglob
}

if [[ $do_claude -eq 1 ]]; then
  echo "Claude Code -> $CLAUDE_DIR" >&2
  install_dir "$REPO_DIR/agents" "$CLAUDE_DIR/agents"
fi
if [[ $do_opencode -eq 1 ]]; then
  echo "OpenCode -> $OPENCODE_DIR" >&2
  install_dir "$REPO_DIR/opencode/agents" "$OPENCODE_DIR/agents"
  install_dir "$REPO_DIR/opencode/commands" "$OPENCODE_DIR/commands"
fi

echo "Done: $installed installed, $skipped skipped." >&2
echo "Reminder: the agents need their skills. Install them with:" >&2
echo "  npx skills add https://github.com/diegofcornejo/skills" >&2
printf '{"installed":%d,"skipped":%d}\n' "$installed" "$skipped"
