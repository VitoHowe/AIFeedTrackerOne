# -*- coding: utf-8 -*-
"""配置面板 API"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import PANEL_CONFIG
from .config_store import read_creators, read_env_values, update_env_values, write_creators

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"

ALLOWED_ENV_KEYS = [
    "app_id",
    "app_secret",
    "FEISHU_TEMPLATE_ID",
    "FEISHU_TEMPLATE_VERSION",
    "FEISHU_USER_OPEN_ID",
    "SESSDATA",
    "bili_jct",
    "buvid3",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "refresh_token",
    "AI_SERVICE",
    "AI_API_KEY",
    "AI_BASE_URL",
    "AI_MODEL",
    "USER_AGENT",
    "PANEL_HOST",
    "PANEL_ADMIN_TOKEN",
]


def _is_local_request(request: Request) -> bool:
    if not request.client:
        return False
    return request.client.host in {"127.0.0.1", "::1"}


def require_admin(request: Request) -> None:
    admin_token = PANEL_CONFIG.get("admin_token")
    if not admin_token:
        return
    provided = request.headers.get("X-Admin-Token") or request.query_params.get("token")
    if provided != admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_read(request: Request) -> None:
    admin_token = PANEL_CONFIG.get("admin_token")
    if admin_token:
        provided = request.headers.get("X-Admin-Token") or request.query_params.get("token")
        if provided != admin_token:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return
    return


async def _notify_change(on_change: Optional[Callable[[], object]]) -> None:
    if not on_change:
        return
    result = on_change()
    if inspect.isawaitable(result):
        await result


def create_app(on_change: Optional[Callable[[], object]] = None) -> FastAPI:
    app = FastAPI(title="AIFeedTracker Config Panel")
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    async def get_config(_: None = Depends(require_read)) -> Dict[str, Optional[str]]:
        return read_env_values(ALLOWED_ENV_KEYS)

    @app.post("/api/config")
    async def update_config(
        payload: Dict[str, Optional[str]] = Body(...),
        _: None = Depends(require_admin),
    ) -> Dict[str, Optional[str]]:
        updates = {k: v for k, v in payload.items() if k in ALLOWED_ENV_KEYS}
        update_env_values(updates)
        await _notify_change(on_change)
        return read_env_values(ALLOWED_ENV_KEYS)

    @app.get("/api/creators")
    async def get_creators(_: None = Depends(require_read)) -> List[dict]:
        return read_creators()

    @app.post("/api/creators")
    async def update_creators(
        creators: List[dict] = Body(...),
        _: None = Depends(require_admin),
    ) -> Dict[str, str]:
        write_creators(creators)
        await _notify_change(on_change)
        return {"status": "ok"}

    return app
