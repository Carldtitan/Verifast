# Verifast

**Teach an AI to write hardware that's correct by construction — then train it to get better.**

Verifast tests one idea: an LLM writes correct digital hardware far more often
when it targets a small, purpose-built language than when it writes raw Verilog —
and you can *reinforcement-train* an open model to widen that gap. The trick is to
make the classic Verilog footguns — inferred latches, blocking/non-blocking
misuse, reset bugs, multiple drivers, hand-rolled state codes — **inexpressible in
the language** and **impossible in the generated output**.

Built at the **HUD Frontier / RSI RL Environments Hackathon** (YC). The
recursive-self-improvement angle: build an environment that teaches a model a
capability you can *verify*, then let the verifier drive the model's improvement.

---

## The two halves

| Component | What it is |
| --- | --- |
| [`fsm-dsl-transpiler/`](fsm-dsl-transpiler/) | **FSM_DSL** — a tiny, AI-native HDL for Moore finite state machines, plus a **frozen** Python transpiler that emits lint-clean, latch-free SystemVerilog. |
| [`rl-fsm/`](rl-fsm/) | The **RL pipeline** — fine-tunes `Qwen2.5-Coder-7B` with GRPO to write better FSM hardware, using a Verilator/Yosys grader as the reward. Orchestrated with **HUD** (rollouts, reward, advantages, eval) + **Modal** (GPU serve + weight update). |
| [`rl-fsm/demo/`](rl-fsm/demo/) | A side-by-side demo: same spec → fine-tuned model writes FSM_DSL vs. a base model writes raw Verilog → a Verilator verifier scores both live. |

```
                     ┌─────────────────────────────────────────────┐
   English spec ───▶ │  Model writes FSM_DSL  ──▶ frozen transpiler │ ──▶ SystemVerilog
                     └─────────────────────────────────────────────┘            │
                                                                                 ▼
                          reward 0..1  ◀──  Verilator / Yosys grader  ◀──  golden co-sim
                               │
                               ▼
                     GRPO weight update (HUD advantages + Modal GPUs) ──▶ better model
```

---

## Why it's credible: correctness is *measured*, not asserted

- **Frozen transpiler.** Once validated, the FSM_DSL → SystemVerilog compiler is
  frozen (see [`fsm-dsl-transpiler/FROZEN.md`](fsm-dsl-transpiler/FROZEN.md)). Any
  change in model pass-rate is attributable to the *language or the model* — never
  to transpiler drift.
- **24 correctness properties** verified with property-based tests (Hypothesis).
- **Golden co-simulation** — every generated module is checked cycle-for-cycle
  against a hand-written oracle for ≥ 1000 deterministically-seeded cycles.
- **Lint-clean** (`verilator --lint-only -Wall`, zero warnings) and **latch-free**
  (Yosys synthesis, `$dlatch` count == 0).
- **Calibrated reward** — golden solution scores `1.0`, a behaviorally-broken one
  scores `0.3`, so the RL signal is meaningful.

---

## The language in one example

The overlapping **"101" sequence detector** — you write *what* the machine does;
the transpiler owns *how* it becomes hardware (state encoding, clocking, reset,
the canonical three-always-block structure):

```
machine seq_detect_101 {
  in  bit x          # serial input bit
  out bit y          # 1 only when a "101" completes

  reset = S0

  state S0 { y = 0  when x -> S1  else -> S0 }
  state S1 { y = 0  when x -> S1  else -> S2 }
  state S2 { y = 0  when x -> S3  else -> S0 }
  state S3 { y = 1  when x -> S1  else -> S2 }
}
```

Seven constructs, two types (`bit`, `bit[H:L]`), implicit `clk`/`rst`, Moore
semantics. Full reference: [`fsm-dsl-transpiler/spec/LANGUAGE_SPEC.md`](fsm-dsl-transpiler/spec/LANGUAGE_SPEC.md).

---

## Quick start

Requires **Python 3.12** and [`uv`](https://docs.astral.sh/uv/). The transpiler's
only runtime dependency is [`lark`](https://github.com/lark-parser/lark).

```bash
cd fsm-dsl-transpiler
uv sync
uv run python -m transpiler.transpile examples/seq_detect_101.fsm > out.sv
uv run pytest                              # full property + golden suite
```

Tool-bound gates (lint / latch / golden co-sim) need the OSS CAD Suite on `PATH`;
they skip cleanly when absent. To require them: `FSM_REQUIRE_TOOLS=1 uv run pytest`.

For the RL pipeline and the side-by-side demo, see [`rl-fsm/README.md`](rl-fsm/README.md)
and [`rl-fsm/demo/README.md`](rl-fsm/demo/README.md).

---

## How the experiment is designed

- **Train** on unlimited synthetic FSMs — a generator produces a templated English
  spec plus a golden reference (via the frozen transpiler).
- **Evaluate** on held-out, real FSM problems so the curve is honest.
- RL needs only **tasks + a checker** — reference solutions are never handed to the
  model.
- **Success criterion:** held-out **pass@1 after RL > pass@1 before RL**, on tasks
  never trained on. Result charts live in [`rl-fsm/charts/`](rl-fsm/charts/).

---

## Repository layout

```
.
├── fsm-dsl-transpiler/   # FSM_DSL language + frozen transpiler + tests + spec
├── rl-fsm/               # RL training: HUD env, Modal GPU jobs, grader, charts, demo
└── verilog-template/     # HUD Verilog evaluation harness / reference tasks
```

## Status

FSM_DSL v0.1 — language design and a tool-validated, frozen transpiler are complete.
The RL environment, reward grader, and Modal training jobs are wired; see each
subproject's README for the live build status.
