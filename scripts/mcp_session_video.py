"""Record an agent asking a question and getting an answer through `/mcp`.

    python scripts/mcp_session_video.py http://127.0.0.1:8300 fpa_... .e2e/videos

Every MCP exchange shown is real: the official `mcp` SDK client connects to the
running server, calls the tools, and the numbers come from the active model. The
transcript around them is scripted — this is not a language model reasoning, and
labelling it as one would misrepresent what the recording proves.

What it does prove is the thing the acceptance criterion asks for: an agent can
discover the tools, ask a question in the domain, and get an answer it can act
on, including the caveat that the figure is fuel to *prepare* rather than fuel
consumed.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_harness import Browser, record  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

_PAGE = """
<!doctype html><html lang="id"><head><meta charset="utf-8"><title>Sesi Agen · MCP</title>
<style>
 :root{--bg:#0f1720;--panel:#16212c;--line:#24333f;--ink:#e6edf3;--muted:#8fa3b3;
       --user:#2f81f7;--tool:#d29922;--ok:#3fb950}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);
      font:15px/1.65 "Segoe UI",system-ui,sans-serif}
 header{padding:14px 22px;border-bottom:1px solid var(--line);display:flex;
        align-items:center;gap:10px;background:var(--panel)}
 header b{font-size:15px} header span{color:var(--muted);font-size:13px}
 .dot{width:9px;height:9px;border-radius:50%;background:var(--ok)}
 main{padding:20px 22px;max-width:980px}
 .turn{margin:0 0 14px;padding:12px 16px;border-radius:10px;background:var(--panel);
       border:1px solid var(--line);opacity:0;transform:translateY(6px);
       animation:in .35s ease forwards}
 @keyframes in{to{opacity:1;transform:none}}
 .who{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);
      margin-bottom:6px}
 .user .who{color:var(--user)} .tool .who{color:var(--tool)}
 pre{margin:6px 0 0;padding:10px 12px;background:#0c1218;border:1px solid var(--line);
     border-radius:8px;overflow-x:auto;font:12.5px/1.5 "Cascadia Mono",Consolas,monospace;
     color:#cdd9e5;white-space:pre-wrap;word-break:break-word}
 .answer{border-left:3px solid var(--ok)}
 .note{color:var(--muted);font-size:12.5px;margin-top:8px}
</style></head><body>
<header><span class="dot"></span><b>Sesi Agen</b>
<span id="target"></span></header><main id="log"></main></body></html>
"""


def _turn_script(kind: str, who: str, body: str, code: str | None, note: str | None) -> str:
    payload = json.dumps(
        {"kind": kind, "who": who, "body": body, "code": code, "note": note}
    )
    return (
        "(() => { const t = " + payload + ";"
        " const el = document.createElement('div');"
        " el.className = 'turn ' + t.kind;"
        " let html = '<div class=\"who\">' + t.who + '</div><div>' + t.body + '</div>';"
        " if (t.code) html += '<pre>' + t.code + '</pre>';"
        " if (t.note) html += '<div class=\"note\">' + t.note + '</div>';"
        " el.innerHTML = html;"
        " document.getElementById('log').appendChild(el);"
        " window.scrollTo(0, document.body.scrollHeight); })()"
    )


async def build(base: str, token: str, video: Path) -> int:
    """Run the real MCP exchange, drawing each step into the page as it happens."""
    page_file = video.parent / "sesi-agen.html"
    page_file.parent.mkdir(parents=True, exist_ok=True)
    page_file.write_text(_PAGE, encoding="utf-8")
    failures: list[str] = []

    async def scenario(page: Browser) -> None:
        await page.navigate(page_file.resolve().as_uri(), settle=1.0)
        await page.evaluate(
            f"document.getElementById('target').textContent = {json.dumps(base + '/mcp')}",
            settle=0.2,
        )

        async def turn(
            kind: str, who: str, body: str, code: str | None = None, note: str | None = None,
            hold: float = 1.4,
        ) -> None:
            await page.evaluate(_turn_script(kind, who, body, code, note), settle=0.25)
            await page.pause(hold)

        await turn(
            "user", "Operator",
            "Berapa bahan bakar yang perlu disiapkan untuk ANGBER besok: "
            "35 km, angkut sekaligus lifting 2 jam?",
            hold=2.0,
        )

        async with streamablehttp_client(
            f"{base}/mcp", headers={"Authorization": f"Bearer {token}"}
        ) as (read, write, _), ClientSession(read, write) as session:
            info = await session.initialize()
            await turn(
                "tool", "MCP · initialize",
                f"Terhubung ke <b>{info.serverInfo.name}</b> versi {info.serverInfo.version}.",
                note="Klien resmi MCP, bukan permintaan HTTP buatan sendiri.",
            )

            tools = [tool.name for tool in (await session.list_tools()).tools]
            await turn(
                "tool", "MCP · tools/list",
                f"{len(tools)} alat tersedia untuk kredensial ini.",
                code="\n".join(f"· {name}" for name in tools),
                note="Daftar disaring menurut cakupan kredensial.",
                hold=2.2,
            )
            if not tools:
                failures.append("tools/list returned nothing")

            schema = json.loads(
                (await session.call_tool("get_prediction_input_schema", {})).content[0].text
            )
            await turn(
                "tool", "MCP · get_prediction_input_schema",
                "Memastikan bentuk masukan sebelum memanggil prediksi.",
                code=json.dumps(schema["required"], ensure_ascii=False),
            )

            arguments: dict[str, Any] = {
                "vehicle_category": "ANGBER",
                "activity_mode": "transport_and_lifting",
                "lifting_hours": 2,
                "total_distance_km": 35,
            }
            await turn(
                "tool", "MCP · tools/call → predict_fuel",
                "Memanggil alat prediksi.",
                code=json.dumps(arguments, indent=2, ensure_ascii=False),
            )

            result = await session.call_tool("predict_fuel", arguments)
            if result.isError:
                failures.append(f"predict_fuel failed: {result.content[0].text}")
                await turn("tool", "MCP · error", result.content[0].text)
                return
            prediction = json.loads(result.content[0].text)
            await turn(
                "tool", "MCP · hasil",
                "Jawaban dari model yang sedang aktif.",
                code=json.dumps(prediction, indent=2, ensure_ascii=False)[:900],
                hold=3.0,
            )

            model = json.loads(
                (await session.call_tool("get_current_model", {})).content[0].text
            )
            await turn(
                "tool", "MCP · get_current_model",
                "Menelusuri model yang menghasilkan angka itu.",
                code=f"{model['model_version_id']} · {model['algorithm']}",
            )

            allocation = prediction["recommended_allocation_liters"]
            estimate = prediction["estimated_fuel_requirement_liters"]
            lower = prediction["uncertainty_interval_liters"]["lower"]
            upper = prediction["uncertainty_interval_liters"]["upper"]
            await turn(
                "user answer", "Jawaban untuk operator",
                f"Siapkan <b>{allocation:.1f} L</b>. Estimasi kebutuhan "
                f"{estimate:.1f} L, rentang wajar {lower:.1f}–{upper:.1f} L.",
                note=prediction["safety_policy"],
                hold=4.0,
            )
            failures.extend(
                [] if estimate > 0 and prediction["safety_policy"] else ["implausible answer"]
            )

    await record(scenario, video, port=9360, width=1180, height=820)
    page_file.unlink(missing_ok=True)
    for failure in failures:
        print(f"  FAIL  {failure}")
    print("  PASS  the agent asked, MCP answered" if not failures else "  FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    base, token, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    raise SystemExit(asyncio.run(build(base, token, out / "07-sesi-agen-mcp.mp4")))
