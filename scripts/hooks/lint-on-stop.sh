#!/bin/sh
# Stop: run lint; if it fails, hand the output back to Claude once (stop_hook_active prevents loops).
[ "$(jq -r '.stop_hook_active // false')" = "true" ] && exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
command -v ruff >/dev/null || exit 0
out=$(ruff check -q . 2>&1)
if [ -n "$out" ]; then
  printf 'Lint failed, fix before finishing:\n%s\n' "$out" >&2; exit 2
fi
exit 0
