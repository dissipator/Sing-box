// Fixed carrier (written fresh by Lei, 2026-11-23) - runtime wrapper for sing-box.
// Rules enforced: UUID is a REQUIRED env var (no literal default, exit if missing);
// core binary is downloaded ONLY from the official SagerNet/sing-box GitHub release;
// no third-party subscription conversion, no baked-in tokens, no telemetry agents.
// The wrapper serves a plain HTTP page on $PORT and proxies WebSocket upgrades to
// the local sing-box VLESS+WS inbound. Subscription is handled by NodeHub, not here.
const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');
const http = require('http');
const net = require('net');
const { spawn, execFileSync } = require('child_process');

const PORT = parseInt(process.env.PORT || '3000', 10);
const UUID = process.env.UUID;
if (!UUID || !/^[0-9a-fA-F-]{36}$/.test(UUID)) {
  console.error('FATAL: env UUID is required (no default is provided)');
  process.exit(1);
}
const WS_PATH = process.env.WS_PATH || '/ws';
const SB_VERSION = process.env.SB_VERSION || '1.11.15';
const INTERNAL = 10001;

function download(url, dest) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { 'User-Agent': 'carrier' } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400) return download(res.headers.location, dest).then(resolve, reject);
      if (res.statusCode !== 200) return reject(new Error('download status ' + res.statusCode));
      const f = fs.createWriteStream(dest);
      res.pipe(f); f.on('finish', () => f.close(resolve));
    }).on('error', reject);
  });
}

async function ensureCore() {
  const bin = path.join(process.cwd(), 'sing-box');
  if (fs.existsSync(bin)) return bin;
  const arch = os.arch() === 'arm64' ? 'arm64' : 'amd64';
  const name = `sing-box-${SB_VERSION}-linux-${arch}`;
  const url = `https://github.com/SagerNet/sing-box/releases/download/v${SB_VERSION}/${name}.tar.gz`;
  const tgz = path.join(process.cwd(), 'sb.tar.gz');
  await download(url, tgz);
  execFileSync('tar', ['-xzf', tgz, '-C', process.cwd()]);
  fs.copyFileSync(path.join(process.cwd(), name, 'sing-box'), bin);
  fs.chmodSync(bin, 0o755);
  return bin;
}

function writeConfig() {
  const cfg = {
    log: { level: 'warn' },
    inbounds: [{
      type: 'vless', tag: 'vless-in', listen: '127.0.0.1', listen_port: INTERNAL,
      users: [{ uuid: UUID }],
      transport: { type: 'ws', path: WS_PATH }
    }],
    outbounds: [{ type: 'direct', tag: 'direct' }]
  };
  const p = path.join(process.cwd(), 'config.json');
  fs.writeFileSync(p, JSON.stringify(cfg));
  return p;
}

const server = http.createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/html' });
  res.end('<html><body><h3>Server is Running</h3></body></html>');
});
server.on('upgrade', (req, socket, head) => {
  if (!req.url.startsWith(WS_PATH)) { socket.destroy(); return; }
  const upstream = net.connect(INTERNAL, '127.0.0.1', () => {
    upstream.write(`${req.method} ${req.url} HTTP/${req.httpVersion}\r\n` +
      Object.entries(req.headers).map(([k, v]) => `${k}: ${v}`).join('\r\n') + '\r\n\r\n');
    if (head && head.length) upstream.write(head);
    upstream.pipe(socket); socket.pipe(upstream);
  });
  upstream.on('error', () => socket.destroy());
  socket.on('error', () => upstream.destroy());
});

(async () => {
  const bin = await ensureCore();
  const cfg = writeConfig();
  const proc = spawn(bin, ['run', '-c', cfg], { stdio: 'inherit' });
  proc.on('exit', (c) => { console.error('core exited', c); process.exit(1); });
  server.listen(PORT, '0.0.0.0', () => console.log('listening on', PORT));
})().catch((e) => { console.error(e.message); process.exit(1); });
