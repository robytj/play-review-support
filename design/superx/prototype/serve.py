"""Static server for the SuperX prototype on Railway (project: support).

Serves this folder on $PORT. If SHARE_PASSWORD is set, every request needs HTTP basic auth
(user: SHARE_USER, default "team"). The generator folder _build/ is never served.
Standard library only.
"""
import base64
import hmac
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
USER = os.environ.get("SHARE_USER", "team")
PASSWORD = os.environ.get("SHARE_PASSWORD", "")
HIDDEN = ("/_build", "/serve.py", "/Dockerfile", "/railway.json")


class Handler(SimpleHTTPRequestHandler):
    def _authorized(self) -> bool:
        if not PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
        except Exception:
            return False
        return hmac.compare_digest(user, USER) and hmac.compare_digest(pw, PASSWORD)

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="SuperX prototype"')
            self.end_headers()
            return
        if self.path.split("?")[0].startswith(HIDDEN):
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        self.do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Robots-Tag", "noindex")
        super().end_headers()

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"SuperX prototype on :{port} (password {'on' if PASSWORD else 'off'})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), partial(Handler, directory=ROOT)).serve_forever()
