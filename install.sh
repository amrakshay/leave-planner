#!/usr/bin/env bash
# One-time setup: link the skill into Claude Code and add a shell alias that opens
# the dashboard from anywhere. Safe to run again; it only changes what is missing.
#
#   ./install.sh            # alias name: leaves
#   ./install.sh myleaves   # pick another alias name
set -euo pipefail

ALIAS_NAME="${1:-leaves}"
REPO="$(cd "$(dirname "$0")" && pwd)"
SKILL_LINK="$HOME/.claude/skills/leave-dashboard"

# 1. Skill symlink
mkdir -p "$HOME/.claude/skills"
if [ -L "$SKILL_LINK" ] && [ "$(readlink "$SKILL_LINK")" = "$REPO/skill" ]; then
  echo "Skill already linked: $SKILL_LINK"
elif [ -e "$SKILL_LINK" ]; then
  echo "Skipped skill link: $SKILL_LINK already exists and points elsewhere. Remove it and re-run." >&2
else
  ln -s "$REPO/skill" "$SKILL_LINK"
  echo "Linked skill: $SKILL_LINK -> $REPO/skill"
fi

# 2. Shell alias (goes through the skill link, so it keeps working if the repo moves
#    and you re-link it)
case "$(basename "${SHELL:-}")" in
  zsh)  RC="$HOME/.zshrc" ;;
  bash) if [ "$(uname)" = Darwin ]; then RC="$HOME/.bash_profile"; else RC="$HOME/.bashrc"; fi ;;
  *)    RC="" ;;
esac
LINE="alias $ALIAS_NAME='python3 \"\$HOME/.claude/skills/leave-dashboard/build.py\" --open'"
MARK="# leave-planner: open the leave dashboard"

if [ -z "$RC" ]; then
  echo "Unknown shell (${SHELL:-none}). Add this line to your shell's startup file:"
  echo "  $LINE"
elif grep -qF "$MARK" "$RC" 2>/dev/null; then
  echo "Alias already in $RC (look for: $MARK)"
else
  printf '\n%s\n%s\n' "$MARK" "$LINE" >> "$RC"
  echo "Added alias '$ALIAS_NAME' to $RC. Open a new terminal (or run: source $RC), then type: $ALIAS_NAME"
fi

[ -f "$REPO/config.json" ] || echo "Next: cp examples/config.example.json config.json and fill it in, then run /leave-dashboard in Claude Code."
