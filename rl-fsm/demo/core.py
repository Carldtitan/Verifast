"""Shared demo logic: call a HUD-gateway model, build hardware, grade it, time it.

Two arms, same spec:
  * DSL arm     -> model writes FSM-DSL, we transpile to SystemVerilog, then cosim.
  * Verilog arm -> model writes SystemVerilog directly, then cosim.

The reward (0..1) = 0.2*compiles + 0.1*lint-clean + 0.7*behaviour-matches-golden,
computed by grader.py via Verilator. Everything needed to call the fine-tuned model
is a HUD API key + the gateway URL below — no other accounts.
"""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from grader import grade                          # noqa: E402
from transpiler.parser import parse               # noqa: E402
from transpiler.ast import build_ast              # noqa: E402
from transpiler.safety import check               # noqa: E402
from transpiler.codegen import generate as gen_sv  # noqa: E402

# --- HUD gateway (OpenAI-compatible). Your teammate sets HUD_API_KEY only. --------
GATEWAY_URL = "https://inference.beta.hud.ai"
DSL_MODEL_DEFAULT = "fsm-rl"          # your fine-tuned model (private to your HUD team)
VERILOG_MODEL_DEFAULT = "Qwen/Qwen3-8B"  # the un-fine-tuned base, same family

_FENCE_FSM = re.compile(r"```(?:fsm|dsl)?\s*(.*?)```", re.DOTALL)
_FENCE_SV = re.compile(r"```(?:systemverilog|verilog|sv)?\s*(.*?)```", re.DOTALL)

_GUIDE_HEAD = (
    "FSM-DSL quick reference:\n"
    "- machine NAME { ... }  (clk/rst implicit, never declared)\n"
    "- in TYPE name / out TYPE name  (TYPE = bit or bit[H:L])\n"
    "- reset = STATE\n"
    "- state NAME { output assignments first, then transitions }\n"
    "- output assignment:  name = INT\n"
    "- transition:  when COND -> STATE (priority), then a MANDATORY  else -> STATE\n"
    "- COND over inputs: bare x, x==k, x!=k, x[i], with && || ! ( )\n"
    "Rules: assign every output in every state; every state ends with else -> STATE.\n\nExamples:\n"
)


def client(api_key: str | None = None) -> OpenAI:
    import os
    key = api_key or os.environ.get("HUD_API_KEY")
    if not key:
        raise SystemExit("Set HUD_API_KEY (export HUD_API_KEY=sk-hud-...) — needed to call the model.")
    return OpenAI(base_url=GATEWAY_URL, api_key=key)


def dsl_guide() -> str:
    ex = "\n\n".join((ROOT / "tasks" / "examples" / f"{n}.fsm").read_text(encoding="utf-8")
                     for n in ("seq_detect_101", "traffic_light", "handshake"))
    return _GUIDE_HEAD + ex


def dsl_prompt(spec: str) -> str:
    return (f"{dsl_guide()}\n\n---\nNow write an FSM-DSL program for this specification. "
            f"Output ONLY a ```fsm code block.\n\n{spec}\n\n/no_think")


def verilog_prompt(spec: str) -> str:
    return ("You are an expert hardware engineer. Write only synthesizable SystemVerilog "
            "inside a ```systemverilog code block.\n\n" + spec + "\n\n/no_think")


def transpile(src: str) -> str | None:
    try:
        p = build_ast(parse(src, file="<demo>"), source_file="<demo>")
        return None if check(p) else gen_sv(p.machines[0])
    except Exception:
        return None


@dataclass
class ArmResult:
    arm: str                 # "DSL" or "Verilog"
    model: str
    raw_output: str = ""
    code: str | None = None  # the SystemVerilog actually graded (transpiled or raw)
    reward: float = 0.0
    parts: dict = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0

    @property
    def tokens_per_s(self) -> float:
        return self.completion_tokens / self.latency_s if self.latency_s else 0.0

    @property
    def passed(self) -> bool:
        return self.reward >= 0.999


def run_arm(cli: OpenAI, arm: str, model: str, spec: str, golden: str,
            max_tokens: int = 700, temperature: float = 0.0) -> ArmResult:
    prompt = dsl_prompt(spec) if arm == "DSL" else verilog_prompt(spec)
    t0 = time.time()
    resp = cli.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens, temperature=temperature)
    latency = time.time() - t0
    text = resp.choices[0].message.content or ""
    u = resp.usage

    if arm == "DSL":
        m = _FENCE_FSM.search(text)
        sv = transpile((m.group(1) if m else text).strip())
    else:
        m = _FENCE_SV.search(text)
        sv = (m.group(1) if m else text).strip() or None

    res = ArmResult(arm=arm, model=model, raw_output=text, code=sv,
                    prompt_tokens=getattr(u, "prompt_tokens", 0),
                    completion_tokens=getattr(u, "completion_tokens", 0),
                    latency_s=latency)
    if sv:
        try:
            g = grade(sv, golden)
            res.reward, res.parts = g["reward"], g["parts"]
        except Exception:
            pass
    return res


def list_tasks() -> list[str]:
    return sorted(d.name for d in (ROOT / "tasks").glob("task_*") if d.is_dir())


def load_task(name: str) -> tuple[str, str]:
    base = ROOT / "tasks" / name
    return (base / "prompt.txt").read_text(encoding="utf-8"), (base / "golden.sv").read_text(encoding="utf-8")
