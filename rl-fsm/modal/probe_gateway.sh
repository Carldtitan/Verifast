#!/bin/bash
export HOME=/home/agent
PY=/home/agent/fsm/.venv/bin/python
cd /home/agent/hud-env
"$PY" - <<'PY'
import time
from hud.settings import settings
from openai import OpenAI
print("hud_gateway_url =", settings.hud_gateway_url)
client = OpenAI(base_url=settings.hud_gateway_url, api_key=settings.api_key)
for model in ("fsm-rl", "Qwen/Qwen3-8B"):
    t0 = time.time()
    r = client.chat.completions.create(model=model,
        messages=[{"role":"user","content":"Reply with the single word OK. /no_think"}],
        max_tokens=20, temperature=0.0)
    dt = time.time()-t0
    u = r.usage
    print(f"\nmodel={model}")
    print("  text:", repr((r.choices[0].message.content or '')[:60]))
    print("  usage:", u.prompt_tokens, u.completion_tokens, u.total_tokens)
    print(f"  latency={dt:.2f}s  tok/s={ (u.completion_tokens/dt) if dt else 0:.1f}")
PY
