"""Локальный приёмник картинок из встроенного браузера.

understandingwar.org закрыт Cloudflare: curl/requests получают 403. Поэтому
картинку скачивает сама страница (fetch внутри вкладки, уже прошедшей проверку)
и POST-ит байты сюда. Приёмник кладёт их в папку проекта.

Запуск:  python scripts/receiver.py [--port 18765]
POST /save?path=<относительный путь внутри проекта>   тело = байты файла
GET  /ping                                             -> "ok"
GET  /collect.js                                       -> scripts/collect.js
GET  /sleep?ms=N  /exists?path=…                    -> пауза / "1"|"0"
"""
import argparse
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# откуда браузеру можно писать: вкладка ISW и YouTube Studio (запросы без Origin — curl, проверки — тоже можно)
ORIGINS = {"https://understandingwar.org", "https://www.understandingwar.org", "https://studio.youtube.com"}
# куда можно писать: только данные сессии <YY.MM>/(_raw|_manifest|_collect|_youtube…)/…, не скрипты и не настройки
SAVE_RE = re.compile(r"^\d\d\.\d\d/(_raw|_manifest|_collect|_youtube[^/]*)(/|$)")
SCRIPT_RE = re.compile(r"^(collect|yt_\w+)\.js$")


def inside(rel):
    """Абсолютный путь внутри проекта или None."""
    target = os.path.normpath(os.path.join(ROOT, rel))
    return target if rel and target.startswith(ROOT + os.sep) else None


class Server(ThreadingHTTPServer):
    # на Windows SO_REUSEADDR пускает второй процесс на тот же порт — запросы уходят куда попало
    allow_reuse_address = False


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin in ORIGINS else "null")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        # Chrome Private Network Access: публичный сайт -> localhost
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        # /collect.js — сборщик для вставки во вкладку: eval(await (await fetch(...)).text())
        # /yt_fix.js, /yt_audit.js, /yt_fill.js — то же для страниц YouTube Studio
        name = urlparse(self.path).path.lstrip("/")
        if SCRIPT_RE.match(name):
            try:
                with open(os.path.join(ROOT, "scripts", name), "rb") as f:
                    data = f.read()
            except OSError:
                return self._reply(404, b"no such script")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.end_headers()
            self.wfile.write(data)
            return
        q = parse_qs(urlparse(self.path).query)
        # /sleep?ms=N — пауза на стороне сервера: таймеры фоновой вкладки Chrome
        # троттлятся до раза в минуту, а сетевой запрос — нет
        if urlparse(self.path).path == "/sleep":
            ms = (q.get("ms") or ["0"])[0]
            time.sleep(min(int(ms), 120000) / 1000 if ms.isascii() and ms.isdigit() else 0)
        # /exists?path=… — "1", если файл уже есть (чтобы не качать день повторно)
        if urlparse(self.path).path == "/exists":
            rel = (q.get("path") or [""])[0].replace("\\", "/").lstrip("/")
            body = b"1" if inside(rel) and os.path.exists(inside(rel)) else b"0"
        else:
            body = b"ok"
        self.send_response(200)
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        q = parse_qs(urlparse(self.path).query)
        rel = (q.get("path") or [""])[0].replace("\\", "/").lstrip("/")
        target = inside(rel)
        origin = self.headers.get("Origin")
        if origin and origin not in ORIGINS:
            return self._reply(403, b"bad origin")
        if not target or not SAVE_RE.match(os.path.relpath(target, ROOT).replace("\\", "/")):
            return self._reply(400, b"bad path")
        size = self.headers.get("Content-Length", "")
        ok = size.isascii() and size.isdigit()
        data = self.rfile.read(int(size)) if ok else b""
        if not ok or len(data) != int(size):
            return self._reply(400, b"short body")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        # через .tmp: оборванная запись не оставит обрезанный файл, который /exists посчитает готовым
        with open(target + ".tmp", "wb") as f:
            f.write(data)
        os.replace(target + ".tmp", target)
        self._reply(200, f"saved {len(data)}".encode())
        print(f"saved {rel} ({len(data)} bytes)", flush=True)

    def _reply(self, code, body):
        self.send_response(code)
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18765)
    a = ap.parse_args()
    print(f"receiver on http://127.0.0.1:{a.port}, root={ROOT}", flush=True)
    Server(("127.0.0.1", a.port), Handler).serve_forever()
