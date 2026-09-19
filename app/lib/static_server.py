"""Background static file server for app/static/.

Streamlit's own static-file route (server.enableStaticServing) forces
``Content-Type: text/plain`` plus ``X-Content-Type-Options: nosniff`` on
every file except a handful of image formats (see
streamlit.web.server.app_static_file_handler.SAFE_APP_STATIC_FILE_EXTENSIONS
in the installed package) — that breaks HTML, CSS and JS entirely, so the
scrollytelling story can't be served that way. This module runs a plain
stdlib HTTP server on a fixed local port instead, which gets MIME types
right for free and needs no extra dependency. Started once per process from
a background daemon thread; safe to call every Streamlit rerun.
"""
from __future__ import annotations

import functools
import http.server
import threading
import urllib.request
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
HOST = "127.0.0.1"
PORT = 8765

_lock = threading.Lock()
_started = False


class _CorsHandler(http.server.SimpleHTTPRequestHandler):
    """Adds CORS so the Streamlit app (a different origin) can load the
    vendored fonts from here, and keeps the request log off stdout."""

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        pass


def _already_serving_our_files() -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/story/index.html", timeout=0.5) as resp:
            return resp.status == 200
    except OSError:
        return False


def ensure_static_server() -> str:
    """Starts the server on first call (per process) and returns its base URL.

    Raises OSError if the port is held by something else entirely.
    """
    global _started
    base_url = f"http://{HOST}:{PORT}"
    with _lock:
        if _started or _already_serving_our_files():
            _started = True
            return base_url

        handler = functools.partial(_CorsHandler, directory=str(STATIC_DIR))
        server = http.server.ThreadingHTTPServer((HOST, PORT), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True, name="story-static-server")
        thread.start()
        _started = True
    return base_url


if __name__ == "__main__":
    print(f"serving {STATIC_DIR} at {ensure_static_server()} (Ctrl+C to stop)")
    threading.Event().wait()
