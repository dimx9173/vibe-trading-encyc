#!/bin/sh
set -eu

config=${1:-}
if [ -z "$config" ] || [ ! -f "$config" ]; then
  printf '%s\n' "usage: validate-nginx.sh <rendered-nginx.conf>" >&2
  exit 2
fi

if grep -q '\${[A-Z_][A-Z_]*}' "$config"; then
  printf '%s\n' "nginx validation failed: unresolved template placeholder" >&2
  exit 1
fi

if grep -Eq 'proxy_pass[[:space:]]+https?://(agent-server|[^;[:space:]]*insforge)' "$config"; then
  printf '%s\n' "nginx validation failed: private upstream is exposed" >&2
  exit 1
fi

if command -v nginx >/dev/null 2>&1; then
  temp=$(mktemp -d "${TMPDIR:-/tmp}/pp-nginx.XXXXXX")
  trap 'rm -rf "$temp"' EXIT HUP INT TERM
  absolute_config=$(cd "$(dirname "$config")" && pwd)/$(basename "$config")
  {
    printf '%s\n' "events {}"
    printf '%s\n' "http { include \"$absolute_config\"; }"
  } >"$temp/nginx.conf"
  nginx -t -c "$temp/nginx.conf" -p "$temp"
else
  printf '%s\n' "nginx unavailable; deterministic checks passed"
fi
