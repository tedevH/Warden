"""Local text harness: talk to Lend by typing. Same tools as the FaceTime agent, no Chert needed.

    python -m agent.harness              Grok decides what to do (needs LIVEKIT_* in .env.local)
    python -m agent.harness --no-llm     keyword routing only (no keys at all)

Type what the caller would say. Extras: /button = press the approve button, /quit.
"""
import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

from agent.prompts import INSTRUCTIONS  # noqa: E402
from agent.tools import LendTools  # noqa: E402

TOOLS = {
    "start_task": ("Do something on a website for the caller (email, bank, food order, open a link).",
                   {"goal": {"type": "string"}}),
    "confirm": ("Record the caller's spoken yes for the approval you just read out.", {}),
    "wait_for_approval": ("After asking them to press their approve button, wait until they press it.", {}),
    "cancel_task": ("Stop whatever Lend is doing.", {}),
    "check_accounts": ("Review bank and email for unusual charges, sign-ins and scam emails.", {}),
    "read_paper": ("Look at a letter or screen held up to the camera and say if it's a scam.", {}),
    "send_screenshot": ("Text a large, high-contrast picture of the current page.", {}),
}


def say(text):
    print(f"\n🔊 Lend: {text}", flush=True)


async def call(tools: LendTools, name, args):
    fn = {"cancel_task": tools.cancel}.get(name) or getattr(tools, name)
    return await (fn(args.get("goal", "")) if name == "start_task" else fn())


def route(text):
    """Keyword routing for --no-llm mode."""
    import re
    t = text.lower().strip()
    if re.fullmatch(r"(yes|yeah|yep|ok|okay|sure|go ahead|do it|approve)[.! ]*", t):
        return "confirm"
    if re.search(r"\b(stop|cancel|never mind)\b", t):
        return "cancel_task"
    if re.search(r"check (my )?accounts?|anything (unusual|wrong)|account check", t):
        return "check_accounts"
    if re.search(r"letter|paper|is this a scam|look at this", t):
        return "read_paper"
    if re.search(r"screenshot|bigger|can'?t see|picture of", t):
        return "send_screenshot"
    return "start_task"


async def llm_turn(model, ctx, defs, tools, text):
    from livekit.agents import APIConnectOptions, llm
    ctx.add_message(role="user", content=text)
    for _ in range(6):
        calls, out = [], []
        async with model.chat(chat_ctx=ctx, tools=defs,
                              conn_options=APIConnectOptions(max_retry=2, timeout=60.0)) as stream:
            async for chunk in stream:
                if chunk.delta:
                    out.append(chunk.delta.content or "")
                    calls.extend(chunk.delta.tool_calls or [])
        reply = "".join(out).strip()
        if not calls:
            ctx.add_message(role="assistant", content=reply)
            return reply
        for c in calls:
            try:
                args = json.loads(c.arguments or "{}")
            except ValueError:
                args = {}
            print(f"   [tool] {c.name}({args.get('goal', '')})", flush=True)
            result = await call(tools, c.name, args) if c.name in TOOLS else f"Unknown tool {c.name}"
            cid = c.call_id or uuid.uuid4().hex
            ctx.items.append(llm.FunctionCall(call_id=cid, name=c.name, arguments=c.arguments or "{}"))
            ctx.items.append(llm.FunctionCallOutput(call_id=cid, name=c.name, output=result, is_error=False))
    return "Sorry, I got stuck. Please ask again."


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--say", action="append", help="scripted lines instead of typing (repeatable)")
    args = ap.parse_args()
    use_llm = not args.no_llm and all(os.getenv(k) for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))

    scripted = list(args.say or [])

    async def press():
        if scripted and scripted[0] == "/button":
            scripted.pop(0)
            await asyncio.sleep(1)
        elif args.say:
            return
        else:
            await asyncio.to_thread(input, "   (press Enter to press the approve button) ")
        r = (await tools.http.post("/button", json={"user_id": tools.user_id})).json()
        print("   [button]", "press received" if r.get("applied") else "nothing was waiting", flush=True)

    async def say_and_maybe_press(text):
        say(text)
        if "approve button" in text.lower():
            asyncio.create_task(press())

    tools = LendTools(say=say_and_maybe_press, on_narration=lambda line: print(f"   · {line}", flush=True))
    try:
        await tools.settings()
    except Exception:
        sys.exit(f"The orchestrator isn't running at {tools.base}. Start it with: make orchestrator")
    await tools.presence(True)

    model = ctx = defs = None
    if use_llm:
        from livekit.agents import inference, llm

        async def _noop(raw_arguments: dict):
            return None

        defs = [llm.function_tool(_noop, raw_schema={"name": n, "description": d, "parameters": {
            "type": "object", "properties": p, "required": list(p)}}) for n, (d, p) in TOOLS.items()]
        model = inference.LLM(model=os.getenv("LEND_VOICE_LLM", "xai/grok-4.3"))
        ctx = llm.ChatContext()
        ctx.add_message(role="system", content=INSTRUCTIONS)
    print(f"Lend text harness ({'Grok voice brain' if use_llm else 'keyword mode'}). "
          f"Type what the caller says. /button presses the approve button. /quit exits.")
    say("Hi, I'm Lend, your online safety helper. What would you like help with today?")
    try:
        while True:
            if scripted:
                text = scripted.pop(0)
                print(f"\nyou> {text}", flush=True)
            elif args.say:
                break
            else:
                text = (await asyncio.to_thread(input, "\nyou> ")).strip()
            if not text:
                continue
            if text == "/quit":
                break
            if text == "/button":
                r = (await tools.http.post("/button", json={"user_id": tools.user_id})).json()
                print("   [button]", "press received" if r.get("applied") else "nothing was waiting", flush=True)
                continue
            if use_llm:
                say(await llm_turn(model, ctx, defs, tools, text))
            else:
                name = route(text)
                print(f"   [tool] {name}", flush=True)
                say(await call(tools, name, {"goal": text}))
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        await tools.presence(False)
        if model:
            await model.aclose()


if __name__ == "__main__":
    asyncio.run(main())
