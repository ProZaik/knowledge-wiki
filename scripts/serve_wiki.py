#!/usr/bin/env python3
"""
Serve Wiki — легковесный локальный HTTP-сервер для просмотра Docsify-вики.
Запускается на порту 3000 и автоматически открывает браузер.

Запросы к /api/* проксируются на MCP API-сервер (по умолчанию localhost:8000).
"""

import os
import sys
import json
import http.server
import socketserver
import webbrowser
import threading
import time
import urllib.request
import urllib.error

PORT = 3000
API_PORT = 8000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class WikiRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Обработчик запросов: проксирует /api/* на MCP-сервер, остальное — статика."""

    def log_message(self, format, *args):
        # Выводим логи в тихом режиме, чтобы не забивать консоль
        sys.stderr.write(f"[Docsify Server] {format % args}\n")

    # ---- API-прокси ----

    def _is_api_request(self):
        """Проверяем, начинается ли путь с /api/."""
        return self.path.startswith("/api/")

    def _proxy_api(self):
        """Проксируем запрос к MCP API-серверу на localhost:API_PORT."""
        target_url = f"http://localhost:{API_PORT}{self.path}"

        # Читаем тело запроса, если есть
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # Собираем заголовки для проксируемого запроса
        proxy_headers = {}
        if self.headers.get("Content-Type"):
            proxy_headers["Content-Type"] = self.headers["Content-Type"]

        try:
            req = urllib.request.Request(
                target_url,
                data=body,
                headers=proxy_headers,
                method=self.command,
            )
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                content_type = resp.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)

        except urllib.error.HTTPError as e:
            # API-сервер вернул HTTP-ошибку — пробрасываем как есть
            resp_body = e.read()
            self.send_response(e.code)
            content_type = e.headers.get("Content-Type", "application/json")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)

        except (urllib.error.URLError, ConnectionError, OSError) as e:
            # MCP-сервер недоступен — возвращаем 502 Bad Gateway
            error_body = json.dumps({
                "error": "MCP API-сервер недоступен",
                "detail": f"Не удалось подключиться к localhost:{API_PORT}. Убедитесь, что MCP-сервер запущен.",
            }).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(error_body)))
            self.end_headers()
            self.wfile.write(error_body)

    # ---- Перехватываем стандартные HTTP-методы ----

    def do_GET(self):
        if self._is_api_request():
            self._proxy_api()
        else:
            super().do_GET()

    def do_POST(self):
        if self._is_api_request():
            self._proxy_api()
        else:
            self.send_error(405, "Method Not Allowed")

    def do_PUT(self):
        if self._is_api_request():
            self._proxy_api()
        else:
            self.send_error(405, "Method Not Allowed")

    def do_DELETE(self):
        if self._is_api_request():
            self._proxy_api()
        else:
            self.send_error(405, "Method Not Allowed")

    def do_PATCH(self):
        if self._is_api_request():
            self._proxy_api()
        else:
            self.send_error(405, "Method Not Allowed")


def open_browser():
    """Открывает браузер после небольшой задержки, чтобы сервер успел запуститься."""
    time.sleep(1)
    url = f"http://localhost:{PORT}"
    print(f"[Docsify Server] Открываем базу знаний в браузере: {url}")
    webbrowser.open(url)


def serve_wiki():
    # Переходим в корневую директорию репозитория, чтобы раздавать файлы оттуда
    os.chdir(ROOT)

    # Решаем проблему с переиспользованием порта "Address already in use"
    socketserver.TCPServer.allow_reuse_address = True

    handler = lambda *args, **kwargs: WikiRequestHandler(*args, directory=ROOT, **kwargs)

    try:
        with socketserver.TCPServer(("", PORT), handler) as httpd:
            print("=" * 60)
            print(f" [OK] Локальный Docsify-сервер успешно запущен!")
            print(f" Адрес: http://localhost:{PORT}")
            print(f" API-прокси: /api/* → http://localhost:{API_PORT}/api/*")
            print(f" Корневая папка: {ROOT}")
            print(" Для остановки сервера нажмите Ctrl+C")
            print("=" * 60)

            # Запускаем браузер в отдельном потоке
            threading.Thread(target=open_browser, daemon=True).start()

            # Запуск бесконечного цикла обслуживания запросов
            httpd.serve_forever()

    except KeyboardInterrupt:
        print("\n[Docsify Server] Сервер остановлен пользователем.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[Docsify Server] Ошибка при запуске сервера: {e}")
        sys.exit(1)


if __name__ == "__main__":
    serve_wiki()
