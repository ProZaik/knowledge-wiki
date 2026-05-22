@echo off
chcp 65001 > nul
title Окружение Knowledge Wiki

echo ============================================================
echo   ЗАПУСК ОКРУЖЕНИЯ WIKI И MCP-СЕРВЕРА (ProZaik)
echo ============================================================
echo.

:: 1. Проверяем наличие Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [X] Ошибка: Python не найден в системе! Пожалуйста, установите Python.
    pause
    exit /b 1
)

:: 2. Запускаем локальный веб-сервер Docsify
echo [1/2] Запускаем локальную вики Docsify на порту 3000...
start "Docsify Wiki (Port 3000)" python scripts/serve_wiki.py

:: 3. Запускаем MCP-сервер в режиме SSE
echo [2/2] Запускаем MCP-сервер (SSE) на порту 8000...
start "Wiki MCP Server (Port 8000)" python scripts/mcp_server.py --transport sse --port 8000

echo.
echo ============================================================
echo   СЕРВИСЫ УСПЕШНО ЗАПУЩЕНЫ!
echo ============================================================
echo.
echo   ⚖️ База знаний Docsify:    http://localhost:3000
echo   🔌 MCP-сервер (SSE):       http://localhost:8000/sse
echo.
echo   ------------------------------------------------------------
echo   КАК ПОДКЛЮЧИТЬ OБЛАЧНЫХ ИИ-КЛИЕНТОВ (Perplexity / ChatGPT):
echo   ------------------------------------------------------------
echo   1. Скачайте ngrok (https://ngrok.com)
echo   2. Запустите команду в терминале:
echo         ngrok http 8000
echo   3. Скопируйте полученную ссылку (например, https://abcd-12-34.ngrok-free.app)
echo   4. Пропишите её в качестве SSE-адреса ИИ-клиента:
echo         https://abcd-12-34.ngrok-free.app/sse
echo.
echo   ------------------------------------------------------------
echo   КАК ПОДКЛЮЧИТЬ К CLAUDE DESKTOP (Локально):
echo   ------------------------------------------------------------
echo   Добавьте в файл %%APPDATA%%\Claude\claude_desktop_config.json:
echo.
echo   "mcpServers": {
echo     "knowledge-wiki": {
echo       "command": "python",
echo       "args": [
echo         "%~dp0scripts\mcp_server.py",
echo         "--transport",
echo         "stdio"
echo       ]
echo     }
echo   }
echo ============================================================
echo.
echo Для остановки серверов просто закройте открывшиеся окна консоли.
echo.
pause
