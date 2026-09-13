"""Local GUI server (stdlib only).

Serves the static single-page UI from gui/static and a small JSON API:
  GET /api/open?path=...   -> parse result (structure tree) + file meta
  GET /api/bytes?path=...&offset=...&length=... -> base64 window of the file
  GET /api/search?path=...&kind=hex|ascii&q=... -> matching byte offsets
  GET /api/formats         -> registered format names

Byte→node lookup (reverse location) is done client-side over the parsed
tree; no per-offset server endpoint is needed.

Parsing happens once per open; the hex view streams windows on demand so
large files are never fully loaded or rendered.
"""
from __future__ import annotations

import base64
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from ffe.api import inspect as ffe_inspect
from ffe.core.registry import registered_formats
from ffe.core.search import parse_hex_query, search_file

STATIC_DIR = Path(__file__).resolve().parents[1] / "gui" / "static"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            if route == "/api/open":
                self._api_open(q)
            elif route == "/api/bytes":
                self._api_bytes(q)
            elif route == "/api/formats":
                self._ensure_parsers()
                self._send(200, json.dumps({"formats": registered_formats()}).encode(),
                           "application/json")
            elif route == "/api/search":
                self._api_search(q)
            elif route == "/":
                self._send(200, (STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif route == "/app.js":
                self._send(200, (STATIC_DIR / "app.js").read_bytes(), "application/javascript")
            elif route == "/style.css":
                self._send(200, (STATIC_DIR / "style.css").read_bytes(), "text/css")
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001 - keep server alive on any handler error
            self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")

    def _api_open(self, q: dict) -> None:
        path = q.get("path", "")
        p = Path(path)
        if not p.is_file():
            self._send(404, json.dumps({"error": f"File not found: {path}"}).encode(), "application/json")
            return
        result = ffe_inspect(str(p))
        if result is None:
            self._send(200, json.dumps({"recognized": False, "fileSize": p.stat().st_size}).encode(),
                       "application/json")
            return
        self._send(200, json.dumps({
            "recognized": True,
            "path": str(p),
            "fileSize": result.file_size,
            "format": result.format_name,
            "messages": result.messages,
            "root": result.root.to_dict(),
        }).encode(), "application/json")

    def _api_bytes(self, q: dict) -> None:
        path = q.get("path", "")
        offset = int(q.get("offset", "0"))
        length = min(int(q.get("length", "4096")), 1 << 20)
        if offset < 0 or length < 0:
            self._send(400, json.dumps({"error": "offset/length must be >= 0"}).encode(),
                       "application/json")
            return
        data = b""
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read(length)
        self._send(200, json.dumps({"offset": offset, "length": len(data),
                                    "data": base64.b64encode(data).decode()}).encode(),
                   "application/json")

    def _ensure_parsers(self) -> None:
        from ffe import api as ffe_api
        ffe_api._ensure()

    def _api_search(self, q: dict) -> None:
        """Search hex bytes or ASCII text; returns hit offsets."""
        path = q.get("path", "")
        query = q.get("q", "")
        kind = q.get("kind", "hex")
        if kind == "hex":
            pattern = parse_hex_query(query)
            if pattern is None:
                self._send(400, json.dumps({"error": "Invalid hex string"}).encode(),
                           "application/json")
                return
        else:
            pattern = query.encode("utf-8", "ignore")
        hits = search_file(path, pattern, limit=int(q.get("limit", "200")))
        self._send(200, json.dumps({"pattern": pattern.hex(" "), "count": len(hits),
                                    "hits": hits}).encode(), "application/json")


def serve(path: str | None = None, port: int = 8737, open_browser: bool = True) -> None:
    if path:
        import urllib.parse
        webbrowser.open(f"http://127.0.0.1:{port}/?file={urllib.parse.quote(str(Path(path).resolve()))}")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"File Format Explorer: http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="optional file to open at startup")
    ap.add_argument("--port", type=int, default=8737)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    serve(a.file, a.port, open_browser=not a.no_browser)
