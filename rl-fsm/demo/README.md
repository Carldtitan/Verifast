# FSM demo — fine-tuned DSL vs base Verilog (side by side)

Same spec → two models → a Verilator verifier scores both, with verbose metrics
(reward breakdown, tokens, latency, tokens/sec).

- **Left / DSL arm**: the **fine-tuned** model (`fsm-rl`) writes our FSM-DSL; a frozen
  transpiler turns it into SystemVerilog.
- **Right / Verilog arm**: an **un-fine-tuned base** model (`Qwen/Qwen3-8B`) writes raw
  SystemVerilog.

Both outputs are graded by `grader.py`: `reward = 0.2·compiles + 0.1·lint-clean + 0.7·behaviour-matches-golden` (Verilator cosim vs a hidden golden).

---

## What you (the teammate) need

1. **A HUD API key that can see the `fsm-rl` model.**
   The fine-tuned model is **hosted on HUD's gateway** (there is no weights file to copy).
   To call it you need a HUD key on the team that owns `fsm-rl`. Ask the owner to either:
   - add you to their HUD team/org (then your own `hud login` key works), **or**
   - share a HUD API key (`sk-hud-...`).
   Set it: `export HUD_API_KEY=sk-hud-...`  (Windows: `setx HUD_API_KEY sk-hud-...`)

2. **Python 3.10+** and the deps:  `pip install -r requirements.txt`

3. **Verilator** on PATH (the verifier needs it):
   - Ubuntu/WSL: `sudo apt-get install -y verilator`
   - macOS: `brew install verilator`
   - or the OSS CAD Suite: https://github.com/YosysHQ/oss-cad-suite-build/releases
   Check: `verilator --version`

That's it — **no access to any other account** (no Modal, no HF, no AWS). Only a HUD key.

---

## How to call the fine-tuned model (the whole trick)

It's an OpenAI-compatible endpoint. Point the OpenAI SDK at HUD's gateway:

```python
from openai import OpenAI
client = OpenAI(base_url="https://inference.beta.hud.ai", api_key="sk-hud-...")
resp = client.chat.completions.create(
    model="fsm-rl",                      # <- the fine-tuned model (or "Qwen/Qwen3-8B" for base)
    messages=[{"role": "user", "content": "...spec..."}],
    max_tokens=700, temperature=0.0,
)
print(resp.choices[0].message.content)
print(resp.usage)                        # prompt/completion/total tokens
```

`model="fsm-rl"` = your fine-tuned model. `model="Qwen/Qwen3-8B"` = the base. Same key, same URL.

---

## Run it

Terminal, side-by-side, verbose:
```bash
export HUD_API_KEY=sk-hud-...
python compare.py                    # random task
python compare.py --task task_0003   # specific spec
```

Two-panel “dual IDE” web UI:
```bash
export HUD_API_KEY=sk-hud-...
streamlit run app.py                 # opens http://localhost:8501
```
Pick a task, hit **Run both** — left panel shows fine-tuned DSL, right shows base Verilog,
each with its verifier score and token/latency/speed metrics.

---

## Files
- `core.py` — gateway client, prompt builders, transpile, grade, timing (shared).
- `compare.py` — terminal side-by-side.
- `app.py` — Streamlit two-panel UI.
- `grader.py` — Verilator cosim verifier.
- `transpiler/` — the frozen FSM-DSL → SystemVerilog compiler.
- `tasks/` — sample specs (`prompt.txt`) + hidden goldens (`golden.sv`) + DSL `examples/`.
