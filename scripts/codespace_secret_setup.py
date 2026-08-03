#!/usr/bin/env python3
"""One-time browser form for saving a Telegram token inside a Codespace.

The helper is intentionally dependency-free.  It never prints, returns, or
logs the submitted token and stops after the first successful save.
"""

from __future__ import annotations

import argparse
import hmac
import html
import os
import re
import secrets
import tempfile
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATTERN = re.compile(r"^[0-9]{6,15}:[A-Za-z0-9_-]{20,}$")
MAX_REQUEST_BYTES = 4096


def valid_telegram_token(value: str) -> bool:
    """Return whether *value* has the documented BotFather token shape."""

    return bool(TOKEN_PATTERN.fullmatch(str(value).strip()))


def write_env_token(env_file: str | Path, token: str) -> None:
    """Atomically replace all Telegram-token entries in an env file."""

    normalized = str(token).strip()
    if not valid_telegram_token(normalized):
        raise ValueError("Invalid Telegram bot token format")

    destination = Path(env_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = destination.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        existing = []
    retained = [
        line for line in existing if not line.startswith("TELEGRAM_BOT_TOKEN=")
    ]
    retained.append(f"TELEGRAM_BOT_TOKEN={normalized}")
    payload = "\n".join(retained).rstrip("\n") + "\n"

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".aaqts_env_",
        dir=destination.parent,
        text=True,
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        os.chmod(destination, 0o600)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def render_form(csrf_token: str, error: str = "") -> bytes:
    error_html = (
        f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AAQTS private setup</title>
  <style>
    body {{ font: 16px system-ui; max-width: 34rem; margin: 3rem auto; padding: 1rem; }}
    label, input, button {{ display: block; width: 100%; box-sizing: border-box; }}
    input, button {{ font: inherit; padding: .8rem; margin-top: .5rem; }}
    button {{ margin-top: 1rem; }}
    .error {{ color: #b42318; }}
    .note {{ color: #475467; }}
  </style>
</head>
<body>
  <h1>AAQTS Telegram setup</h1>
  <p class="note">This private one-time page saves the token only to this Codespace.</p>
  {error_html}
  <form method="post" action="/save" autocomplete="off">
    <input type="hidden" name="csrf" value="{html.escape(csrf_token)}">
    <label for="token">BotFather token</label>
    <input id="token" name="token" type="password" required
           inputmode="text" autocapitalize="none" spellcheck="false"
           placeholder="123456789:AA...">
    <button type="submit">Save token</button>
  </form>
</body>
</html>"""
    return document.encode("utf-8")


def render_success() -> bytes:
    return b"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AAQTS setup complete</title></head><body>
<h1>Token saved</h1><p>You can close this tab and return to ChatGPT.</p>
</body></html>"""


def build_handler(env_file: Path, csrf_token: str):
    """Create a request handler bound to one destination and CSRF token."""

    class SecretSetupHandler(BaseHTTPRequestHandler):
        server_version = "AAQTSSetup/1.0"

        def log_message(self, _format: str, *_args) -> None:
            # Request paths are fixed and there is never a reason to log input.
            return

        def _headers(self, status: HTTPStatus, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                "frame-ancestors 'none'; base-uri 'none'",
            )
            self.send_header(
                "Permissions-Policy",
                "camera=(), microphone=(), geolocation=()",
            )
            self.end_headers()

        def _send_form(self, error: str = "") -> None:
            payload = render_form(csrf_token, error)
            self._headers(HTTPStatus.OK, len(payload))
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path != "/":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_form()

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path != "/save":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return

            form = parse_qs(
                self.rfile.read(length).decode("utf-8", errors="strict"),
                keep_blank_values=True,
            )
            submitted_csrf = form.get("csrf", [""])[0]
            token = form.get("token", [""])[0].strip()
            if not hmac.compare_digest(submitted_csrf, csrf_token):
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not valid_telegram_token(token):
                self._send_form(
                    "Invalid token format. Copy only the digits:letters token from BotFather."
                )
                return

            write_env_token(env_file, token)
            payload = render_success()
            self._headers(HTTPStatus.OK, len(payload))
            self.wfile.write(payload)
            self.wfile.flush()
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    return SecretSetupHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="seconds before the one-time setup page shuts down",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("Port must be between 1 and 65535")
    if not 30 <= args.timeout <= 3600:
        raise SystemExit("Timeout must be between 30 and 3600 seconds")

    csrf_token = secrets.token_urlsafe(32)
    server = HTTPServer(
        (args.host, args.port),
        build_handler(args.env_file.resolve(), csrf_token),
    )
    timer = threading.Timer(args.timeout, server.shutdown)
    timer.daemon = True
    timer.start()
    print(f"AAQTS one-time setup listening on {args.host}:{args.port}")
    print(f"It will close after one successful save or {args.timeout} seconds.")
    try:
        server.serve_forever()
    finally:
        timer.cancel()
        server.server_close()
        print("AAQTS one-time setup stopped")


if __name__ == "__main__":
    main()
