#!/usr/bin/env python3
# Sing-box carrier (Python runtime) - sanitized version.
# Rules enforced: UUID is a REQUIRED env var (no literal default, exit if missing);
# core binary is downloaded ONLY from the official SagerNet/sing-box GitHub release;
# no third-party subscription conversion, no public subscription endpoint, and
# nothing sensitive (UUID/links) is printed to logs.
# The wrapper serves a plain HTTP page on $PORT and proxies WebSocket upgrades
# on $WS_PATH to a sing-box VLESS+WS inbound on a loopback port.
import io
import json
import os
import re
import select
import socket
import subprocess
import sys
import tarfile
import threading
import urllib.request

UUID = os.environ.get("UUID", "")
if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", UUID):
    print("FATAL: env UUID is required (no default is provided)", file=sys.stderr)
    sys.exit(1)

PORT = int(os.environ.get("PORT", "3000"))
WS_PATH = os.environ.get("WS_PATH", "/ws")
SB_VERSION = os.environ.get("SB_VERSION", "1.11.15")
CORE_PORT = 18080
WORKDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".sb-core")
CAMO = (b"<!doctype html><html><head><title>Welcome</title></head>"
        b"<body><h1>Welcome</h1><p>Site under construction.</p></body></html>")


def ensure_core():
    os.makedirs(WORKDIR, exist_ok=True)
    binary = os.path.join(WORKDIR, "sing-box")
    if os.path.exists(binary):
        return binary
    arch = "amd64" if os.uname().machine in ("x86_64", "amd64") else "arm64"
    name = f"sing-box-{SB_VERSION}-linux-{arch}"
    url = f"https://github.com/SagerNet/sing-box/releases/download/v{SB_VERSION}/{name}.tar.gz"
    req = urllib.request.Request(url, headers={"User-Agent": "carrier"})
    with urllib.request.urlopen(req) as resp, tarfile.open(fileobj=io.BytesIO(resp.read()), mode="r:gz") as tar:
        member = tar.getmember(f"{name}/sing-box")
        member.name = "sing-box"
        tar.extract(member, WORKDIR)
    os.chmod(binary, 0o755)
    return binary


def write_config():
    cfg = {
        "log": {"level": "warn"},
        "inbounds": [{
            "type": "vless",
            "listen": "127.0.0.1",
            "listen_port": CORE_PORT,
            "users": [{"uuid": UUID}],
            "transport": {"type": "ws", "path": WS_PATH},
        }],
        "outbounds": [{"type": "direct"}],
    }
    path = os.path.join(WORKDIR, "config.json")
    with open(path, "w") as f:
        json.dump(cfg, f)
    return path


def tunnel(client, core):
    socks = [client, core]
    try:
        while True:
            readable, _, _ = select.select(socks, [], [], 60)
            if not readable:
                break
            for s in readable:
                data = s.recv(65536)
                if not data:
                    return
                (core if s is client else client).sendall(data)
    except OSError:
        pass
    finally:
        for s in socks:
            try:
                s.close()
            except OSError:
                pass


def handle(client):
    try:
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 65536:
            chunk = client.recv(4096)
            if not chunk:
                client.close()
                return
            buf += chunk
        head = buf.split(b"\r\n\r\n", 1)[0].decode("latin-1", "replace")
        lines = head.split("\r\n")
        parts = lines[0].split(" ") if lines else []
        path = parts[1] if len(parts) > 1 else "/"
        headers = {}
        for line in lines[1:]:
            k, _, v = line.partition(":")
            if k:
                headers[k.strip().lower()] = v.strip()
        if path.startswith(WS_PATH) and headers.get("upgrade", "").lower() == "websocket":
            core = socket.create_connection(("127.0.0.1", CORE_PORT), timeout=10)
            core.sendall(buf)
            tunnel(client, core)
        else:
            body = CAMO
            resp = (b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
                    + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            client.sendall(resp)
            client.close()
    except OSError:
        try:
            client.close()
        except OSError:
            pass


def main():
    binary = ensure_core()
    config = write_config()
    core = subprocess.Popen([binary, "run", "-c", config],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", PORT))
        server.listen(128)
        print(f"listening on {PORT}")
        while True:
            client, _ = server.accept()
            threading.Thread(target=handle, args=(client,), daemon=True).start()
    finally:
        core.terminate()


if __name__ == "__main__":
    main()
