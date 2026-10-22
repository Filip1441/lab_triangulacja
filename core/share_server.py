import html
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import config
from core import results

logger = logging.getLogger(__name__)

PAGE = """<!doctype html><html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Wyniki laboratorium</title>
<style>body{{font-family:sans-serif;max-width:32rem;margin:1.5rem auto;padding:0 1rem}}
a.big{{display:block;padding:1rem;margin:.6rem 0;background:#0078d4;color:#fff;text-decoration:none;border-radius:.5rem}}
small{{color:#666}}</style></head><body><h2>Wyniki laboratorium</h2>{body}
<p><small>Pliki są usuwane po {days} dniach.</small></p></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.debug(fmt % args)

    def _send(self, code, ctype, data, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        pkgs = results.list_packages()
        if path == "/latest.zip" and pkgs:
            path = "/" + pkgs[0][0]
        if path in ("/", "/index.html"):
            if pkgs:
                links = "".join(
                    f'<a class="big" href="/{html.escape(n)}" download>{"⬇ Najnowsze" if i == 0 else "⬇"} {html.escape(n)}'
                    f' <small style="color:#cde">({s // 1024} KB)</small></a>' for i, (n, s, _) in enumerate(pkgs[:10]))
            else:
                links = "<p>Brak plików.</p>"
            body = PAGE.format(body=links, days=getattr(config, 'RESULTS_KEEP_DAYS', 7)).encode("utf-8")
            return self._send(200, "text/html; charset=utf-8", body)
        name = path.lstrip("/")
        if name in {n for n, _, _ in pkgs}:  # whitelist: only existing result packages, no path traversal
            with open(os.path.join(results.results_dir(), name), "rb") as f:
                data = f.read()
            return self._send(200, "application/zip", data,
                              {"Content-Disposition": f'attachment; filename="{name}"'})
        self._send(404, "text/plain; charset=utf-8", b"Not found")


class ShareServer:
    """Tiny read-only HTTP server that lets students download their result ZIPs over the Pi's Wi-Fi."""
    def __init__(self, port=None):
        self.port = port or getattr(config, 'SHARE_PORT', 8000)
        self.httpd = None

    def start(self):
        try:
            self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), _Handler)
        except OSError as e:
            logger.warning(f"Share server not started on port {self.port}: {e}")
            return False
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        logger.info(f"Share server listening on port {self.port}")
        return True

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
