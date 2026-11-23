#!/bin/bash
# Sing-box carrier (PHP/shared-host runtime) - sanitized version.
# Rules enforced: UUID is a REQUIRED env var (no literal default, exit if missing);
# core binary is downloaded ONLY from the official SagerNet/sing-box GitHub release;
# no third-party subscription conversion, no public subscription endpoint, and
# nothing sensitive (UUID/links) is printed to logs.
# Topology on shared hosts: sing-box listens directly on $PORT (the platform
# terminates TLS in front of it); index.php / check.php are plain camouflage
# pages served by the host's separate web service.
set -e
cd "$(dirname "$0")"

if ! [[ "$UUID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
  echo "FATAL: env UUID is required (no default is provided)" >&2
  exit 1
fi

PORT="${PORT:-3000}"
WS_PATH="${WS_PATH:-/ws}"
SB_VERSION="${SB_VERSION:-1.11.15}"
WORKDIR=".sb-core"
mkdir -p "$WORKDIR"

if [ ! -x "$WORKDIR/sing-box" ]; then
  case "$(uname -m)" in
    x86_64|amd64) ARCH=amd64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;;
  esac
  NAME="sing-box-${SB_VERSION}-linux-${ARCH}"
  URL="https://github.com/SagerNet/sing-box/releases/download/v${SB_VERSION}/${NAME}.tar.gz"
  curl -fsSL "$URL" -o "$WORKDIR/core.tar.gz"
  tar -xzf "$WORKDIR/core.tar.gz" -C "$WORKDIR" "${NAME}/sing-box"
  mv "$WORKDIR/${NAME}/sing-box" "$WORKDIR/sing-box"
  rm -rf "$WORKDIR/${NAME}" "$WORKDIR/core.tar.gz"
  chmod +x "$WORKDIR/sing-box"
fi

cat > "$WORKDIR/config.json" <<EOF
{
  "log": { "level": "warn" },
  "inbounds": [{
    "type": "vless",
    "listen": "0.0.0.0",
    "listen_port": ${PORT},
    "users": [{ "uuid": "${UUID}" }],
    "transport": { "type": "ws", "path": "${WS_PATH}" }
  }],
  "outbounds": [{ "type": "direct" }]
}
EOF

echo "listening on ${PORT}"
exec "$WORKDIR/sing-box" run -c "$WORKDIR/config.json"
