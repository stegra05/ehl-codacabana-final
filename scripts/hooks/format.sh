#!/bin/sh
# PostToolUse on Edit|Write: format the touched file.
f=$(jq -r '.tool_input.file_path // empty')
[ -n "$f" ] && [ -f "$f" ] || exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
case "$f" in
  *.py) command -v ruff >/dev/null && ruff format -q "$f" && ruff check -q --fix "$f" ;;
  *.ts|*.tsx|*.css|*.json|*.md)
    [ -x web/node_modules/.bin/prettier ] && web/node_modules/.bin/prettier --log-level silent -w "$f" ;;
esac
exit 0
