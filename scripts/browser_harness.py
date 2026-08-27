"""Drive real Chrome over the DevTools Protocol, and record what it does.

Built on CDP rather than Playwright so it needs nothing installed that is not
already here: Chrome ships with the machine, `websockets` comes in with uvicorn,
and ffmpeg is on PATH. The point is to execute the application's JavaScript —
`app.js` is 163 lines driving route stops, field visibility, and live
validation, and none of it runs under the Python test suite, which only ever
sees the HTML the server rendered.

Recording is a means, not the goal. Each scenario asserts; the video is what
lets a person watch the same thing and disagree.
"""

import asyncio
import base64
import json
import shutil
import subprocess
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class BrowserError(RuntimeError):
    pass


@dataclass
class Frame:
    at: float
    png: bytes


@dataclass
class Cdp:
    """A minimal CDP client: request/response plus buffered events."""

    socket: Any
    _next_id: int = 1
    events: list[dict[str, Any]] = field(default_factory=list)

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        message_id = self._next_id
        self._next_id += 1
        await self.socket.send(
            json.dumps({"id": message_id, "method": method, "params": params})
        )
        while True:
            message = json.loads(await self.socket.recv())
            if message.get("id") == message_id:
                if "error" in message:
                    raise BrowserError(f"{method}: {message['error']}")
                return dict(message.get("result", {}))
            if "method" in message:
                self.events.append(message)

    async def drain(self, handler: Callable[[dict[str, Any]], Any], seconds: float) -> None:
        """Pump events for a while, so screencast frames keep arriving."""
        deadline = time.monotonic() + seconds
        for pending in self.events:
            await _maybe_await(handler(pending))
        self.events.clear()
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                raw = await asyncio.wait_for(self.socket.recv(), timeout=remaining)
            except TimeoutError:
                return
            message = json.loads(raw)
            if "method" in message:
                await _maybe_await(handler(message))


async def _maybe_await(value: Any) -> None:
    if asyncio.iscoroutine(value):
        await value


class Recorder:
    """Collects screencast frames and writes a constant-rate MP4.

    Chrome emits a frame only when the page changes, so the raw stream has
    irregular gaps. Frames are timestamped and resampled at a fixed rate on the
    way out, otherwise a still moment would play back as a jump cut.
    """

    def __init__(self, fps: int = 10) -> None:
        self.fps = fps
        self.frames: list[Frame] = []
        self._started = time.monotonic()

    def add(self, png: bytes) -> None:
        self.frames.append(Frame(at=time.monotonic() - self._started, png=png))

    def write(self, destination: Path, tail_seconds: float = 1.0) -> Path | None:
        if not self.frames:
            return None
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise BrowserError("ffmpeg is not on PATH")

        destination.parent.mkdir(parents=True, exist_ok=True)
        duration = self.frames[-1].at + tail_seconds
        total = max(1, int(duration * self.fps))

        process = subprocess.Popen(
            [
                ffmpeg, "-y", "-loglevel", "error",
                "-f", "image2pipe", "-framerate", str(self.fps), "-i", "-",
                # yuv420p and an even-dimension filter, or the file will not
                # play in most players.
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                str(destination),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None
        index = 0
        try:
            for tick in range(total):
                moment = tick / self.fps
                while index + 1 < len(self.frames) and self.frames[index + 1].at <= moment:
                    index += 1
                process.stdin.write(self.frames[index].png)
            process.stdin.close()
        except BrokenPipeError:  # pragma: no cover - ffmpeg died; report below
            pass
        if process.wait() != 0:
            raise BrowserError(process.stderr.read().decode("utf-8", "replace")[:400])
        return destination


class Browser:
    """One headless Chrome tab, with the conveniences the scenarios need."""

    def __init__(self, cdp: Cdp, recorder: Recorder) -> None:
        self._cdp = cdp
        self._recorder = recorder

    async def _pump(self, seconds: float) -> None:
        async def handle(message: dict[str, Any]) -> None:
            if message.get("method") == "Page.screencastFrame":
                params = message["params"]
                self._recorder.add(base64.b64decode(params["data"]))
                await self._cdp.call("Page.screencastFrameAck", sessionId=params["sessionId"])

        await self._cdp.drain(handle, seconds)

    async def navigate(self, url: str, settle: float = 1.6) -> None:
        await self._cdp.call("Page.navigate", url=url)
        await self._pump(settle)

    async def evaluate(self, expression: str, settle: float = 0.6) -> Any:
        result = await self._cdp.call(
            "Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True
        )
        await self._pump(settle)
        if "exceptionDetails" in result:
            raise BrowserError(str(result["exceptionDetails"])[:300])
        return result.get("result", {}).get("value")

    async def click(self, selector: str, settle: float = 0.9) -> None:
        """A real click, so any handler bound to the element runs."""
        clicked = await self.evaluate(
            f"(() => {{ const el = document.querySelector({json.dumps(selector)});"
            f" if (!el) return false; el.click(); return true; }})()",
            settle=settle,
        )
        if not clicked:
            raise BrowserError(f"no element matched {selector!r}")

    async def fill(self, selector: str, value: str, settle: float = 0.5) -> None:
        """Set a value and fire the events a real keystroke would.

        `app.js` listens for `input` and `change`; assigning `.value` alone
        fires neither, so a test that skipped them would silently not exercise
        the behaviour it claims to.
        """
        # Built by concatenation rather than one f-string: the literal braces in
        # `new Event('input', {bubbles: true})` have to survive, and mixing
        # f-string and plain segments is how the escaping went wrong once.
        script = (
            "(() => { const el = document.querySelector("
            + json.dumps(selector)
            + "); if (!el) return false; el.value = "
            + json.dumps(value)
            + "; el.dispatchEvent(new Event('input', {bubbles: true}));"
            " el.dispatchEvent(new Event('change', {bubbles: true}));"
            " return true; })()"
        )
        ok = await self.evaluate(script, settle=settle)
        if not ok:
            raise BrowserError(f"no element matched {selector!r}")

    async def text(self) -> str:
        return str(await self.evaluate("document.body.innerText", settle=0.05))

    async def count(self, selector: str) -> int:
        return int(
            await self.evaluate(
                f"document.querySelectorAll({json.dumps(selector)}).length", settle=0.05
            )
        )

    async def visible(self, selector: str) -> bool:
        return bool(
            await self.evaluate(
                f"(() => {{ const el = document.querySelector({json.dumps(selector)});"
                " if (!el) return false; const style = getComputedStyle(el);"
                " return style.display !== 'none' && style.visibility !== 'hidden'"
                " && el.offsetParent !== null; })()",
                settle=0.05,
            )
        )

    async def values(self, selector: str) -> list[str]:
        return list(
            await self.evaluate(
                f"Array.from(document.querySelectorAll({json.dumps(selector)}))"
                ".map(el => el.value)",
                settle=0.05,
            )
            or []
        )

    async def pause(self, seconds: float) -> None:
        """Hold on screen, so a viewer can read what just happened."""
        await self._pump(seconds)


def start_chrome(profile: Path, port: int, width: int, height: int) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def devtools_url(port: int) -> str:
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json") as response:
                for target in json.load(response):
                    if target.get("type") == "page":
                        return str(target["webSocketDebuggerUrl"])
        except Exception:  # noqa: BLE001 - Chrome is still starting
            pass
        time.sleep(0.5)
    raise BrowserError("Chrome DevTools endpoint never appeared")


@dataclass
class Session:
    browser: Browser
    recorder: Recorder
    cdp: Cdp


async def record(
    scenario: Callable[[Browser], Any],
    video: Path,
    *,
    port: int = 9333,
    width: int = 1280,
    height: int = 900,
    session_cookie: tuple[str, str] | None = None,
    origin: str = "127.0.0.1",
) -> None:
    """Run one scenario against a fresh browser, writing an MP4 of it."""
    # Absolute: Chrome silently refuses a relative --user-data-dir and then
    # never opens the debugging port, which looks like a timeout rather than a
    # bad argument.
    video = video.resolve()
    profile = (video.parent / f".chrome-{video.stem}").resolve()
    chrome = start_chrome(profile, port, width, height)
    try:
        async with websockets.connect(
            devtools_url(port), max_size=200 * 1024 * 1024
        ) as socket:
            cdp = Cdp(socket=socket)
            await cdp.call("Page.enable")
            await cdp.call("Runtime.enable")
            await cdp.call("Network.enable")
            if session_cookie is not None:
                await cdp.call(
                    "Network.setCookie",
                    name=session_cookie[0],
                    value=session_cookie[1],
                    domain=origin,
                    path="/",
                    httpOnly=True,
                )
            recorder = Recorder()
            await cdp.call(
                "Page.startScreencast", format="png", maxWidth=width, maxHeight=height
            )
            browser = Browser(cdp, recorder)
            try:
                await scenario(browser)
            finally:
                await cdp.call("Page.stopScreencast")
                recorder.write(video)
    finally:
        chrome.terminate()
        shutil.rmtree(profile, ignore_errors=True)
