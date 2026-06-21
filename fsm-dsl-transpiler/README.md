# FSM_DSL

**A tiny, AI-native hardware description language for Moore finite state machines, with a frozen Python transpiler that emits lint-clean, latch-free SystemVerilog.**

You write *what* a machine does — its states, per-state outputs, and transitions.
The transpiler owns *how* it becomes hardware: state encoding, clocking, reset,
and the canonical three-always-block structure. The whole-language thesis is
that the low-level Verilog mistakes that trip up humans and LLMs alike —
inferred latches, blocking/non-blocking misuse, reset bugs, hand-rolled state
codes, multiple drivers — are made **inexpressible** in the language and
**impossible** in the generated output.

```
INPUT.fsm ──▶ Parser (lark) ──▶ AST ──▶ Safety_Checker ──▶ [gate] ──▶ Code_Generator ──▶ OUTPUT.sv
                  │                          │
              parse error              safety errors
              (stderr, exit≠0)        (stderr, exit≠0, no stdout)
```

The gate is absolute: if any safety check fails, **nothing** is written to
stdout and the process exits non-zero. SystemVerilog is produced only from an
AST that passed all four safety checks.

---

## Quick start

Requires **Python 3.12** and [`uv`](https://docs.astral.sh/uv/). The only
runtime dependency is [`lark`](https://github.com/lark-parser/lark).

```bash
# from the project root
uv sync                                            # create the environment
uv run python -m transpiler.transpile examples/seq_detect_101.fsm > out.sv
```

On success the generated SystemVerilog is written to **stdout** and the exit
code is `0`. On any error (bad CLI args, unreadable file, parse failure, or a
safety violation) a diagnostic is written to **stderr**, **nothing** is written
to stdout, and the exit code is non-zero.

A console script is also installed:

```bash
uv run fsm-transpile examples/traffic_light.fsm
```

---

## The language in one example

The overlapping **"101" sequence detector** (`examples/seq_detect_101.fsm`):

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

### The seven constructs

| Construct          | Form                          |
| ------------------ | ----------------------------- |
| machine            | `machine NAME { ... }`        |
| input port         | `in TYPE name`                |
| output port        | `out TYPE name`               |
| reset state        | `reset = STATE`               |
| state              | `state NAME { ... }`          |
| output assignment  | `name = VALUE`                |
| transition         | `when COND -> STATE` / `else -> STATE` |

Two types: `bit` (width 1) and `bit[H:L]` (width `H - L + 1`, with `H ≥ L ≥ 0`).
Clock (`clk`) and reset (`rst`) are implicit on every machine. The full
reference is in [`spec/LANGUAGE_SPEC.md`](spec/LANGUAGE_SPEC.md).

---

## What the transpiler guarantees

- **Moore outputs** — each output is a function of the current state only.
- **Totality** — every output is assigned in every state; every state ends with
  an `else` transition. (Both eliminate inferred latches.)
- **Single driver** — each output is driven by exactly one machine.
- **Name resolution** — every transition/reset target is a declared state.
- **Canonical structure** — exactly three procedural blocks (two `always_comb`,
  one `always_ff @(posedge clk)`), an `enum logic` state type sized
  `max(1, ceil(log2(N)))`, and a synchronous active-high reset.
- **Lint-clean, latch-free output** — generated modules pass
  `verilator --lint-only -Wall` (zero warnings) and synthesize with zero
  inferred latches under Yosys. Guards are rendered width-correctly (multi-bit
  signals reduced with `|`, comparison literals sized to the signal width), and
  unused declared inputs get a targeted, scoped `UNUSEDSIGNAL` waiver — `-Wall`
  is never dropped and width warnings are never suppressed.

---

## Project layout

```
fsm-dsl-transpiler/
├── transpiler/            # the transpiler package (only runtime dep: lark)
│   ├── transpile.py       #   CLI: python -m transpiler.transpile INPUT.fsm
│   ├── grammar.lark       #   FSM_DSL grammar (LALR(1))
│   ├── parser.py          #   parse() -> lark tree, located ParseError
│   ├── ast.py             #   typed AST + builder + typed guard-expression tree
│   ├── safety.py          #   four compile-time safety checks + driver
│   ├── codegen.py         #   three-always-block SystemVerilog emitter
│   └── errors.py          #   CompileError hierarchy with source locations
├── spec/LANGUAGE_SPEC.md  # complete language specification
├── examples/*.fsm         # seq_detect_101, traffic_light, handshake
├── golden/*.sv            # hand-written behavioral oracles for the examples
├── tests/                 # pytest + Hypothesis suite (24 correctness properties)
├── FROZEN.md              # frozen-record / re-freeze policy
└── pyproject.toml         # uv-managed, Python 3.12, hatchling build
```

---

## Tests

The whole suite runs from a single command:

```bash
uv run pytest
```

It includes unit tests, end-to-end CLI tests, negative tests, and one
property-based test (via [Hypothesis](https://hypothesis.readthedocs.io/)) for
each of the 24 correctness properties in `spec/LANGUAGE_SPEC.md` / the design.

Some gates need the OSS CAD Suite on `PATH`:

- **lint** — `verilator --lint-only -Wall` (zero warnings/errors),
- **latch-freedom** — Yosys synthesis (`$dlatch` count == 0),
- **golden equivalence** — co-simulation against the goldens for ≥ 1000 cycles
  (any of `iverilog`+`vvp` or `verilator`).

When those tools are absent the corresponding tests **skip** (they never fail
spuriously), so `uv run pytest` is green in a toolless dev environment. To
require the tools (e.g. in CI / grading), set `FSM_REQUIRE_TOOLS=1`:

```bash
FSM_REQUIRE_TOOLS=1 uv run pytest    # hard-fails if verilator/yosys are missing
```

---

## How it compares

`FSM_DSL` is closest in spirit to HDL generators like Chisel, but is
deliberately tiny and FSM-only, and its transpiler is *frozen* (see
`FROZEN.md`) so generated hardware is correct by construction and pass-rate
changes are attributable to the language, not transpiler drift. A side-by-side
of the "101" detector in FSM_DSL, the generated SystemVerilog, and Chisel is in
the spec's example section.

## License / status

FSM_DSL v0.1 — Phase 1 (language design) and Phase 2 (build + freeze the
transpiler). See `FROZEN.md` for the freeze record and re-freeze policy.
