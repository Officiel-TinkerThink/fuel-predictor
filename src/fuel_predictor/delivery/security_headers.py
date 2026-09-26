"""Headers every response carries, so a browser holds each page to what it is.

The policy allows what the pages actually use and nothing else: the app's
own scripts, styles and images, its two inline scripts by a nonce minted per
request, and the Google Maps embed as the only frame (the route preview).
FastAPI's /docs and /redoc load Swagger's script and styles from a CDN with
inline code of their own, so they are left out of the page policy; every
other header still applies to them.

There is deliberately no `form-action`: signing an agent in (ADR 0014) ends
in a redirect from our consent form to the agent's own callback address,
which such a directive would block.
"""

import secrets
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_NONCE: ContextVar[str] = ContextVar("csp_nonce", default="")

_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src https://maps.google.com https://www.google.com; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)

_ALWAYS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
)

# Pages whose HTML is FastAPI's, not ours.
_OWN_POLICY_EXEMPT = ("/docs", "/redoc")


def csp_nonce() -> str:
    """The nonce of the response being rendered, for an inline <script>."""
    return _NONCE.get()


class SecurityHeadersMiddleware:
    """Pure ASGI, like the session middleware: the nonce is set in a context
    variable before the route runs, so the template rendering the page reads
    the same value the header announces."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        nonce = secrets.token_urlsafe(18)
        token = _NONCE.set(nonce)
        path: str = scope.get("path", "")
        over_https = scope.get("scheme") == "https"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _value in headers}
                extra = list(_ALWAYS)
                if not path.startswith(_OWN_POLICY_EXEMPT):
                    extra.append((b"content-security-policy", _POLICY.format(nonce=nonce).encode()))
                if over_https:
                    extra.append((b"strict-transport-security", b"max-age=31536000"))
                headers.extend((name, value) for name, value in extra if name not in present)
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            _NONCE.reset(token)
