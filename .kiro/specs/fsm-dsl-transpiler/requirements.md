# Requirements Document

## Introduction

This feature delivers a small, AI-native hardware description language for Moore finite state machines (FSMs) together with a frozen Python transpiler that emits correct, synthesizable SystemVerilog. The motivating thesis is that large language models fail at Verilog FSMs primarily through repeatable low-level coding mistakes (inferred latches, blocking versus non-blocking assignment misuse, reset errors, hand-rolled state encodings, and multiple drivers) rather than logic errors. By constraining authors to a tiny language in which those mistakes cannot be expressed, and by routing all SystemVerilog generation through a deterministic transpiler, generated hardware is correct by construction.

This document covers **only Phase 1 (design the language)** and **Phase 2 (build and freeze the transpiler)**. It deliberately excludes the reinforcement-learning loop, any model training or inference, and the benchmark harness for evaluating models. Scope ends when the transpiler is built, validated against golden SystemVerilog files, and frozen.

The work is organized into six requirement groups: language design, compile-time safety, generated-SystemVerilog correctness, transpiler behavior, test harness, and freeze.

## Glossary

- **FSM_DSL**: The Moore-only finite state machine domain-specific language defined in this spec (version 0.1).
- **Transpiler**: The Python 3.12 program that parses FSM_DSL source text, performs compile-time safety checks, and emits SystemVerilog. Invoked as `python -m transpiler.transpile INPUT.fsm > OUTPUT.sv`.
- **Parser**: The component of the Transpiler, built on the `lark` library, that turns FSM_DSL source text into a parse tree / AST.
- **Safety_Checker**: The component of the Transpiler that enforces compile-time safety rules (total outputs, total transitions, single driver, name resolution).
- **Code_Generator**: The component of the Transpiler that emits SystemVerilog in the three-always-block Moore style.
- **Test_Harness**: The pytest-based suite (`tests/test_transpiler.py`) that transpiles examples, compares against goldens, lints, checks for latches, runs behavioral equivalence, and runs negative tests.
- **Golden_SV**: A known-correct SystemVerilog file (`golden/X.sv`) that serves as the test oracle for the transpiler output of a corresponding example.
- **Example_Program**: A hand-written FSM_DSL source file (`examples/X.fsm`) used as transpiler input and validation case.
- **Language_Spec**: The document `spec/LANGUAGE_SPEC.md` defining FSM_DSL fully.
- **Frozen_Record**: The document `FROZEN.md` recording the frozen transpiler version, date, and golden pass status.
- **Moore_Output**: An FSM output whose value depends only on the current state, not on inputs.
- **Three_Always_Style**: The SystemVerilog FSM coding style using exactly three blocks: a combinational next-state block, a sequential state-register block, and a combinational output block.
- **Dlatch_Count**: The number of `$dlatch` cells reported by Yosys synthesis of a SystemVerilog module.
- **State_Target**: A state name referenced as the destination of a transition or by a `reset` declaration.
- **Total_Outputs**: The property that every declared output is assigned in every state.
- **Total_Transitions**: The property that every state ends with a final `else -> STATE` clause.
- **Toolchain**: The pre-installed OSS CAD Suite tools available on `PATH`: `verilator`, `yosys`, `z3`, and `sby`.

## Requirements

### Requirement 1: Language Construct Set (Language Design)

**User Story:** As a DSL author, I want a minimal fixed set of constructs for Moore FSMs, so that I can learn the whole language in minutes and cannot express unsafe hardware.

#### Acceptance Criteria

1. THE FSM_DSL SHALL support exactly seven constructs: machine declaration, input port declaration, output port declaration, reset-state declaration, state declaration, output assignment, and transition.
2. THE FSM_DSL SHALL declare exactly one FSM per source file using the form `machine NAME { ... }`, where NAME is a unique identifier and the machine compiles to exactly one SystemVerilog module.
3. IF a source file declares zero machines or more than one machine, THEN THE Safety_Checker SHALL report a compile-time error identifying the problem and its source location, and SHALL emit no SystemVerilog module.
4. THE FSM_DSL SHALL declare an input port using the form `in TYPE name`, where TYPE is one of the FSM_DSL-defined port types and name is an identifier unique within the machine.
5. THE FSM_DSL SHALL declare an output port using the form `out TYPE name`, where TYPE is one of the FSM_DSL-defined port types and name is an identifier unique within the machine.
6. THE FSM_DSL SHALL declare exactly one reset state per machine using the form `reset = STATE`.
7. IF a machine declares zero reset declarations or more than one reset declaration, THEN THE Safety_Checker SHALL report a compile-time error identifying the problem and its source location, and SHALL emit no SystemVerilog module.
8. THE FSM_DSL SHALL declare a state using the form `state NAME { ... }`, where NAME is an identifier unique within the machine.
9. IF two or more states are declared with the same NAME within a machine, THEN THE Safety_Checker SHALL report a compile-time error naming the duplicated state, and SHALL emit no SystemVerilog module.
10. THE FSM_DSL SHALL set a Moore_Output for a state using an output assignment of the form `name = VALUE` inside that state, where VALUE is consistent with the named output's TYPE.
11. THE FSM_DSL SHALL express a guarded transition using the form `when COND -> STATE` inside a state.
12. THE FSM_DSL SHALL express an unconditional fallback transition using the form `else -> STATE` inside a state.
13. WHERE the FSM_DSL version is 0.1, IF a program contains a construct outside the seven defined constructs, THEN THE Parser SHALL report a compile-time error identifying the unsupported construct and its source location, and SHALL emit no SystemVerilog module.

### Requirement 2: Type System (Language Design)

**User Story:** As a DSL author, I want a simple type notation for signals, so that I can declare single-bit and multi-bit ports without ambiguity.

#### Acceptance Criteria

1. THE FSM_DSL SHALL support the type `bit` for a single-bit signal representing a 1-bit-wide port.
2. THE FSM_DSL SHALL support the type `bit[H:L]` for a multi-bit signal, where H is the high index and L is the low index, and both H and L are non-negative integers in the range 0 to 65535, with H greater than or equal to L.
3. WHEN a port is declared with type `bit`, THE Code_Generator SHALL emit a single-bit SystemVerilog signal of width 1.
4. WHEN a port is declared with type `bit[H:L]`, THE Code_Generator SHALL emit a SystemVerilog vector signal spanning indices H down to L with a width of (H minus L plus 1) bits.
5. IF a port is declared with type `bit[H:L]` where H is less than L, or where H or L is negative, or where H or L is non-integer, THEN THE FSM_DSL SHALL reject the declaration, produce an error indicating the invalid index range, and emit no SystemVerilog signal for that port.
6. IF a port is declared with a type token other than `bit` or `bit[H:L]`, THEN THE FSM_DSL SHALL reject the declaration, produce an error indicating the unrecognized type, and emit no SystemVerilog signal for that port.

### Requirement 3: Implicit Clock and Reset (Language Design)

**User Story:** As a DSL author, I want clock and reset handled automatically, so that I never wire sequential plumbing by hand.

#### Acceptance Criteria

1. THE FSM_DSL SHALL treat clock (`clk`) and reset (`rst`) as implicit input ports present on every machine without requiring author declaration.
2. IF a program declares a port whose name exactly matches the reserved identifier `clk` or `rst` (case-sensitive, exact match), THEN THE Safety_Checker SHALL report a compile-time error that identifies the offending reserved name and the source location of the declaration.
3. WHEN the Safety_Checker reports a reserved-name error for a machine, THEN THE Code_Generator SHALL NOT emit SystemVerilog output for that machine, and the input source SHALL remain unmodified.
4. WHEN a machine is transpiled and no reserved-name error is present, THE Code_Generator SHALL add `clk` and `rst` as input ports on the generated SystemVerilog module without requiring author declaration.

### Requirement 4: Comments and Readability (Language Design)

**User Story:** As a DSL author, I want comments and English-like keywords, so that a program reads close to a plain description of the state machine.

#### Acceptance Criteria

1. WHEN a `#` character is encountered outside a quoted token or string, THE Parser SHALL treat all characters from `#` through the end of the current line (up to but excluding the newline) as a comment and SHALL exclude them from tokenization.
2. WHEN a `#` character appears inside a quoted token or string, THE Parser SHALL treat it as a literal character and SHALL NOT begin a comment.
3. WHEN a source file is tokenized, THE Parser SHALL produce a token stream identical to the token stream produced from the same source with all comments removed.
4. THE FSM_DSL SHALL define an exact, closed, case-sensitive keyword set consisting of `machine`, `in`, `out`, `reset`, `state`, `when`, and `else`.
5. WHEN a token matches a keyword spelling but differs in letter case, THE Parser SHALL NOT treat that token as a keyword.
6. THE FSM_DSL SHALL provide exactly one canonical spelling and one syntactic form for each concept, with no synonym keywords and no alternative syntaxes for the same idea.
7. IF a program uses a synonym keyword or an alternative syntax for a concept, THEN THE Parser SHALL report a compile-time error and SHALL leave any previously parsed output unchanged.

### Requirement 5: Language Specification Document (Language Design)

**User Story:** As a transpiler implementer, I want a complete language specification, so that I can implement the transpiler from the spec alone.

#### Acceptance Criteria

1. THE Language_Spec SHALL define each of the exactly seven FSM_DSL constructs (`machine`, `in`, `out`, `reset`, `state`, output assignment, and transition), and for each construct SHALL state its syntax, its semantics, and at least one textual example of its use.
2. THE Language_Spec SHALL include an EBNF grammar that derives all seven constructs, contains no unreferenced or undefined grammar symbols, and is unambiguous (every valid FSM_DSL program has exactly one parse).
3. THE Language_Spec SHALL define the type system as exactly two types: `bit` (width 1) and `bit[H:L]`, where H and L are non-negative integers constrained by H ≥ L and the declared vector width equals H − L + 1.
4. THE Language_Spec SHALL define Moore semantics by stating that each `out` value is a function of the current state only and is independent of input values within the same cycle.
5. THE Language_Spec SHALL enumerate every compile-time safety rule enforced by the Safety_Checker, covering at minimum total outputs (every `out` assigned in every `state`), total transitions (every `state` ends with `else -> STATE`), single driver (an output is assigned only within states of its own machine), and name resolution (every `STATE` referenced in a transition or `reset` is a declared `state`); and for each rule SHALL state the triggering condition and that violation produces a compile-time error.
6. THE Language_Spec SHALL include a table containing one row for each of the seven constructs and one row for each safety rule enumerated in Criterion 5, where each row names the specific Verilog coding hazard that construct or rule removes.
7. THE Language_Spec SHALL state the exact `verilator` and `yosys` commands used to validate generated SystemVerilog, including for each command the pass condition that determines success (`verilator` lint reporting zero warnings and `yosys` reporting zero `$dlatch` cells).

### Requirement 6: Example Programs (Language Design)

**User Story:** As a transpiler implementer, I want representative example programs, so that the language and transpiler are exercised across increasing complexity.

#### Acceptance Criteria

1. THE feature SHALL provide an Example_Program `examples/seq_detect_101.fsm` implementing an overlapping "101" sequence detector with exactly four states, a single 1-bit input, and a single 1-bit output that is asserted (value 1) only on the input cycle that completes a "101" pattern and is 0 otherwise.
2. THE feature SHALL provide an Example_Program `examples/traffic_light.fsm` with exactly three states that advance to the next state on each assertion of the `tick` input and a 2-bit output that takes a distinct value (0 to 3) for each state.
3. THE feature SHALL provide an Example_Program `examples/handshake.fsm` implementing a `req`/`ack`/`busy` controller with exactly three states, where `req`, `ack`, and `busy` are each 1-bit signals.
4. WHEN the Safety_Checker processes each Example_Program, THE Safety_Checker SHALL report it as passing only if every state defines an output for all declared output signals, every state defines a transition for every reachable input combination, and every name referenced (state, input, output) resolves to a declared name.
5. IF any Example_Program fails total outputs, total transitions, or name resolution checks, THEN THE Safety_Checker SHALL reject the program, emit an error indicating the failed rule and the offending state or name, and produce no transpiler output for that program.

### Requirement 7: Total Outputs (Compile-Time Safety)

**User Story:** As a DSL author, I want every output forced to have a value in every state, so that inferred latches are impossible.

#### Acceptance Criteria

1. THE Safety_Checker SHALL verify, for every declared state and every declared output, that the output is assigned exactly one value within that state.
2. IF a declared state does not assign a declared output, THEN THE Safety_Checker SHALL report a compile-time error naming the state and the unassigned output, in the form `state S does not assign output 'x'`.
3. WHEN a declared state leaves more than one declared output unassigned, THE Safety_Checker SHALL report one separate compile-time error per unassigned output, each in the form `state S does not assign output 'x'`.
4. WHEN the source declares zero states or zero outputs, THE Safety_Checker SHALL complete the totality check without reporting any unassigned-output error.
5. IF at least one unassigned-output error is reported during the totality check, THEN THE Safety_Checker SHALL terminate compilation with a non-zero exit status and SHALL NOT produce compiled output.
6. WHEN every declared output is assigned in every declared state, THE Safety_Checker SHALL complete the totality check with no error reported and allow compilation to proceed.

### Requirement 8: Total Transitions (Compile-Time Safety)

**User Story:** As a DSL author, I want every state to define a transition for all conditions, so that next-state logic is never ambiguous.

#### Acceptance Criteria

1. WHEN the Safety_Checker processes a source file, THE Safety_Checker SHALL verify that every declared state ends with a final `else -> STATE` clause as its last transition.
2. IF a declared state does not end with a final `else -> STATE` clause, THEN THE Safety_Checker SHALL reject compilation, produce no output artifact, and report a compile-time error naming the offending state.
3. IF more than one declared state lacks a final `else -> STATE` clause, THEN THE Safety_Checker SHALL report one compile-time error per offending state, each naming the offending state.
4. IF the target `STATE` referenced in an `else -> STATE` clause is not a declared state, THEN THE Safety_Checker SHALL reject compilation and report a compile-time error naming both the offending state and the undeclared target.
5. WHEN the Safety_Checker evaluates the transitions of a state, THE Safety_Checker SHALL evaluate them in declared order from top to bottom and select the first transition whose condition evaluates true, treating the final `else -> STATE` clause as the always-true default.

### Requirement 9: Single Driver (Compile-Time Safety)

**User Story:** As a DSL author, I want each output driven from exactly one machine, so that multiple-driver hardware bugs cannot occur.

#### Acceptance Criteria

1. WHEN a DSL source program is compiled, THE Safety_Checker SHALL verify, before any code generation occurs, that every output is assigned only within states belonging to the single machine that declares that output.
2. IF an output is assigned in a state that belongs to a machine other than the machine declaring the output, THEN THE Safety_Checker SHALL reject the program with a compile-time error that names the offending output and reports the source location (file and line) of the offending assignment, and SHALL NOT produce generated output.
3. IF the same output is declared by more than one machine, THEN THE Safety_Checker SHALL reject the program with a compile-time error that names the duplicated output and reports the source location (file and line) of each declaring machine, and SHALL NOT produce generated output.
4. WHEN the Safety_Checker reports more than one single-driver violation in a single compilation, THE Safety_Checker SHALL report every detected violation rather than stopping at the first one.

### Requirement 10: Name Resolution (Compile-Time Safety)

**User Story:** As a DSL author, I want every referenced state name to resolve to a real state, so that dangling transitions are caught before simulation.

#### Acceptance Criteria

1. WHEN the Safety_Checker processes a source program, THE Safety_Checker SHALL verify that every State_Target referenced in every transition matches the name of a state declared in that program.
2. WHEN the Safety_Checker processes a source program, THE Safety_Checker SHALL verify that the state named in `reset = STATE` matches the name of a state declared in that program.
3. IF a transition references a State_Target whose name does not match any declared state, THEN THE Safety_Checker SHALL report a compile-time error that names the undefined State_Target, and SHALL prevent simulation from starting.
4. IF the reset declaration references a state whose name does not match any declared state, THEN THE Safety_Checker SHALL report a compile-time error that names the undefined reset state, and SHALL prevent simulation from starting.
5. IF two or more State_Targets across the program are unresolved, THEN THE Safety_Checker SHALL report a separate compile-time error naming each unresolved State_Target.
6. WHEN every referenced State_Target and the reset state resolve to a declared state, THE Safety_Checker SHALL report zero name-resolution errors and SHALL allow compilation to proceed.

### Requirement 11: Three-Always-Block Structure (Generated-SV Correctness)

**User Story:** As a hardware consumer of generated code, I want the canonical three-always-block Moore structure, so that synthesis produces predictable, correct hardware.

#### Acceptance Criteria

1. WHEN the Code_Generator emits a module for a state machine, THE Code_Generator SHALL produce exactly three procedural blocks for that machine: one combinational next-state block, one sequential state-register block, and one combinational output block.
2. THE Code_Generator SHALL emit non-blocking assignments (`<=`) exclusively inside the sequential block, and the sequential block SHALL be declared as an `always_ff @(posedge clk)` block.
3. THE Code_Generator SHALL emit blocking assignments (`=`) exclusively inside each combinational block, and each combinational block SHALL be declared as an `always_comb` block.
4. THE Code_Generator SHALL place sequential assignments (`<=`) and combinational assignments (`=`) in separate blocks such that no single procedural block contains both assignment operators.
5. WHEN a reset condition is asserted, THE Code_Generator SHALL emit, inside the sequential `always_ff` block, an assignment that loads the state register with the defined reset state; otherwise the sequential block SHALL assign the state register the value produced by the combinational next-state block.
6. THE Code_Generator SHALL assign a default value to every next-state signal and every output signal at the start of its combinational block on all execution paths, so that each combinational block produces no inferred latches.

### Requirement 12: No Inferred Latches (Generated-SV Correctness)

**User Story:** As a hardware consumer of generated code, I want no inferred latches, so that the design behaves as a clean synchronous FSM.

#### Acceptance Criteria

1. WHEN the Code_Generator emits a combinational block (`always_comb` or equivalent), THE Code_Generator SHALL assign a default value to every signal that is the target of an assignment anywhere within that block, before any conditional (`if`/`case`) statement in that block.
2. THE Code_Generator SHALL emit exactly one `default:` arm in every `case` statement it generates, and that arm SHALL assign a value to every signal assigned in any other arm of the same `case` statement.
3. WHEN any generated SystemVerilog module is synthesized with Yosys, THE generated SystemVerilog SHALL produce a Dlatch_Count of exactly zero as reported by the Yosys synthesis statistics for that module.
4. IF synthesis of any generated module with Yosys reports a Dlatch_Count greater than zero, THEN THE Code_Generator SHALL treat generation as failed and SHALL surface an error indicating which module and signal inferred a latch, without emitting the module as a successful result.

### Requirement 13: State Encoding and Reset (Generated-SV Correctness)

**User Story:** As a DSL author, I want the compiler to own state encoding and reset, so that I never hand-roll state codes or reset logic.

#### Acceptance Criteria

1. THE Code_Generator SHALL emit the state encoding as a single SystemVerilog `enum logic` type whose enumeration members are exactly the set of declared states, with one member per declared state and no additional members.
2. THE Code_Generator SHALL size the `enum logic` state type to a width of `max(1, ceil(log2(N)))` bits, where N is the number of declared states.
3. THE Code_Generator SHALL declare the state register and the next-state signal using the emitted `enum logic` state type, and SHALL NOT emit hand-written integer or bit-vector literal state codes.
4. THE Code_Generator SHALL emit the reset logic exclusively within the sequential state-register block (the `always_ff @(posedge clk)` block) and SHALL NOT emit reset logic in any combinational block.
5. THE Code_Generator SHALL emit the reset as synchronous, sampling `rst` only on the rising edge of `clk`, with no asynchronous reset term in the sensitivity list, and SHALL treat a logic-high `rst` value as the asserted (active) state.
6. WHILE `rst` is asserted high, WHEN a rising edge of `clk` occurs, THE generated SystemVerilog SHALL set the state register to the state named by the `reset` declaration, taking precedence over any next-state transition value.

### Requirement 14: Lint-Clean Output (Generated-SV Correctness)

**User Story:** As a hardware consumer of generated code, I want lint-clean SystemVerilog, so that the output passes standard quality gates without manual review.

#### Acceptance Criteria

1. WHEN a generated module is checked with `verilator --lint-only -Wall`, THE generated SystemVerilog SHALL produce zero warnings and zero errors, and the lint process SHALL terminate with a success (zero) exit status.
2. WHEN each Golden_SV is checked with `verilator --lint-only -Wall`, THE Golden_SV SHALL produce zero warnings and zero errors, and the lint process SHALL terminate with a success (zero) exit status.
3. WHEN each Golden_SV is synthesized with Yosys, THE Golden_SV SHALL produce a Dlatch_Count exactly equal to zero.
4. IF the `verilator --lint-only -Wall` check reports one or more warnings or errors for a generated module or a Golden_SV, THEN THE quality gate SHALL classify that file as failed and SHALL report each reported warning together with its source file name and line number, without modifying the checked file.
5. IF Yosys synthesis of a Golden_SV produces a Dlatch_Count greater than zero, THEN THE quality gate SHALL classify that Golden_SV as failed and SHALL report the resulting inferred-latch count.

### Requirement 15: Transpiler CLI and Parsing (Transpiler Behavior)

**User Story:** As a team member, I want a simple command-line transpiler in plain Python, so that I can maintain it without knowing Verilog.

#### Acceptance Criteria

1. THE Transpiler SHALL be implemented in Python 3.12 with dependencies managed by `uv`.
2. THE Transpiler SHALL use the `lark` library for parsing and SHALL NOT declare or import any parsing or hardware-description library other than `lark` and the Python 3.12 standard library.
3. THE Transpiler SHALL provide a CLI invoked as `python -m transpiler.transpile INPUT.fsm`, accepting exactly one positional argument naming the input `.fsm` file.
4. WHEN the Transpiler is invoked on a `.fsm` file that parses successfully against the FSM_DSL grammar, THE Transpiler SHALL write the generated SystemVerilog to standard output and SHALL terminate with a zero exit status.
5. THE feature SHALL provide a Lark grammar file `transpiler/grammar.lark` defining the FSM_DSL.
6. IF the CLI is invoked with zero positional arguments or more than one positional argument, THEN THE Transpiler SHALL write an error message to standard error indicating that exactly one input file is required, SHALL write nothing to standard output, and SHALL terminate with a non-zero exit status.
7. IF the named input file does not exist or cannot be opened for reading, THEN THE Transpiler SHALL write an error message to standard error indicating the file could not be read, SHALL write nothing to standard output, and SHALL terminate with a non-zero exit status.
8. IF the input file content fails to parse against the FSM_DSL grammar, THEN THE Transpiler SHALL write an error message to standard error indicating the parse failure and its location, SHALL write nothing to standard output, and SHALL terminate with a non-zero exit status.

### Requirement 16: Transpiler Error Reporting (Transpiler Behavior)

**User Story:** As a DSL author, I want clear, specific error messages, so that I can fix mistakes at compile time rather than in simulation.

#### Acceptance Criteria

1. WHEN the Transpiler is invoked on a program that parses successfully, THE Transpiler SHALL run all four compile-time safety checks (total outputs, total transitions, name resolution, single driver) to completion before emitting any SystemVerilog.
2. IF a program violates a safety rule, THEN THE Transpiler SHALL write to the standard error stream a compile-time error message that identifies the specific safety rule violated and names the offending program element by its declared identifier (the relevant state name, output name, or State_Target).
3. IF a program violates a safety rule, THEN THE Transpiler SHALL write nothing to the standard output stream and SHALL terminate with a non-zero exit status.
4. IF the input cannot be parsed as a valid FSM_DSL program, THEN THE Transpiler SHALL write a parse error to the standard error stream that identifies the line number of the failure, write nothing to the standard output stream, and terminate with a non-zero exit status.
5. WHEN all four compile-time safety checks complete with zero violations, THE Transpiler SHALL terminate with a zero exit status.

### Requirement 17: Transpile-to-Golden Behavioral Equivalence (Test Harness)

**User Story:** As a maintainer, I want the harness to prove generated code matches the goldens behaviorally, so that I trust the transpiler output regardless of formatting.

#### Acceptance Criteria

1. WHEN the Test_Harness runs, THE Test_Harness SHALL transpile each Example_Program to SystemVerilog.
2. IF transpilation of an Example_Program fails, THEN THE Test_Harness SHALL mark that example as failed, report a diagnostic identifying the example, and continue running the remaining examples.
3. WHEN the Test_Harness establishes equivalence between a generated module and its Golden_SV, THE Test_Harness SHALL do so by co-simulation comparing observable outputs, and SHALL NOT use textual matching of the SystemVerilog.
4. WHEN the Test_Harness simulates a generated module and its Golden_SV, THE Test_Harness SHALL drive both with identical, deterministically-seeded input stimulus, an identical clock, and an identical reset sequence, for a minimum of 1000 clock cycles.
5. WHILE simulation runs after reset deassertion, THE Test_Harness SHALL compare every output port of the generated module against the corresponding output port of the Golden_SV on every clock cycle.
6. WHEN every compared output port matches on every cycle for an example, THE Test_Harness SHALL mark that example's equivalence check as passed.
7. IF any output port differs between the generated module and the Golden_SV on any cycle, THEN THE Test_Harness SHALL mark that example as failed and report a diagnostic identifying the cycle and the mismatched output port.

### Requirement 18: Harness Lint and Latch Checks (Test Harness)

**User Story:** As a maintainer, I want the harness to enforce lint and latch gates, so that every transpiled module meets the generated-SV correctness rules automatically.

#### Acceptance Criteria

1. WHEN the Test_Harness runs, THE Test_Harness SHALL execute `verilator --lint-only -Wall` on each generated SystemVerilog module in the transpilation output set within 300 seconds per module, and SHALL mark a module's lint gate as passed only when verilator reports zero warnings and zero errors.
2. IF `verilator --lint-only -Wall` reports one or more warnings or errors for a generated module, THEN THE Test_Harness SHALL mark that module's lint gate as failed, preserve the results of the other modules, and report the failing module identifier together with the verilator warning and error output.
3. WHEN the Test_Harness runs, THE Test_Harness SHALL synthesize each generated module with Yosys within 300 seconds per module, record the module's Dlatch_Count (defined as the number of D-latches inferred during synthesis), and mark the module's latch gate as passed only when its Dlatch_Count equals zero.
4. IF a generated module's Dlatch_Count is greater than zero, THEN THE Test_Harness SHALL mark that module's latch gate as failed and report the failing module identifier and its Dlatch_Count.
5. IF verilator or Yosys terminates with a tool-execution error or exceeds its 300-second timeout for a generated module, THEN THE Test_Harness SHALL mark that module's corresponding gate as failed and report a tool-execution error indicating which tool did not complete.

### Requirement 19: Negative Tests (Test Harness)

**User Story:** As a maintainer, I want negative tests for each safety rule, so that I have evidence the compile-time checks actually fire.

#### Acceptance Criteria

1. WHEN the Test_Harness feeds the Transpiler a program in which at least one state is missing one or more required output assignments, THE Test_Harness SHALL assert that the Transpiler exits with a non-zero exit code, emits no SystemVerilog to standard output, and reports an error message that identifies the total-outputs safety rule as violated and names the offending state.
2. WHEN the Test_Harness feeds the Transpiler a program in which at least one state is missing its mandatory final `else` transition, THE Test_Harness SHALL assert that the Transpiler exits with a non-zero exit code, emits no SystemVerilog to standard output, and reports an error message that identifies the total-transitions safety rule as violated and names the offending state.
3. WHEN the Test_Harness feeds the Transpiler a program in which a transition references a State_Target that is not declared as a state, THE Test_Harness SHALL assert that the Transpiler exits with a non-zero exit code, emits no SystemVerilog to standard output, and reports an error message that identifies the name-resolution safety rule as violated and names the undefined State_Target.

### Requirement 20: Single-Command Harness Execution (Test Harness)

**User Story:** As a maintainer, I want one command to run the whole harness, so that validation is reproducible and easy.

#### Acceptance Criteria

1. WHEN `uv run pytest` is executed as a single command with no manual steps, THE Test_Harness SHALL run, for all three examples, the positive checks (transpile, lint with `verilator --lint-only -Wall`, `$dlatch` count via Yosys, and golden behavioral match) and all negative tests.
2. WHEN all examples transpile, lint with zero warnings, report a `$dlatch` count of zero, and match their goldens on every cycle, AND all negative tests report the expected errors, THE Test_Harness SHALL terminate with a successful (zero) exit status and zero reported failures.
3. IF any example fails transpilation, lint, the `$dlatch` check, or golden behavioral match, THEN THE Test_Harness SHALL report a failure identifying the example and the failed check, and SHALL terminate with a non-zero exit status.
4. IF any negative test does not produce its expected error, THEN THE Test_Harness SHALL report a failure identifying the negative test, and SHALL terminate with a non-zero exit status.
5. IF `verilator` or `yosys` is not available on `PATH`, THEN THE Test_Harness SHALL report a failure indicating the missing tool, and SHALL terminate with a non-zero exit status.

### Requirement 21: Freeze the Transpiler (Freeze)

**User Story:** As a project lead, I want the validated transpiler frozen, so that later experiments cannot silently change the transpiler and confound results.

#### Acceptance Criteria

1. WHEN the Test_Harness reports a passing result under `uv run pytest`, THE feature SHALL produce a Frozen_Record `FROZEN.md` recording the Transpiler version identifier, the freeze date in ISO 8601 format, and confirmation that all three Example_Programs match their goldens on every cycle.
2. IF the Test_Harness reports a failing result, THEN THE feature SHALL NOT produce or update the Frozen_Record, and any existing Frozen_Record SHALL remain unchanged.
3. THE Language_Spec SHALL state that the Transpiler is frozen and SHALL state that any change in model pass-rate must be attributable to language changes rather than Transpiler drift.
4. THE Frozen_Record SHALL state that the Transpiler is modified only through a re-freeze, defined as re-running the full Test_Harness to a passing result and updating the recorded version and date, and never silently during experiments.
5. WHERE later phases change the language or examples, THE Frozen_Record SHALL require a completed re-freeze (a passing Test_Harness result) before any modified Transpiler output is treated as validated.
