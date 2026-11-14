"""Grok planner for the browser worker, via LiveKit Inference (your LIVEKIT_API_KEY/SECRET; no xAI key).

Same tools, safety gate, vault and untrusted-content wrapping as the Claude planner. Only the brain differs.
    LEND_PLANNER=grok (default) | claude
    LEND_GROK_MODEL=xai/grok-4.3
"""
import asyncio
import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import APIConnectOptions, inference, llm

from .observe import format_for_llm
from .session import Blocked, GuardStop
from .skills import SKILLS

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)
MODEL = os.getenv("LEND_GROK_MODEL", "xai/grok-4.3")
OLD_PAGE = "(older page snapshot removed to save space; call read_page if you need it again)"


def _schema(name, desc, props=None, required=None):
    params = {"type": "object", "properties": props or {}, "required": required or list((props or {}).keys())}

    async def _noop(raw_arguments: dict):  # we execute tools ourselves; this only carries the schema
        return None

    return llm.function_tool(_noop, raw_schema={"name": name, "description": desc, "parameters": params})


def _tool_defs(use_skills):
    s = {"type": "string"}
    defs = [
        _schema("goto", "Open a URL in the browser.", {"url": s}),
        _schema("click", "Click an element by its [ref].", {"ref": s}),
        _schema("type", "Type text into a text field by [ref] (never passwords or codes).", {"ref": s, "text": s}),
        _schema("select", "Choose a dropdown option by [ref] and option label.", {"ref": s, "option": s}),
        _schema("back", "Go back one page."),
        _schema("read_page", "Re-read the current page (text and element refs)."),
        _schema("scroll", "Scroll down and re-read the page."),
        _schema("login", "Sign in on the current page with the saved login for this exact site."),
        _schema("done", "Finish with a short spoken-style summary for the person.", {"summary": s}),
        _schema("need_user", "Stop and ask the person a question.", {"question": s}),
    ]
    if use_skills:
        listing = "; ".join(f"{k}: {v[1]}" for k, v in SKILLS.items())
        defs.append(_schema("run_skill", f"Run a scripted flow. Available: {listing}",
                            {"name": s, "args": {"type": "object", "description": "arguments for the skill"}},
                            required=["name"]))
    return defs


async def _execute(session, result, name, args, max_steps):
    """Run one tool call; return (text_for_model, finished)."""
    if name == "done":
        if result.status == "running":
            result.status, result.summary = "done", args.get("summary", "")
        return "Recorded. Stop now.", True
    if name == "need_user":
        if result.status == "running":
            result.status, result.question = "needs_user", args.get("question", "")
        return "Question recorded. Stop now.", True
    if result.status == "blocked":
        return "The task was stopped for safety. Call done() repeating the explanation.", False
    result.steps += 1
    if result.steps > max_steps:
        return f"Step limit ({max_steps}) reached. Call done() now.", False
    ops = {
        "goto": lambda: session.goto(args["url"]),
        "click": lambda: session.click(args["ref"]),
        "type": lambda: session.type(args["ref"], args["text"]),
        "select": lambda: session.select(args["ref"], args["option"]),
        "back": session.back,
        "read_page": session.observe,
        "login": session.login,
    }

    async def _scroll():
        await session.page.mouse.wheel(0, 800)
        return await session.observe()

    ops["scroll"] = _scroll
    if name == "run_skill":
        skill = SKILLS.get(args.get("name"))
        if not skill:
            return f"Unknown skill {args.get('name')!r}.", False
        session.narrate(f"Using the {args['name'].replace('_', ' ')} routine")
        ops["run_skill"] = lambda: skill[0](session, **(args.get("args") or {}))
    if name not in ops:
        return f"Unknown tool {name}.", False
    try:
        out = await ops[name]()
        return (out if isinstance(out, str) else format_for_llm(out)), False
    except GuardStop as g:
        result.status, result.summary = "blocked", g.verdict.get("plain_explanation") or str(g)
        session.narrate(f"Stopped for safety: {result.summary}")
        return f"STOPPED BY WARDEN GUARD: {result.summary} The task is over. Call done() and say this.", False
    except Blocked as e:
        result.blocked.append(str(e))
        session.narrate(f"Blocked: {e}")
        return f"BLOCKED BY SAFETY GATE: {e}", False
    except KeyError as e:
        return f"Missing argument {e} for {name}.", False
    except Exception as e:
        return f"Action failed: {e.__class__.__name__}: {str(e)[:300]}", False


async def run_task_grok(goal, session, result, system_prompt, use_skills, max_steps, on_text=None):
    model = inference.LLM(model=MODEL)
    tools = _tool_defs(use_skills)
    start = await session.observe()
    ctx = llm.ChatContext()
    ctx.add_message(role="system", content=system_prompt)
    ctx.add_message(role="user", content=f"The person asked: {goal!r}\n\nThe browser is on: "
                                         f"{start.url or 'a blank page'}.\nDo the task, then call done() or need_user().")
    outputs = []
    for _ in range(max_steps + 10):
        calls, text = [], []
        stream = model.chat(chat_ctx=ctx, tools=tools, tool_choice="required",
                            conn_options=APIConnectOptions(max_retry=2, timeout=60.0))
        async with stream:
            async for chunk in stream:
                if chunk.delta:
                    if chunk.delta.content:
                        text.append(chunk.delta.content)
                    calls.extend(chunk.delta.tool_calls or [])
        if text and on_text:
            on_text("".join(text).strip())
        if not calls:
            if result.status == "running":
                result.status, result.summary = "done", "".join(text).strip()
            break
        finished = False
        for c in calls:
            try:
                args = json.loads(c.arguments or "{}")
            except ValueError:
                args = {}
            out, fin = await _execute(session, result, c.name, args, max_steps)
            call_id = c.call_id or uuid.uuid4().hex
            ctx.items.append(llm.FunctionCall(call_id=call_id, name=c.name, arguments=c.arguments or "{}"))
            for o in outputs:  # keep only the newest page snapshot in full
                if o.output.startswith("Current page:") or "<untrusted_page_content" in o.output:
                    o.output = OLD_PAGE
            fco = llm.FunctionCallOutput(call_id=call_id, name=c.name, output=out, is_error=False)
            ctx.items.append(fco)
            outputs.append(fco)
            finished = finished or fin
        if finished:
            break
    await model.aclose()
    return result
