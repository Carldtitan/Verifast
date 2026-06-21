# Spec-mode prompt — Phase 1 + Phase 2: FSM-DSL and its frozen transpiler

> Paste everything below the line into Kiro Spec mode. It is written to be prescriptive
> about rules and constraints, while leaving the requirements/design/tasks structure to you.

---

## Project context (read first)

We are building a small, AI-native hardware description language for **finite state
machines (FSMs)** for a HUD/YC RL-environments hackathon. The thesis: LLMs are
measurably bad at writing Verilog FSMs, and almost all their failures are the *same*
low-level Verilog footguns (inferred latches, blocking vs non-blocking misuse, reset
mistakes, hand-rolled state encodings, multiple drivers) rather than logic errors. If
the model writes a tiny language where those footguns are *impossible to express*, and a
frozen transpiler emits correct SystemVerilog every time, the model's pass-rate should
rise. A later phase (NOT in this spec) evolves the language via an RL loop.

**This spec covers only Phase 1 (design the language) and Phase 2 (build + freeze the
transpiler).** Do not design the RL loop, the benchmark harness for the model, or any
training. Stop at "the transpiler is built, tested against goldens, and frozen."

### Team and environment constraints (hard, non-negotiable)
- **The team does not know Verilog.** The transpiler must be plain Python so the team can
  maintain it; the generated SystemVerilog is checked by tools, never hand-reviewed.
- **Everything runs in WSL/Ubuntu on a path with NO spaces.** Verilator's build step
  uses `make`, which breaks on spaces. The canonical project lives at a space-free Linux
  path (e.g. `/home/agent/fsm-dsl` or `~/fsm-dsl`). Never assume a Windows path.
- **The toolchain is already installed and verified** (OSS CAD Suite: `verilator`,
  `yosys`, `z3`, `sby`). Assume `verilator` and `yosys` are on `PATH`.
- **Language for the transpiler:** Python 3.12, dependency management with `uv`. Use the
  `lark` parsing library for the grammar. No other heavy dependencies.

---

## Fundamental rules this spec MUST honor

### A. Programming-language design principles (from trusted sources)
Apply these as design requirements for the DSL. Sources:
[Hoare, *Hints on Programming Language Design*](https://en.wikipedia.org/wiki/Programming_language_design_and_implementation)
and [summary](https://softwareas.com/hints-on-programming-language-design-by-car-hoare-quick-summary/).
(Rephrased for licensing compliance.)

1. **Simplicity.** Keep the language small. Fewer constructs beat more. A new user should
   learn the whole language in minutes.
2. **Security / safety.** It must be impossible (or very hard) to write a program that
   compiles to broken or ambiguous hardware. Errors should be caught at compile time with
   clear messages, not discovered later in simulation.
3. **Orthogonality / uniformity.** A small set of consistent rules that combine
   predictably. Similar things look similar; there is **one** canonical way to express
   each concept (no synonyms, no two syntaxes for the same idea).
4. **Readability.** Keywords are real English words. The text of a program should read
   close to a plain description of the state machine.
5. **Fast, simple translation.** The grammar must be simple enough that a
   straightforward parser + tree-walking code generator suffices. No ambiguity.
6. **Principle of least astonishment.** Defaults do the safe, obvious thing.

### B. Synthesizable-SystemVerilog rules the GENERATED code MUST follow
The transpiler's *output* must obey these industry-standard FSM coding rules. Sources:
[Cummings, *State Machine Coding Styles for Synthesis*](https://www.researchgate.net/publication/247640028_State_Machine_Coding_Styles_for_Synthesis)
and [Cummings, *Nonblocking Assignments in Verilog Synthesis — Coding Styles That Kill*](https://www.researchgate.net/publication/238283056_Nonblocking_Assignments_in_Verilog_Synthesis_Coding_Styles_That_Kill).
(Rephrased for licensing compliance.)

1. Use the **three-always-block Moore style**: (1) a combinational next-state block, (2)
   a sequential state-register block, (3) a combinational output block.
2. **Sequential logic uses non-blocking assignment `<=` inside `always_ff @(posedge clk)`.**
3. **Combinational logic uses blocking assignment `=` inside `always_comb`.** Never mix
   the two styles in one block.
4. **No inferred latches.** Every combinational block must assign every signal on every
   path: pre-assign defaults at the top of the block AND provide a `default:` arm in every
   `case`. (We confirm this with Yosys: zero `$dlatch` cells.)
5. **State encoding is the compiler's job**, emitted as a SystemVerilog `enum logic`. The
   programmer never writes state codes.
6. **Synchronous, active-high reset** in the state-register block only.
7. Output must be **lint-clean** under `verilator --lint-only -Wall` (zero warnings).

---

## Phase 1 — Design the language

### Required language design (treat as fixed requirements)
The DSL is **Moore FSMs only** and must be built from this minimal construct set. Do not
add constructs beyond these in v0.1:

1. `machine NAME { ... }` — declares one FSM (compiles to one SystemVerilog module).
2. `in TYPE name` — an input port. `TYPE` is `bit` or `bit[H:L]`.
3. `out TYPE name` — an output port (Moore output).
4. `reset = STATE` — names the reset state.
5. `state NAME { ... }` — one state.
6. output assignment `name = VALUE` inside a state — sets a Moore output for that state.
7. transitions inside a state: `when COND -> STATE` (priority, top to bottom) and a
   mandatory final `else -> STATE`.

`clk` and `rst` are **implicit** — every machine gets them automatically; the programmer
never declares or wires them.

### Safety rules the language MUST enforce at compile time (these are the whole point)
- **Outputs are total:** every `out` must be assigned in **every** `state`. Missing one is
  a compile error (`state S does not assign output 'x'`). This makes inferred latches
  impossible.
- **Transitions are total:** every `state` must end with `else -> STATE`. Missing it is a
  compile error.
- **Single driver:** an output can only be assigned inside states of its own machine.
- **Names must resolve:** every `STATE` referenced in a transition and in `reset` must be
  a declared `state`; otherwise compile error.
- **Comments:** `#` to end of line.

### Phase 1 deliverables
1. `spec/LANGUAGE_SPEC.md` — the full language definition: the 7 constructs, an EBNF
   grammar, the type system (`bit`, `bit[H:L]`), Moore semantics, the compile-time safety
   rules above, and a table mapping each construct/rule to the specific Verilog footgun it
   removes.
2. `examples/*.fsm` — **3 hand-written example programs**, increasing in complexity:
   - `seq_detect_101.fsm` — overlapping "101" sequence detector (4 states, 1-bit out).
   - `traffic_light.fsm` — 3 states cycling on a `tick` input, 2-bit output.
   - `handshake.fsm` — a `req`/`ack`/`busy` controller (3 states).
3. `golden/*.sv` — for each example, the **known-correct SystemVerilog** it must compile
   to, written in the three-always-block Moore style from Rule B. These goldens are the
   transpiler's test oracle in Phase 2. Each golden must compile lint-clean under
   `verilator --lint-only -Wall` and synthesize with **zero `$dlatch`** under Yosys.

### Phase 1 acceptance criteria
- The spec is complete enough that someone could implement the transpiler from it alone.
- All 3 `.fsm` examples are valid under the spec's own rules (total outputs, total
  transitions, resolvable names).
- All 3 goldens pass `verilator --lint-only -Wall` (0 warnings) and Yosys `$dlatch` count
  is 0. (Provide the exact commands in the spec.)

---

## Phase 2 — Build the transpiler, then freeze it

### What to build
A Python program that turns `.fsm` source text into SystemVerilog text.

1. `transpiler/grammar.lark` — the Lark grammar for the language in Phase 1.
2. `transpiler/transpile.py` — parses a `.fsm` file, runs the compile-time safety checks
   (total outputs, total transitions, name resolution, single driver) with **clear error
   messages**, and emits SystemVerilog in the exact three-always-block Moore style.
   Provide a CLI: `python -m transpiler.transpile INPUT.fsm > OUTPUT.sv`.
3. `tests/test_transpiler.py` — the test harness (see below).

### The judge (reuse the checks we already trust)
For each example, the harness must:
1. **Transpile** `examples/X.fsm` to SystemVerilog.
2. **Compare to golden** — the generated SV must be functionally equivalent to
   `golden/X.sv`. Equivalence is established by simulation (below), not string match
   (formatting may differ).
3. **Lint** — `verilator --lint-only -Wall TOP` on the generated SV must be 0 warnings.
4. **No latches** — run Yosys (`read_verilog -sv; proc; opt; write_json`) and assert the
   generated SV has **zero `$dlatch`** cells. (This mirrors the synthesis check in the
   existing repair grader, which we have already calibrated and trust.)
5. **Behavioral equivalence** — write a small SystemVerilog or cocotb testbench per
   example that drives identical input sequences into BOTH the generated module and the
   golden module and asserts their outputs match on every cycle. Use `verilator --binary`
   (or the cocotb runner) to run it.

### Phase 2 acceptance criteria
- For all 3 examples: transpile succeeds, lint is clean (0 warnings), `$dlatch` count is
  0, and the generated module's outputs match the golden's on every cycle of the
  testbench.
- The compile-time safety checks are proven by **negative tests**: feed the transpiler a
  program with a missing output, a missing `else`, and an undefined state target, and
  assert it errors with a clear, specific message in each case.
- A single command (e.g. `uv run pytest`) runs the whole harness green.

### Freeze
Once all Phase 2 acceptance criteria pass:
- Tag/record the transpiler version (e.g. a `FROZEN.md` noting the commit/date and that
  all goldens pass).
- State explicitly in the spec that the transpiler is **frozen**: later phases may change
  the *language* and *examples*, but the transpiler is only modified through a deliberate,
  re-calibrated re-freeze — never silently during experiments. Explain why: if the
  transpiler drifts during experiments, we can't tell whether a pass-rate change came from
  a better language or a changed transpiler.

---

## Explicitly out of scope (do NOT include in this spec)
- The RL / self-improvement loop, reward shaping, held-out task sets.
- Any model training, fine-tuning, or inference provider integration.
- Mealy outputs, timers/counters, hierarchy/sub-machines, default-output blocks. (These
  are deliberately deferred; the later RL loop may propose them.)
- Integration with the `stream_arb_fifo` HUD tasks — our DSL emits its own modules; we
  only *reuse the style of checks* (lint, `$dlatch`, simulation), not those specific
  tasks.

## How to structure the spec output
- **Requirements** in EARS-style, grouped as: language design, compile-time safety,
  generated-SV correctness, transpiler behavior, test harness, freeze.
- **Design** covering: grammar, AST, the safety-check pass, the code-generation templates
  (show the exact three-always-block skeleton), and the test-harness architecture.
- **Tasks** ordered so Phase 1 artifacts (spec, examples, goldens) come first and are
  validated by the toolchain before the transpiler is written, then the transpiler, then
  the harness, then freeze.
