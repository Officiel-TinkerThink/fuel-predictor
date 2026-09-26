"""The files a browser or crawler asks a site for by name, and static caching.

Browsers ask for /favicon.ico and phones for /apple-touch-icon.png whatever
the page links; both used to be sent to the sign-in page. /robots.txt asks
search engines to leave an internal tool alone.

A stylesheet or script is addressed by a hash of its content (`?v=`), so a
changed file has a new address: such a response may be kept for a year.
"""

from urllib.parse import parse_qs

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from fuel_predictor.delivery.rendering import STATIC_DIRECTORY

_A_DAY = "public, max-age=86400"


def build_site_files_router() -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/favicon.ico")
    def favicon() -> FileResponse:
        return FileResponse(
            STATIC_DIRECTORY / "favicon.ico",
            media_type="image/vnd.microsoft.icon",
            headers={"Cache-Control": _A_DAY},
        )

    @router.get("/apple-touch-icon.png")
    @router.get("/apple-touch-icon-precomposed.png")
    def touch_icon() -> FileResponse:
        return FileResponse(
            STATIC_DIRECTORY / "apple-touch-icon.png",
            media_type="image/png",
            headers={"Cache-Control": _A_DAY},
        )

    @router.get("/robots.txt")
    def robots() -> PlainTextResponse:
        return PlainTextResponse("User-agent: *\nDisallow: /\n", headers={"Cache-Control": _A_DAY})

    return router


class VersionedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        if "v" in query and response.status_code in (200, 304):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
