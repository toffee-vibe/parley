"""Запуск MCP-сервера в фоновом потоке со своим event loop — интерфейс Qt живёт в главном потоке."""

from __future__ import annotations

import asyncio
import logging
import threading

import uvicorn
from mcp.server.mcpserver import MCPServer

log = logging.getLogger(__name__)


class BackgroundServer:
    def __init__(self, mcp: MCPServer, host: str, port: int):
        app = mcp.streamable_http_app(host=host)
        self._server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning",
                                                     lifespan="on"))
        self._thread = threading.Thread(target=self._run, name="mcp-server", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        # Открытые SSE-потоки иначе держат выход. Принудительная остановка обрывает и lifespan,
        # а uvicorn печатает об этом безвредный traceback — его прячем.
        logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
        self._server.should_exit = True
        self._server.force_exit = True
        self._thread.join(timeout=3)

    def _run(self) -> None:
        try:
            asyncio.run(self._server.serve())
        except Exception:
            log.exception("MCP-сервер упал")
