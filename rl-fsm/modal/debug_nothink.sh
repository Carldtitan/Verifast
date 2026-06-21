#!/bin/bash
export HOME=/home/agent
PY=/home/agent/fsm/.venv/bin/python
cd /home/agent/hud-env
"$PY" - <<'PY'
import asyncio, sys
sys.path.insert(0, ".")
from pathlib import Path
from hud.settings import settings
from openai import AsyncOpenAI
import env as E
from grader import grade

base = Path("task_data/train/task_0000/prompt.txt").read_text()
gold = Path("task_data/train/task_0000/golden.sv").read_text()
guide = E._dsl_guide()
def mk(p): return f"{guide}\n\n---\nNow write an FSM-DSL program for this specification.\nOutput ONLY a ```fsm code block.\n\n{p}"

client = AsyncOpenAI(base_url=settings.hud_gateway_url, api_key=settings.api_key)

async def trial(name, **kw):
    try:
        r = await client.chat.completions.create(model="fsm-rl",
            messages=[{"role":"user","content":kw.pop("prompt")}],
            max_tokens=kw.pop("max_tokens",1200), temperature=0.7, **kw)
        txt = r.choices[0].message.content or ""
        m = E._FENCE_FSM.search(txt)
        src = (m.group(1) if m else txt).strip()
        sv = E._transpile(src)
        g = grade(sv, gold) if sv else None
        print(f"[{name}] len={len(txt)} has_think={'<think>' in txt} transpile={sv is not None} grade={g}")
    except Exception as e:
        print(f"[{name}] ERROR {e!r}")

async def main():
    await trial("A_enable_thinking_false", prompt=mk(base),
                extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    await trial("B_no_think_tag", prompt=mk(base)+" /no_think")
    await trial("C_big_budget", prompt=mk(base), max_tokens=2500)

asyncio.run(main())
PY
