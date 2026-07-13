"""Static-file serving with history-routing fallback for the React UI."""
from __future__ import annotations

from pathlib import PurePosixPath

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class SPAStaticFiles(StaticFiles):
    """Serve index.html for clean client routes while preserving real 404s."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            request_path = str(scope.get("path", "")).lstrip("/")
            is_client_route = (
                exc.status_code == 404
                and not request_path.startswith(("api/", "assets/"))
                and not PurePosixPath(request_path).suffix
            )
            if not is_client_route:
                raise
            return await super().get_response("index.html", scope)
