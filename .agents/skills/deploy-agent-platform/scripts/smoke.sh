#!/bin/sh
set -eu

base_url=${PUBLIC_BASE_URL:-}
health_path=${HEALTH_PATH:-/health}

if [ -z "$base_url" ]; then
  printf '%s\n' "Set PUBLIC_BASE_URL" >&2
  exit 2
fi

curl --fail --silent --show-error \
  --connect-timeout "${CONNECT_TIMEOUT_SECONDS:-5}" \
  --max-time "${MAX_TIME_SECONDS:-30}" \
  "${base_url%/}${health_path}"

printf '\n%s\n' "health smoke check passed"
