"""End-to-end check of rtk PR #4778 (49087db): real `rtk hook claude` SessionStart calls.

Each scenario starts its own local listener, points ANTHROPIC_BASE_URL at it, and
runs the hook in a clean environment whose Claude config dir, profile dirs and
rtk data all live under the scratch root (nothing under the real profile).

Usage: python -I e2e.py <rtk binary> <scratch-root>
"""

import http.server
import json
import os
import pathlib
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import traceback

# Absolute: on POSIX, subprocess resolves a relative program against the child's cwd.
RTK = str(pathlib.Path(sys.argv[1]).resolve())
ROOT = pathlib.Path(sys.argv[2]).resolve()  # env paths must not depend on the child's cwd
WARN = "not answering as the RTK proxy"
SPAWNED = ("started the RTK proxy", "launched the RTK proxy", "could not be started")
RTK_HEALTH = b'{"service":"rtk-proxy","status":"ok"}'
IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def annotate(title, message):
    """Report a failure as an error annotation: the API serves those without a login."""
    if not IN_ACTIONS:
        return

    def esc(text):
        return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    title = esc(title).replace(":", "%3A").replace(",", "%2C")
    print(f"::error title={title}::{esc(message)}")


def http_gateway(status, body, host="127.0.0.1", family=socket.AF_INET):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        address_family = family
        daemon_threads = True

    server = Server((host, 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def bare_listener(host="127.0.0.1", family=socket.AF_INET):
    """Accepts connections at the TCP level and never answers: a hung daemon."""
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.bind((host, 0))
    sock.listen(128)
    return sock, sock.getsockname()[1]


def ipv6_available():
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


def run_hook(name, url, settings_url=None, proxy_bind=None):
    case = ROOT / name
    home = case / "home"
    claude = case / "claude"
    for d in (home / "AppData" / "Roaming", home / "AppData" / "Local", claude, case / "tmp", case / "project"):
        d.mkdir(parents=True, exist_ok=True)
    if settings_url is not None:
        (claude / "settings.json").write_text(
            json.dumps({"env": {"ANTHROPIC_BASE_URL": settings_url}}), encoding="utf-8"
        )
    env = {
        "TMP": str(case / "tmp"),
        "TEMP": str(case / "tmp"),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "CLAUDE_CONFIG_DIR": str(claude),
        "RTK_DB_PATH": str(case / "rtk" / "history.db"),
        "RTK_TEE_DIR": str(case / "rtk" / "tee"),
        "RTK_RECALL_DB": str(case / "rtk" / "recall.db"),
        "RTK_TELEMETRY_DISABLED": "1",
        "ANTHROPIC_BASE_URL": url,
    }
    if os.name == "nt":
        env.update({"SYSTEMROOT": r"C:\Windows", "WINDIR": r"C:\Windows", "PATH": r"C:\Windows\system32;C:\Windows"})
    else:
        env["PATH"] = "/usr/bin:/bin"
    if proxy_bind is not None:
        env["RTK_PROXY_BIND"] = proxy_bind
    payload = {
        "session_id": f"e2e-{name}",
        "transcript_path": "",
        "cwd": str(case / "project"),
        "hook_event_name": "SessionStart",
        "source": "startup",
    }
    out = subprocess.run(
        [RTK, "hook", "claude"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=case / "project",
        timeout=60,
    )
    return out


def check(name, expect, out, bind_addr=None):
    stdout, stderr = out.stdout.strip(), out.stderr.strip()
    msg = ""
    if stdout:
        try:
            msg = json.loads(stdout).get("systemMessage", "")
        except json.JSONDecodeError:
            msg = f"<non-JSON stdout> {stdout}"
    problems = []
    if out.returncode != 0:
        problems.append(f"exit {out.returncode}")
    if stderr:
        problems.append(f"stderr: {stderr}")
    if any(s in msg for s in SPAWNED):
        problems.append("spawned a daemon")
    if expect == "silent" and stdout:
        problems.append("expected silence")
    if expect == "warn":
        if WARN not in msg:
            problems.append("expected the not-answering warning")
        elif bind_addr and f"--bind {bind_addr}" not in msg:
            problems.append(f"warning does not name --bind {bind_addr}")
    status = "PASS" if not problems else "FAIL"
    shown = msg if msg else "(no output)"
    print(f"{status}  {name:<34} expect={expect:<6} -> {shown}" + (f"   [{'; '.join(problems)}]" if problems else ""))
    if problems:
        annotate(f"e2e {name}", f"{shown} [{'; '.join(problems)}]")
    return not problems


def main():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True)
    results = []

    # No RTK setup for the address: whatever holds the port is the user's own gateway.
    for status in ("200 OK", "401 Unauthorized", "404 Not Found"):
        code = int(status.split()[0])
        server, port = http_gateway(code, b"{}")
        name = f"no-setup/http-{code}"
        results.append(check(name, "silent", run_hook(name.replace("/", "_"), f"http://127.0.0.1:{port}")))
        server.shutdown()
    sock, port = bare_listener()
    results.append(check("no-setup/silent-listener", "silent", run_hook("ns_bare", f"http://127.0.0.1:{port}")))
    sock.close()
    server, port = http_gateway(200, RTK_HEALTH)
    results.append(check("no-setup/rtk-daemon", "silent", run_hook("ns_rtk", f"http://127.0.0.1:{port}")))
    server.shutdown()

    # settings.json env.ANTHROPIC_BASE_URL names the address.
    server, port = http_gateway(200, b"{}")
    url = f"http://127.0.0.1:{port}"
    results.append(check("settings/other-service", "warn", run_hook("st_http", url, settings_url=url), f"127.0.0.1:{port}"))
    server.shutdown()
    sock, port = bare_listener()
    url = f"http://127.0.0.1:{port}"
    results.append(check("settings/hung-daemon", "warn", run_hook("st_bare", url, settings_url=url), f"127.0.0.1:{port}"))
    sock.close()
    server, port = http_gateway(200, RTK_HEALTH)
    url = f"http://127.0.0.1:{port}"
    results.append(check("settings/rtk-daemon", "silent", run_hook("st_rtk", url, settings_url=url)))
    server.shutdown()
    server, port = http_gateway(200, b"{}")
    other = port + 1 if port < 65535 else port - 1
    results.append(check("settings/names-another-port", "silent", run_hook("st_other", f"http://127.0.0.1:{port}", settings_url=f"http://127.0.0.1:{other}")))
    server.shutdown()

    # RTK_PROXY_BIND names the address.
    server, port = http_gateway(200, b"{}")
    results.append(check("rtk-proxy-bind/other-service", "warn", run_hook("pb_http", f"http://127.0.0.1:{port}", proxy_bind=f"127.0.0.1:{port}"), f"127.0.0.1:{port}"))
    server.shutdown()

    # localhost with a listener on [::1] only.
    if ipv6_available():
        server, port = http_gateway(200, b"{}", host="::1", family=socket.AF_INET6)
        url = f"http://localhost:{port}"
        results.append(check("localhost/ipv6-gateway", "silent", run_hook("lh_v6", url)))
        results.append(check("localhost/ipv6-gateway+settings", "warn", run_hook("lh_v6_st", url, settings_url=url), f"127.0.0.1:{port}"))
        server.shutdown()
        server, port = http_gateway(200, RTK_HEALTH, host="::1", family=socket.AF_INET6)
        results.append(check("localhost/ipv6-rtk-daemon", "silent", run_hook("lh_v6_rtk", f"http://localhost:{port}")))
        server.shutdown()
    else:
        print("SKIP  localhost/[::1] cases: no IPv6 loopback")

    print(f"\n{sum(results)}/{len(results)} scenarios passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        annotate("e2e crashed", traceback.format_exc()[-2000:])
        raise
