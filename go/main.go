// Sing-box carrier (Go runtime) - sanitized version.
// Rules enforced: UUID is a REQUIRED env var (no literal default, exit if missing);
// core binary is downloaded ONLY from the official SagerNet/sing-box GitHub release;
// no third-party subscription conversion, no public subscription endpoint, and
// nothing sensitive (UUID/links) is printed to logs.
// The wrapper serves a plain HTTP page on $PORT and proxies WebSocket upgrades
// on $WS_PATH to a sing-box VLESS+WS inbound on a loopback port.
package main

import (
	"archive/tar"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
)

var camoPage = []byte("<!doctype html><html><head><title>Welcome</title></head>" +
	"<body><h1>Welcome</h1><p>Site under construction.</p></body></html>")

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func ensureCore(dir, version string) (string, error) {
	binary := filepath.Join(dir, "sing-box")
	if _, err := os.Stat(binary); err == nil {
		return binary, nil
	}
	arch := "amd64"
	if runtime.GOARCH == "arm64" {
		arch = "arm64"
	}
	name := fmt.Sprintf("sing-box-%s-linux-%s", version, arch)
	url := fmt.Sprintf("https://github.com/SagerNet/sing-box/releases/download/v%s/%s.tar.gz", version, name)
	resp, err := http.Get(url)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("download status %s", resp.Status)
	}
	gz, err := gzip.NewReader(resp.Body)
	if err != nil {
		return "", err
	}
	tr := tar.NewReader(gz)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return "", err
		}
		if hdr.Name == name+"/sing-box" {
			out, err := os.OpenFile(binary, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
			if err != nil {
				return "", err
			}
			if _, err := io.Copy(out, tr); err != nil {
				out.Close()
				return "", err
			}
			out.Close()
			return binary, nil
		}
	}
	return "", fmt.Errorf("sing-box binary not found in release tarball")
}

func writeConfig(dir, uuid, wsPath string, corePort int) (string, error) {
	cfg := map[string]any{
		"log": map[string]any{"level": "warn"},
		"inbounds": []any{map[string]any{
			"type":        "vless",
			"listen":      "127.0.0.1",
			"listen_port": corePort,
			"users":       []any{map[string]any{"uuid": uuid}},
			"transport":   map[string]any{"type": "ws", "path": wsPath},
		}},
		"outbounds": []any{map[string]any{"type": "direct"}},
	}
	data, err := json.Marshal(cfg)
	if err != nil {
		return "", err
	}
	path := filepath.Join(dir, "config.json")
	return path, os.WriteFile(path, data, 0o600)
}

func main() {
	uuid := os.Getenv("UUID")
	if !regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`).MatchString(uuid) {
		log.Fatal("FATAL: env UUID is required (no default is provided)")
	}
	port := envOr("PORT", "3000")
	wsPath := envOr("WS_PATH", "/ws")
	version := envOr("SB_VERSION", "1.11.15")
	const corePort = 18080

	exe, err := os.Executable()
	if err != nil {
		log.Fatal(err)
	}
	workdir := filepath.Join(filepath.Dir(exe), ".sb-core")
	if err := os.MkdirAll(workdir, 0o755); err != nil {
		log.Fatal(err)
	}
	binary, err := ensureCore(workdir, version)
	if err != nil {
		log.Fatal(err)
	}
	config, err := writeConfig(workdir, uuid, wsPath, corePort)
	if err != nil {
		log.Fatal(err)
	}
	core := exec.Command(binary, "run", "-c", config)
	core.Stdout = nil
	core.Stderr = nil
	if err := core.Start(); err != nil {
		log.Fatal(err)
	}
	defer core.Process.Kill()

	target, _ := url.Parse(fmt.Sprintf("http://127.0.0.1:%d", corePort))
	proxy := httputil.NewSingleHostReverseProxy(target)
	mux := http.NewServeMux()
	mux.HandleFunc(wsPath, func(w http.ResponseWriter, r *http.Request) {
		proxy.ServeHTTP(w, r)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		w.Write(camoPage)
	})
	log.Println("listening on", port)
	log.Fatal(http.ListenAndServe("0.0.0.0:"+port, mux))
}
