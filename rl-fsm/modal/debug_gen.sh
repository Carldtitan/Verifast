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

base = (Path("task_data/train/task_0000/prompt.txt")).read_text()
guide = E._dsl_guide()
prompt = f"{guide}\n\n---\nNow write an FSM-DSL program for this specification.\nOutput ONLY a ```fsm code block.\n\n{base}"

async def main():
    print("gateway url candidates:",
          getattr(settings, "hud_gateway_url", None),
          getattr(settings, "gateway_url", None),
          getattr(settings, "hud_api_url", None))
    url = getattr(settings, "hud_gateway_url", None) or "https://api.beta.hud.ai/v1/gateway"
    client = AsyncOpenAI(base_url=url, api_key=settings.api_key)
    for think in (None,):
        r = await client.chat.completions.create(
            model="fsm-rl",
            messages=[{"role":"user","content":prompt}],
            max_tokens=900, temperature=0.7,
        )
        txt = r.choices[0].message.content or ""
        print("===== RAW COMPLETION (len", len(txt), ") =====")
        print(txt[:2000])
        print("===== PARSE+GRADE =====")
        m = E._FENCE_FSM.search(txt)
        src = (m.group(1) if m else txt).strip()
        sv = E._transpile(src)
        print("transpile ok?", sv is not None)
        if sv:
            gold = Path("task_data/train/task_0000/golden.sv").read_text()
            from grader import grade
            print("grade:", grade(sv, gold))

asyncio.run(main())
PY
