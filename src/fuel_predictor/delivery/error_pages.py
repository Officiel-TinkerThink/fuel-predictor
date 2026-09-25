"""What a person sees when an address or a method does not exist.

The framework answered every unknown path with `{"detail":"Not Found"}` -
English, raw JSON, no way back - including to someone following an old
bookmark in a browser. A browser (one that asks for HTML) now gets the app's
own error page; everything else - the API, the page's own script calls - keeps
getting JSON, the API in the same shape as its other errors.

Only the router's own misses are rewritten. An endpoint that raises an
HTTPException with its own message keeps it.
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from fuel_predictor.delivery.rendering import render_error_page

_PAGES = {
    404: (
        "Halaman tidak ditemukan",
        "Alamat ini tidak ada. Mungkin tautannya sudah lama atau ada salah ketik. "
        "Mulai lagi dari Ringkasan.",
    ),
    405: (
        "Tindakan tidak tersedia",
        "Halaman ini tidak menerima tindakan tersebut. Buka halamannya dari menu, lalu coba lagi.",
    ),
}
_ROUTER_MISSES = {"Not Found", "Method Not Allowed"}
# Something failed that no page anticipated. Said without detail - the log
# has the traceback - and with what the person can still do.
_UNEXPECTED = (
    "Terjadi kesalahan",
    "Permintaan ini gagal diproses. Data yang sudah tersimpan aman. Coba lagi sebentar lagi; "
    "bila terus terjadi, sampaikan kepada administrator beserta waktunya.",
)


def register_error_pages(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, error: StarletteHTTPException) -> Response:
        headers = dict(error.headers or {})
        routed_miss = error.status_code in _PAGES and error.detail in _ROUTER_MISSES
        if routed_miss and _wants_a_page(request):
            title, message = _PAGES[error.status_code]
            return HTMLResponse(
                render_error_page(title, message), status_code=error.status_code, headers=headers
            )
        if routed_miss and request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=error.status_code,
                content={
                    "error": {
                        "code": "not_found" if error.status_code == 404 else "method_not_allowed",
                        "message": _PAGES[error.status_code][0] + ".",
                    }
                },
                headers=headers,
            )
        return JSONResponse(
            status_code=error.status_code, content={"detail": error.detail}, headers=headers
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _error: Exception) -> Response:
        # Starlette re-raises after this answer, so the traceback still reaches the log.
        if _wants_a_page(request):
            return HTMLResponse(render_error_page(*_UNEXPECTED), status_code=500)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": _UNEXPECTED[1]}},
        )


def _wants_a_page(request: Request) -> bool:
    return not request.url.path.startswith("/api/") and "text/html" in request.headers.get(
        "accept", ""
    )
