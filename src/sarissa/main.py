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
import uuid
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncIterator, Literal

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from rich.console import Console

from sarissa.api import challenges, session, tools

PORT = 7331  # ALWAYS — no config, no fallback
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"

# Poligon (challenge generator). Loopback only — the Generate tab's one outbound hop.
POLIGON_PORT = 7333
POLIGON_URL = f"http://{HOST}:{POLIGON_PORT}"
GENERATE_TIMEOUT = 30.0
HEALTH_TIMEOUT = 2.0


def poligon_client(timeout: float) -> httpx.AsyncClient:
    # Looked up at call time, so tests can swap in an httpx.MockTransport.
    return httpx.AsyncClient(base_url=POLIGON_URL, timeout=timeout)


class GenerateRequest(BaseModel):
    # Strict: rejects true/"42"/4.0 — bool would otherwise pass as an int.
    model_config = ConfigDict(strict=True, extra="forbid")

    template: Literal["android", "filesystem", "evidence"]
    seed: StrictInt
    difficulty: Annotated[StrictInt, Field(ge=1, le=3)]


async def fetch_challenge(req: GenerateRequest) -> bytes:
    """Poligon generates (JSON with scenario_id), then serves the zip separately."""
    try:
        async with poligon_client(GENERATE_TIMEOUT) as client:
            gen = await client.post("/api/generate", json=req.model_dump())
            if gen.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Poligon error: generate returned HTTP {gen.status_code}")
            try:
                scenario_id = str(uuid.UUID(str(gen.json()["scenario_id"])))
            except (ValueError, KeyError, TypeError):
                raise HTTPException(status_code=502, detail="Poligon error: no scenario id in response") from None
            dl = await client.get(f"/api/download/{scenario_id}")
            if dl.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Poligon error: download returned HTTP {dl.status_code}")
            return dl.content
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Poligon offline") from None
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Poligon timed out") from None
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Poligon error: {type(exc).__name__}") from None


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

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/generate")
    async def generate_challenge(req: GenerateRequest) -> Response:
        """Proxy a generate request to Poligon and return the challenge zip."""
        content = await fetch_challenge(req)
        filename = f"{req.template}_{req.seed}_d{req.difficulty}.zip"
        return Response(
            content=content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/poligon/health")
    async def poligon_health() -> dict:
        try:
            async with poligon_client(HEALTH_TIMEOUT) as client:
                resp = await client.get("/api/health")
        except httpx.HTTPError:
            return {"status": "offline", "port": POLIGON_PORT}
        return {"status": "online", "poligon_status": resp.status_code, "port": POLIGON_PORT}

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
