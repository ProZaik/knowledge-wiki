#!/usr/bin/env python3
"""
Serve Wiki — легковесный локальный HTTP-сервер для просмотра Docsify-вики.
Запускается на порту 3000 и автоматически открывает браузер.
"""

import os
import sys
import http.server
import socketserver
import webbrowser
import threading
import time

PORT = 3000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Кастомный обработчик запросов, который выводит логи более аккуратно."""
    def log_message(self, format, *args):
        # Выводим логи в тихом режиме, чтобы не забивать консоль
        sys.stderr.write(f"[Docsify Server] {format % args}\n")


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
    
    handler = lambda *args, **kwargs: QuietHTTPRequestHandler(*args, directory=ROOT, **kwargs)
    
    try:
        with socketserver.TCPServer(("", PORT), handler) as httpd:
            print("=" * 60)
            print(f" [OK] Локальный Docsify-сервер успешно запущен!")
            print(f" Адрес: http://localhost:{PORT}")
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
