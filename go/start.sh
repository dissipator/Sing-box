#!/bin/sh
# Sing-box carrier (Go runtime) launcher - sanitized version.
# UUID must be provided via env by the platform; see main.go.
set -e
cd "$(dirname "$0")"
if [ -z "$UUID" ]; then
  echo "FATAL: env UUID is required (no default is provided)" >&2
  exit 1
fi
go build -o carrier main.go
exec ./carrier
