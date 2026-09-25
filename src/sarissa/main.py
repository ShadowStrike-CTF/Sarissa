# Sarissa — FastAPI app and CLI entry point.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

"""Run with `sarissa` or `python -m sarissa.main`. Always serves on 127.0.0.1:7331."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from rich.console import Console

from sarissa.api import challenges, session, tools

PORT = 7331  # ALWAYS — no config, no fallback
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"


def static_dir() -> Path:
    # PyInstaller one-file builds unpack data under sys._MEIPASS (datas → sarissa/static).
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "sarissa" / "static"
    return Path(__file__).parent / "static"


def create_app(sessions_dir: Path | None = None) -> FastAPI:
    # No session is opened at launch: the browser's launch picker creates or restores one.
    manager = session.SessionManager(sessions_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(session.autosave_loop(manager))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            manager.save()

    # docs_url/redoc_url off: Swagger UI pulls assets from a CDN (external network call).
    app = FastAPI(title="Sarissa", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.sessions = manager
    app.include_router(challenges.router)
    app.include_router(tools.router)
    app.include_router(session.router)

    @app.exception_handler(session.NoActiveSession)
    def no_active_session(request: Request, exc: session.NoActiveSession) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir() / "index.html")

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="sarissa", description="Rapid-access CTF dashboard for digital forensics competitions."
    )
    parser.add_argument(
        "--min-strings", type=int, default=tools.DEFAULT_MIN_STRINGS,
        help="string extractor minimum length (CLI only, default 4)",
    )
    args = parser.parse_args(argv)

    try:
        tools.set_min_strings(args.min_strings)
        app = create_app()
    except ValueError as exc:
        parser.error(str(exc))

    console = Console()
    console.print(f"[bold #922b21]SARISSA[/] — CTF dashboard  [dim]by ShadowStrike[/]")
    console.print(f"Sessions in {app.state.sessions.base_dir} — pick or create one in the browser")
    console.print(f"Serving on [bold]{URL}[/]  (Ctrl+C to stop)")

    opener = threading.Timer(1.0, webbrowser.open, args=(URL,))
    opener.daemon = True
    opener.start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
