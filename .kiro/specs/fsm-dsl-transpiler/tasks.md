# Implementation Plan: FSM_DSL Transpiler

## Overview

This plan implements **FSM_DSL v0.1** and its frozen Python 3.12 transpiler as a linear compiler pipeline: CLI shell → lark parser → AST builder → Safety_Checker (four checks) → Code_Generator (three-always-block SystemVerilog). Implementation proceeds bottom-up — error types and grammar first, then parser, AST, safety, codegen, and finally the CLI that wires everything together — followed by the language spec, example programs, goldens, and the pytest-based test harness, ending with the freeze artifact.

The stack is fixed by the design: Python 3.12, dependencies managed by `uv`, `lark` as the only parsing dependency, and `hypothesis` for property-based tests. Property tests (one per correctness property) are placed close to the code they validate and are marked optional with `*`. External-tool properties (Yosys/verilator) run at reduced iteration counts in the harness.

## Tasks

- [x] 1. Set up project structure and error foundation
  - [x] 1.1 Create the `transpiler` package and uv project configuration
    - Create `pyproject.toml` targeting Python 3.12, managed by `uv`, declaring `lark` as the only runtime dependency and `hypothesis`/`pytest` as dev dependencies
    - Create the directory layout: `transpiler/__init__.py`, `spec/`, `examples/`, `golden/`, `tests/`
    - Confirm no parsing/HDL library other than `lark` and the stdlib is declared
    - _Requirements: 15.1, 15.2_

  - [x] 1.2 Implement the compile-error hierarchy and source locations
    - Create `transpiler/errors.py` with `Loc(file, line, column)` and a `CompileError` base exposing `render()` producing `FILE:LINE:COL: <message>`
    - Add `ParseError`, `TypeError_`, and `SafetyError` (with a `rule` field: `total_outputs` | `total_transitions` | `single_driver` | `name_resolution`)
    - _Requirements: 16.2, 16.4_

- [x] 2. Implement the parser
  - [x] 2.1 Author the FSM_DSL Lark grammar
    - Create `transpiler/grammar.lark` deriving exactly the seven constructs (machine, `in`, `out`, `reset`, `state`, output assignment, transition)
    - Define the canonical forms: `machine NAME { ... }`, `in TYPE name`, `out TYPE name`, `reset = STATE`, `state NAME { ... }`, output assignment `name = VALUE`, and transitions `when COND -> STATE` / `else -> STATE`
    - Reserve the closed, case-sensitive keyword set `machine in out reset state when else`; provide exactly one syntactic form per construct (no synonyms/alternatives)
    - Define line comments `#...` ignored by the lexer except inside quoted tokens; define `bit` and `bit[H:L]` type tokens
    - _Requirements: 1.1, 1.4, 1.5, 1.6, 1.13, 4.1, 4.2, 4.4, 4.5, 4.6, 4.7, 5.2, 15.5_

  - [x] 2.2 Implement the parse loader
    - Create `transpiler/parser.py` with `parse(source) -> ParseTree` loading `grammar.lark` in `lalr` mode for unambiguous parsing
    - Raise `ParseError(line, column, message)` on grammar failure, identifying the failure line
    - _Requirements: 4.3, 5.2, 15.8_

  - [x] 2.3 Write property test for parse round-trip
    - **Property 1: Parse round-trip is identity**
    - **Validates: Requirements 5.2**
    - Place in `tests/test_parser.py`

  - [x] 2.4 Write property test for comment invariance
    - **Property 2: Comments do not affect tokenization**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - Place in `tests/test_parser.py`

  - [x] 2.5 Write property test for keyword case sensitivity
    - **Property 3: Keywords are case-sensitive**
    - **Validates: Requirements 4.4, 4.5**
    - Place in `tests/test_parser.py`

- [x] 3. Implement the AST builder and type system
  - [x] 3.1 Define the AST data model
    - Create `transpiler/ast.py` with frozen dataclasses `Loc`, `PortType` (with `width` property), `Port`, `Value`, `OutputAssignment`, `Condition`, `Transition`, `State`, `Machine`, `Program`
    - Encode structural invariants in types (e.g. `width == high - low + 1`, transition `kind` ∈ {`when`,`else`})
    - _Requirements: 2.1, 2.2_

  - [x] 3.2 Implement the lark Transformer with type and structural validation
    - Add `build_ast(tree) -> Program` transforming the parse tree into the typed model, attaching `Loc` to every node
    - Build input/output `Port` nodes from `in TYPE name` / `out TYPE name`, output assignments `name = VALUE`, and the `reset = STATE` declaration with their source locations
    - Validate type tokens: accept `bit` (width 1) and `bit[H:L]` with integer `H ≥ L ≥ 0` (range 0–65535); reject `H < L`, negative, non-integer, and unrecognized types with a located error and no emitted signal
    - Enforce exactly one machine per file; enforce exactly one reset declaration per machine (reject zero or more than one with a located error and no module); reject author-declared `clk`/`rst`; reject duplicate state names
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 2.5, 2.6, 3.1, 3.2, 3.3_

  - [x] 3.3 Write property test for vector width
    - **Property 5: Vector width matches the declared index range**
    - **Validates: Requirements 2.2, 2.3, 2.4**
    - Place in `tests/test_frontend.py`

  - [x] 3.4 Write property test for invalid type rejection
    - **Property 6: Invalid types are rejected without emitting a signal**
    - **Validates: Requirements 2.5, 2.6**
    - Place in `tests/test_frontend.py`

  - [x] 3.5 Write property test for reserved clk/rst names
    - **Property 7: Reserved clock/reset names are rejected; valid machines gain clk and rst**
    - **Validates: Requirements 3.2, 3.3, 3.4**
    - Place in `tests/test_frontend.py`

  - [x] 3.6 Write property test for machine-count rule
    - **Property 4: Exactly one machine yields exactly one module; otherwise rejection**
    - **Validates: Requirements 1.2, 1.3**
    - Place in `tests/test_frontend.py`

  - [x] 3.7 Write property test for duplicate state names
    - **Property 8: Duplicate state names are rejected**
    - **Validates: Requirements 1.9**
    - Place in `tests/test_frontend.py`

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement the Safety_Checker
  - [x] 5.1 Implement the total-outputs check
    - Add `check_total_outputs(m) -> list[SafetyError]` to `transpiler/safety.py`: for every (state, declared output) pair where the output is unassigned, emit one error `state S does not assign output 'x'`; report zero errors when all are assigned, including the zero-states/zero-outputs case
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.6_

  - [x] 5.2 Write property test for total-outputs diagnostics
    - **Property 9: Total-outputs diagnostics are exact**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.6**
    - Place in `tests/test_safety.py`

  - [x] 5.3 Implement the total-transitions check
    - Add `check_total_transitions(m) -> list[SafetyError]`: report one error per state whose transition list does not end in a final `else -> STATE`, naming each offending state
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 5.4 Write property test for total transitions
    - **Property 10: Every state must end with a final else transition**
    - **Validates: Requirements 8.1, 8.2, 8.3**
    - Place in `tests/test_safety.py`

  - [x] 5.5 Implement the name-resolution check
    - Add `check_name_resolution(m) -> list[SafetyError]`: verify every transition target (including `else -> STATE`) and the `reset = STATE` target resolve to a declared state; emit one error per unresolved target naming it
    - _Requirements: 8.4, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 5.6 Write property test for name resolution
    - **Property 11: Every transition and reset target resolves to a declared state**
    - **Validates: Requirements 8.4, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6**
    - Place in `tests/test_safety.py`

  - [x] 5.7 Implement the single-driver check
    - Add `check_single_driver(p) -> list[SafetyError]`: verify every output is assigned only within states of the machine that declares it, and that no output is declared by more than one machine; report every violation with output name and source location(s)
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 5.8 Write property test for single driver
    - **Property 12: Each output is driven by exactly one machine**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4**
    - Place in `tests/test_safety.py`

  - [x] 5.9 Implement the safety driver
    - Add `check(program) -> list[SafetyError]` that runs all four checks to completion and returns the aggregated, ordered diagnostics; an empty list means the program is safe to generate
    - _Requirements: 16.1, 16.5_

  - [x] 5.10 Write property test for multi-rule completeness
    - **Property 13: All safety checks run to completion and every violation is reported**
    - **Validates: Requirements 16.1**
    - Place in `tests/test_safety.py`

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement the Code_Generator
  - [x] 7.1 Emit the enum state type and signal declarations
    - In `transpiler/codegen.py`, emit a single `enum logic [W-1:0]` state type whose members are exactly the declared states, sized `max(1, ceil(log2(N)))`; declare `state`/`next_state` with that type and emit no hand-written literal state codes
    - _Requirements: 13.1, 13.2, 13.3_

  - [x] 7.2 Emit the next-state combinational block
    - Emit one `always_comb` next-state block opening with `next_state = state` default, then a `case (state)` with one `default:` arm; within each state arm, select the first true guard's target in declared order, with `else` as the always-true default
    - _Requirements: 8.5, 11.1, 11.3, 11.6, 12.1, 12.2_

  - [x] 7.3 Emit the output combinational block
    - Emit one `always_comb` output block (Moore: function of state only) opening with defaults for every output, then a `case (state)` with a single `default:` arm assigning all outputs
    - _Requirements: 11.1, 11.3, 11.6, 12.1, 12.2_

  - [x] 7.4 Emit the sequential state-register block
    - Emit one `always_ff @(posedge clk)` block using `<=` exclusively, with synchronous active-high reset loading the `reset` state and otherwise loading `next_state`; no asynchronous term in the sensitivity list
    - _Requirements: 11.2, 11.4, 11.5, 13.4, 13.5, 13.6_

  - [x] 7.5 Assemble the module via `generate()`
    - Add `generate(m) -> str` (precondition: `check()` returned `[]`) emitting the module header with implicit `clk`/`rst` plus declared inputs/outputs at correct widths, then the three procedural blocks
    - _Requirements: 2.3, 2.4, 3.4, 11.1_

  - [x] 7.6 Write property test for three-block structure
    - **Property 17: Generated module has exactly three procedural blocks with separated assignment operators**
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4**
    - Place in `tests/test_codegen.py`

  - [x] 7.7 Write property test for defaults and total case default arm
    - **Property 18: Combinational blocks assign defaults to all targets and cases have one total default arm**
    - **Validates: Requirements 11.6, 12.1, 12.2**
    - Place in `tests/test_codegen.py`

  - [x] 7.8 Write property test for the enum state type
    - **Property 19: State type is an enum whose members are exactly the declared states with correct width**
    - **Validates: Requirements 13.1, 13.2, 13.3**
    - Place in `tests/test_codegen.py`

  - [x] 7.9 Write property test for reset confinement
    - **Property 20: Reset logic is synchronous, active-high, and confined to the sequential block**
    - **Validates: Requirements 11.5, 13.4, 13.5**
    - Place in `tests/test_codegen.py`

  - [x] 7.10 Write property test for reset precedence
    - **Property 21: Asserted reset loads the reset state, overriding next-state**
    - **Validates: Requirements 13.6**
    - Place in `tests/test_codegen.py`

  - [x] 7.11 Write property test for transition selection order
    - **Property 22: Transition selection preserves declared order with else as default**
    - **Validates: Requirements 8.5**
    - Place in `tests/test_codegen.py`

- [x] 8. Wire the CLI pipeline
  - [x] 8.1 Implement the CLI entry point
    - Create `transpiler/transpile.py` with `main(argv) -> int` invoked as `python -m transpiler.transpile INPUT.fsm`: validate exactly one positional arg (else usage to stderr, exit 2), read the file (unreadable → stderr error, exit 1), run parse → build_ast → check → generate, buffering SystemVerilog and flushing to stdout only on full success (exit 0); on any error path write diagnostics to stderr, write nothing to stdout, exit non-zero
    - The CLI is the only component touching `sys.stdout`/`sys.stderr`/exit codes
    - _Requirements: 15.3, 15.4, 15.6, 15.7, 15.8, 16.2, 16.3, 16.4, 16.5_

  - [x] 8.2 Write property test for the stdout/exit contract
    - **Property 14: Any rejected program produces empty stdout and a non-zero exit**
    - **Validates: Requirements 15.4, 15.8, 16.2, 16.3, 16.5**
    - Place in `tests/test_cli.py`

  - [x] 8.3 Write property test for parse-failure line reporting
    - **Property 15: Parse-failure diagnostics carry a line number**
    - **Validates: Requirements 15.8, 16.4**
    - Place in `tests/test_cli.py`

  - [x] 8.4 Write property test for CLI argument arity
    - **Property 16: CLI argument arity is enforced**
    - **Validates: Requirements 15.6**
    - Place in `tests/test_cli.py`

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Author the language spec and validation inputs
  - [x] 10.1 Write the language specification document
    - Create `spec/LANGUAGE_SPEC.md`: define each of the seven constructs (syntax, semantics, example); include an unambiguous EBNF grammar with no undefined symbols; define the two-type system; state Moore semantics; enumerate all four safety rules with triggering conditions; include the construct/rule → Verilog-hazard table; state the exact `verilator --lint-only -Wall` and Yosys commands with their pass conditions; state that the transpiler is frozen and pass-rate changes must be attributable to language (not transpiler) changes
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 21.3_

  - [x] 10.2 Write the example programs
    - Create `examples/seq_detect_101.fsm` (overlapping "101" detector, four states, 1-bit in, 1-bit out asserted only on completion), `examples/traffic_light.fsm` (three states advancing on `tick`, distinct 2-bit output per state), and `examples/handshake.fsm` (three-state `req`/`ack`/`busy` controller, 1-bit signals)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 10.3 Write the golden SystemVerilog oracles
    - Create `golden/seq_detect_101.sv`, `golden/traffic_light.sv`, and `golden/handshake.sv` as known-correct, lint-clean, latch-free oracle modules matching each example's behavior
    - _Requirements: 14.2, 14.3, 17.3_

- [x] 11. Implement the test harness
  - [x] 11.1 Implement shared Hypothesis strategies
    - Create `tests/strategies.py`: a strategy producing valid `Machine`/`Program` models (varied state counts, port widths, output assignments, ordered transitions ending in `else`, resolvable targets), plus derived perturbations producing targeted invalid inputs (drop an output, strip the trailing `else`, repoint a target, inject `clk`/`rst`, duplicate a state, declare an output in two machines)
    - _Requirements: 17.1_

  - [x] 11.2 Implement example existence, structure, and safety tests
    - In `tests/test_transpiler.py`, assert the three examples exist, parse to their specified structure, and pass all four safety checks
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 11.3 Implement negative tests for each safety rule
    - Add three crafted programs (missing output assignment, missing final `else`, unresolved `State_Target`); assert non-zero exit, empty stdout, and a rule-named error identifying the offending element for each
    - _Requirements: 19.1, 19.2, 19.3_

  - [x] 11.4 Implement golden behavioral equivalence co-simulation
    - For each example, transpile then co-simulate the generated module against its `Golden_SV` under identical deterministically-seeded stimulus, identical clock and reset sequence, for ≥ 1000 cycles; compare every output port every cycle after reset deassertion; on mismatch report the cycle and offending port; a transpile failure marks that example failed and continues
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7_

  - [x] 11.5 Write property test for latch-freedom (tool-bounded)
    - **Property 23: Generated modules synthesize with zero inferred latches**
    - **Validates: Requirements 12.3, 14.3**
    - Place in `tests/test_transpiler.py`; reduced iterations (e.g. `max_examples=20`) with a marker to skip when Yosys is absent

  - [x] 11.6 Write property test for lint-cleanliness (tool-bounded)
    - **Property 24: Generated modules are lint-clean**
    - **Validates: Requirements 14.1**
    - Place in `tests/test_transpiler.py`; reduced iterations with a marker to skip when verilator is absent

  - [x] 11.7 Implement the lint and latch gates for generated modules and goldens
    - Run `verilator --lint-only -Wall` and Yosys synthesis on each generated module and golden within a 300 s per-module budget; mark a module's lint gate passed only on zero warnings/errors and its latch gate passed only on `Dlatch_Count == 0`; report failing module identifier with tool output; treat tool error/timeout as a gate failure without modifying the file
    - _Requirements: 12.4, 14.1, 14.2, 14.3, 14.4, 14.5, 18.1, 18.2, 18.3, 18.4, 18.5_

  - [x] 11.8 Implement single-command execution and smoke checks
    - Ensure `uv run pytest` runs the whole suite (positive checks for all three examples plus all negative tests) with no manual steps, reflecting pass/fail in exit status; assert Python 3.12, that the only third-party import is `lark`, and that `transpiler/grammar.lark` exists; fail with a clear message if `verilator` or `yosys` is missing on `PATH`
    - _Requirements: 15.1, 15.2, 15.5, 20.1, 20.2, 20.3, 20.4, 20.5_

- [x] 12. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Produce the freeze artifact
  - [x] 13.1 Generate the frozen record
    - On a passing `uv run pytest` result, create `FROZEN.md` recording the transpiler version identifier, the freeze date (ISO 8601), and confirmation that all three examples match their goldens on every cycle; state the re-freeze policy (modified only by re-running the full harness to a pass and updating version/date, never silently); ensure a failing run neither creates nor modifies it
    - _Requirements: 21.1, 21.2, 21.4, 21.5_

## Notes

- Tasks marked with `*` are optional property/unit tests and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each correctness property from the design is implemented by exactly one property-based test, tagged `# Feature: fsm-dsl-transpiler, Property {N}: {text}`.
- Property tests live close to the code they validate (parser, frontend, safety, codegen, CLI) and reference both the property number and the requirements clause they check.
- Properties 23 and 24 depend on external tools (Yosys, verilator) and run at reduced iteration counts with skip markers; the three goldens also exercise these tools as fixed integration cases.
- Checkpoints provide incremental validation points where the suite should be green before proceeding.
- All four safety checks run to completion before any code generation; stdout is written only on full success.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1"] },
    { "id": 3, "tasks": ["3.2", "11.1"] },
    { "id": 4, "tasks": ["5.1", "7.1", "2.3"] },
    { "id": 5, "tasks": ["5.3", "7.2", "2.4", "3.3"] },
    { "id": 6, "tasks": ["5.5", "7.3", "2.5", "3.4"] },
    { "id": 7, "tasks": ["5.7", "7.4", "3.5"] },
    { "id": 8, "tasks": ["5.9", "7.5", "3.6"] },
    { "id": 9, "tasks": ["8.1", "5.2", "7.6", "3.7"] },
    { "id": 10, "tasks": ["5.4", "7.7", "8.2", "10.1"] },
    { "id": 11, "tasks": ["5.6", "7.8", "8.3", "10.2"] },
    { "id": 12, "tasks": ["5.8", "7.9", "8.4", "10.3"] },
    { "id": 13, "tasks": ["5.10", "7.10", "11.2"] },
    { "id": 14, "tasks": ["7.11", "11.3"] },
    { "id": 15, "tasks": ["11.4"] },
    { "id": 16, "tasks": ["11.5"] },
    { "id": 17, "tasks": ["11.6"] },
    { "id": 18, "tasks": ["11.7"] },
    { "id": 19, "tasks": ["11.8"] },
    { "id": 20, "tasks": ["13.1"] }
  ]
}
```
