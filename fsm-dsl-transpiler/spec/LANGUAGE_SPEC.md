# FSM_DSL Language Specification

**Version:** 0.1
**Status:** Frozen (see [Freeze Statement](#11-freeze-statement))

FSM_DSL is a minimal, AI-native hardware description language for **Moore**
finite state machines. An author writes *what* a machine does — its states,
its per-state outputs, and its transitions — and a frozen Python transpiler
owns *how* that becomes hardware: state encoding, clocking, reset, and the
three-always-block SystemVerilog structure. The whole-language thesis is that
the low-level Verilog mistakes large language models repeat (inferred latches,
blocking/non-blocking misuse, reset bugs, hand-rolled state codes, multiple
drivers) are made **inexpressible** by the language and **impossible** in the
generated output.

This document is complete enough to implement the transpiler from the spec
alone. It defines the seven constructs, the grammar, the type system, Moore
semantics, the four compile-time safety rules, the construct/rule → hazard
mapping, and the exact commands that validate generated SystemVerilog.

---

## Table of Contents

1. [Lexical Structure](#1-lexical-structure)
2. [The Seven Constructs](#2-the-seven-constructs)
3. [EBNF Grammar](#3-ebnf-grammar)
4. [Type System](#4-type-system)
5. [Implicit Clock and Reset](#5-implicit-clock-and-reset)
6. [Moore Semantics](#6-moore-semantics)
7. [Compile-Time Safety Rules](#7-compile-time-safety-rules)
8. [Construct / Rule → Verilog Hazard Table](#8-construct--rule--verilog-hazard-table)
9. [Validation Commands and Pass Conditions](#9-validation-commands-and-pass-conditions)
10. [A Complete Example](#10-a-complete-example)
11. [Freeze Statement](#11-freeze-statement)

---

## 1. Lexical Structure

- **Identifiers** are an ASCII letter or underscore followed by any number of
  letters, digits, or underscores: `/[a-zA-Z_][a-zA-Z0-9_]*/`.
- **Integer literals** are non-negative decimal integers: `/[0-9]+/`.
- **Keywords** are a closed, case-sensitive set of exactly seven words:
  `machine`, `in`, `out`, `reset`, `state`, `when`, `else`. A token that
  matches a keyword's spelling but differs in letter case (for example
  `Machine`) is **not** a keyword; it lexes as an identifier and will fail to
  parse in keyword position.
- **Comments** begin with `#` and run to the end of the line (excluding the
  newline). FSM_DSL defines no string or quoted tokens, so `#` always starts a
  comment. Removing all comments leaves the surviving token stream unchanged.
- **Whitespace** (spaces, tabs, newlines) is insignificant except as a token
  separator.

There is **exactly one** canonical spelling and **exactly one** syntactic form
for each concept. There are no synonym keywords and no alternative syntaxes.

---

## 2. The Seven Constructs

FSM_DSL has exactly seven constructs. Each is described below with its syntax,
its semantics, and at least one textual example.

### 2.1 Machine Declaration

**Syntax**

```
machine NAME { ... }
```

**Semantics.** Declares the single finite state machine of the source file.
`NAME` is an identifier and becomes the name of the generated SystemVerilog
module. **Exactly one** machine is declared per source file; zero or more than
one is a compile-time error. The machine body contains input declarations,
output declarations, exactly one reset declaration, and one or more state
declarations, in any order. The implicit `clk` and `rst` inputs are added
automatically and must not be declared (see §5).

**Example**

```
machine blinker {
  out bit led
  reset = OFF
  state OFF { led = 0  else -> ON }
  state ON  { led = 1  else -> OFF }
}
```

### 2.2 Input Port Declaration

**Syntax**

```
in TYPE name
```

**Semantics.** Declares an input port readable inside transition guards.
`TYPE` is an FSM_DSL port type (`bit` or `bit[H:L]`, see §4) and `name` is an
identifier unique within the machine. Inputs may only influence the *next
state*, never an output value within the same cycle (Moore, see §6).

**Example**

```
in bit start          # a 1-bit input
in bit[7:0] data      # an 8-bit input vector
```

**Unused inputs are legal.** A declared input need *not* be referenced by any
transition guard, nor need every bit of a vector input be read. The port list is
frequently fixed by an external interface or testbench, and a correct Moore
machine often does not branch on every declared input — reserved/strobe signals,
inputs that would only matter in a Mealy design, or vector inputs only a few
bits of which matter, may legitimately go partly or wholly unread. Such a
program is **never rejected**; rejecting it would fail an otherwise-correct,
interface-conformant design.

To keep the generated SystemVerilog clean under `verilator --lint-only -Wall`
(which would otherwise emit `%Warning-UNUSEDSIGNAL` for a declared-but-unread
input, or for the unread bits of one used only via bit-selects), the
Code_Generator emits a **targeted, per-signal waiver** for exactly those input
ports that are not read at full width: the canonical Verilator "intentionally
unused" read idiom, a single net whose name contains `unused` (so the tool
exempts it) that reads the *whole* of each such input, e.g.

```
wire _unused_ok = &{1'b0, c, f};   // reads unused input `c` and the unread bits of `f`
```

`-Wall` is **never** dropped and no blanket `-Wno-UNUSEDSIGNAL` is used; the
waiver targets only the inputs that are not fully read and nothing else. A
machine whose every input is read at full width emits no waiver and is
byte-for-byte unchanged.

### 2.3 Output Port Declaration

**Syntax**

```
out TYPE name
```

**Semantics.** Declares an output port. `TYPE` is an FSM_DSL port type and
`name` is an identifier unique within the machine. Every output must be
assigned a value in every state (see §7.1). Each output is driven by exactly
one machine (see §7.3).

**Example**

```
out bit done          # a 1-bit output
out bit[1:0] code      # a 2-bit output vector
```

### 2.4 Reset-State Declaration

**Syntax**

```
reset = STATE
```

**Semantics.** Names the state the machine enters on reset. `STATE` must be a
declared state (see §7.4). **Exactly one** reset declaration is required per
machine; zero or more than one is a compile-time error. Reset is synchronous
and active-high in the generated hardware (see §5).

**Example**

```
reset = IDLE
```

### 2.5 State Declaration

**Syntax**

```
state NAME { ... }
```

**Semantics.** Declares one state. `NAME` is an identifier unique within the
machine (duplicate state names are a compile-time error). The body contains
output assignments and transitions. A machine declares one or more states; the
transpiler owns their binary encoding (authors never write state codes).

**Example**

```
state IDLE {
  done = 0
  when start -> RUN
  else -> IDLE
}
```

### 2.6 Output Assignment

**Syntax**

```
name = VALUE
```

**Semantics.** Inside a state body, sets the named output to a constant
non-negative integer `VALUE` for that state. The value must fit the output's
declared width. Because the value depends only on the enclosing state and not
on any input, output assignments are **Moore** (see §6). Every declared output
must be assigned in every state (see §7.1).

**Example**

```
code = 2        # set the 'code' output to 2 while in this state
```

### 2.7 Transition

A transition selects the next state. There are two forms — a guarded `when`
clause and an unconditional `else` fallback — which together are the seventh
construct.

**Syntax**

```
when COND -> STATE      # guarded transition
else -> STATE           # unconditional fallback transition
```

**Semantics.** Within a state, transitions are evaluated **in declared order,
top to bottom**, and the first transition whose condition is true is taken.
`COND` is a boolean expression over input ports (see §3 for the expression
grammar). The final transition of every state must be an `else -> STATE`
clause, which is the always-true default (see §7.2). Every `STATE` target must
be a declared state (see §7.4).

**Example**

```
state RUN {
  done = 0
  when data[0] -> DONE        # first true guard wins
  when busy && !start -> RUN
  else -> RUN                 # mandatory always-true default
}
```

**Guard width semantics (generated SystemVerilog).** A guard is a *boolean*
condition, but FSM_DSL signals may be multiple bits wide. To make the generated
SystemVerilog width-correct — and therefore `verilator --lint-only -Wall` clean
with no `WIDTH` / `WIDTHTRUNC` warnings — the Code_Generator renders guards as
follows:

- **A multi-bit signal in a boolean context means "non-zero".** When a signal
  wider than 1 bit appears as the whole guard or as an operand of `!`, `&&`, or
  `||`, it is reduced with the reduction-OR operator: `f` becomes `(|f)`. So
  `when f` (with `f` 2 bits) means `f != 0`. A 1-bit signal and a bit-select
  (`f[i]`, always 1 bit) are already boolean and pass through unchanged.
- **Comparison literals are width-matched to their signal operand.** In a
  `signal OP literal` comparison the integer literal is sized to the signal's
  declared width, e.g. `f == 5` with `f` 3 bits emits `f == 3'd5`. If a literal
  does not fit that width (e.g. `f == 9` with `f` 2 bits) the program is
  **rejected** with a located error naming the value and width, consistent with
  output-value width handling — sizing it would silently truncate the value.
- **Width-trivial comparisons are folded.** When a comparison is *constant*
  given the signal's width — e.g. `e <= 3` with `e` 2 bits is always true, or
  `e > 3` always false — it is rendered as `1'b1` / `1'b0`. The guard's truth
  value is unchanged, and this avoids Verilator's `CMPCONST` ("comparison is
  constant due to limited range") under `-Wall`. The guard remains legal and is
  never rejected.

These rules are applied by codegen alone; they do not change the surface
language or what the author writes. `-Wall` is never dropped and width warnings
are never suppressed (unlike the benign `UNUSEDSIGNAL` case in §2.2): a width
warning can mask a real truncation, so generated guards are made genuinely
width-correct instead.

---

## 3. EBNF Grammar

The grammar below derives all seven constructs. Every nonterminal that is
referenced is defined, and no defined nonterminal is left unreferenced. The
grammar is unambiguous: each construct begins with a distinct reserved keyword
(or, for an output assignment, an identifier), and the guard-expression rules
use a strict precedence chain, so every valid FSM_DSL program has exactly one
parse.

Notation: `=` defines a rule; `,` is concatenation; `|` is alternation;
`{ x }` is zero-or-more repetitions of `x`; `[ x ]` is an optional `x`;
quoted text is a literal terminal; `(* ... *)` is a comment.

```ebnf
(* ---- Top level ------------------------------------------------------- *)
program            = machine ;                 (* exactly one machine per file *)

(* ---- 1. Machine declaration ------------------------------------------ *)
machine            = "machine" , identifier , "{" , { machine_item } , "}" ;

machine_item       = in_decl
                   | out_decl
                   | reset_decl
                   | state_decl ;

(* ---- 2. Input port declaration --------------------------------------- *)
in_decl            = "in" , port_type , identifier ;

(* ---- 3. Output port declaration -------------------------------------- *)
out_decl           = "out" , port_type , identifier ;

(* ---- 4. Reset-state declaration -------------------------------------- *)
reset_decl         = "reset" , "=" , identifier ;

(* ---- 5. State declaration -------------------------------------------- *)
state_decl         = "state" , identifier , "{" , { state_item } , "}" ;

state_item         = output_assignment
                   | transition ;

(* ---- 6. Output assignment -------------------------------------------- *)
output_assignment  = identifier , "=" , integer ;

(* ---- 7. Transition --------------------------------------------------- *)
transition         = when_transition
                   | else_transition ;

when_transition    = "when" , condition , "->" , identifier ;
else_transition    = "else" , "->" , identifier ;

(* ---- Port types ------------------------------------------------------ *)
port_type          = "bit" , [ "[" , integer , ":" , integer , "]" ] ;

(* ---- Guard condition expression (strict precedence) ------------------ *)
(*   lowest:  ||   then  &&   then comparison   then unary !   then primary *)
condition          = or_expr ;
or_expr            = and_expr , { "||" , and_expr } ;
and_expr           = not_expr , { "&&" , not_expr } ;
not_expr           = "!" , not_expr
                   | comparison ;
comparison         = primary , [ comp_op , primary ] ;
comp_op            = "==" | "!=" | "<=" | ">=" | "<" | ">" ;
primary            = bit_select
                   | identifier
                   | integer
                   | "(" , condition , ")" ;
bit_select         = identifier , "[" , integer , "]" ;

(* ---- Terminals ------------------------------------------------------- *)
identifier         = ( letter | "_" ) , { letter | digit | "_" } ;
integer            = digit , { digit } ;
letter             = "A" | ... | "Z" | "a" | ... | "z" ;
digit              = "0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" ;

(* ---- Lexical (stripped before parsing) ------------------------------- *)
comment            = "#" , { any_character_except_newline } ;
```

**Notes on faithfulness to the implementation.** The reference parser
(`transpiler/grammar.lark`, LALR(1)) admits zero-or-more machines syntactically
(`start: machine*`) and enforces the "exactly one machine per file" rule in the
AST builder so that a *located* diagnostic — not a bare parse error — is
produced for zero or more than one machine. The grammar above states the
language rule (`program = machine`) directly. Likewise, the port type is
captured syntactically as an identifier optionally followed by `[H:L]`; the
requirement that the type name is exactly `bit` and that `H ≥ L ≥ 0` is checked
in the AST builder (see §4) so that an unrecognized type or a bad index range
yields a located error rather than an opaque parse failure.

---

## 4. Type System

FSM_DSL has exactly **two** types.

| Type      | Width            | Constraints                                            |
| --------- | ---------------- | ------------------------------------------------------ |
| `bit`     | 1                | a single-bit signal                                    |
| `bit[H:L]`| `H − L + 1` bits | `H` and `L` are integers with `H ≥ L ≥ 0`, range 0..65535 |

- **`bit`** declares a 1-bit-wide port. It generates a SystemVerilog signal of
  width 1 with no range, e.g. `input logic a`.
- **`bit[H:L]`** declares a vector spanning index `H` down to index `L`. Its
  width is `H − L + 1`. It generates a SystemVerilog vector signal, e.g.
  `output logic [7:0] q` for `bit[7:0]`.

A declaration is **rejected at compile time** (no signal is emitted) when:

- the index range is invalid — `H < L`, or `H` or `L` is negative, or an index
  is non-integer or outside `0..65535`; the error names the invalid index
  range; or
- the type token is anything other than `bit` or `bit[H:L]`; the error names
  the unrecognized type.

An output assignment's integer `VALUE` must be representable in the output's
declared width.

---

## 5. Implicit Clock and Reset

Every machine has two implicit input ports that the author never declares:

- **`clk`** — the clock. The generated state register is clocked on its rising
  edge (`always_ff @(posedge clk)`).
- **`rst`** — the reset. It is **synchronous** (sampled only on the rising edge
  of `clk`, no asynchronous term) and **active-high**: while `rst` is high, the
  next rising clock edge loads the state register with the state named by the
  `reset` declaration, taking precedence over any transition.

Declaring a port named exactly `clk` or `rst` (case-sensitive, exact match) is
a compile-time error that names the offending reserved name and its source
location; no module is emitted and the source is left unmodified. When no
reserved-name error is present, the generator adds `clk` and `rst` as input
ports on the module automatically.

---

## 6. Moore Semantics

FSM_DSL is a **Moore** language: **each `out` value is a function of the
current state only, and is independent of input values within the same cycle.**

Concretely:

- An output's value is fixed by the output assignment in the currently active
  state. It does not depend on any input in that cycle.
- Inputs influence only the **next** state, through transition guards
  (`when COND -> STATE`). A change on an input can therefore change an output
  only on a subsequent cycle, after the state register has advanced.
- The generated output logic is a single combinational block driven by `state`
  alone (`always_comb` whose `case` switches on `state`), which is what makes
  the outputs glitch-free and the machine a true Moore FSM.

This rules out Mealy-style outputs (outputs that respond combinationally to
inputs within the same cycle); they are not expressible in FSM_DSL.

---

## 7. Compile-Time Safety Rules

The Safety_Checker enforces four rules. **All four run to completion** before
any SystemVerilog is generated, so every violation in a program is reported
rather than stopping at the first. **Any violation is a compile-time error:**
the transpiler writes the diagnostic to standard error, writes nothing to
standard output, and exits with a non-zero status. The four rules are:

### 7.1 Total Outputs

**Triggering condition.** For every declared state `S` and every declared
output `x`, if `S` does not assign `x`, that is a violation. A state that
leaves several outputs unassigned yields one error per unassigned output.

**Diagnostic form.** `state S does not assign output 'x'`

This guarantees every output has a defined value in every state, so no output
can ever be left unassigned on some path.

### 7.2 Total Transitions

**Triggering condition.** If a declared state's transition list is empty, or
its **last** transition is not an `else -> STATE` clause, that is a violation.
One error is emitted per offending state.

**Diagnostic form.**
`state S does not end with a final 'else -> STATE' transition`

This guarantees every state defines a next state for every input combination
(the trailing `else` is the always-true default).

### 7.3 Single Driver

**Triggering condition.** Two situations are violations:

- **Duplicate declaration** — the same output name is declared by more than one
  machine. One error is emitted per duplicate declaration, naming the output
  and the source location of every declaring machine.
- **Cross-machine assignment** — a state assigns an output that is declared by
  a *different* machine than the one the state belongs to. One error is emitted
  per offending assignment, naming the output, the assigning state and machine,
  and the machine that declares the output.

Every detected violation is reported, not just the first.

This guarantees each output is driven by exactly one machine.

### 7.4 Name Resolution

**Triggering condition.** Every transition target (including the target of a
final `else -> STATE` clause) and the `reset = STATE` target must name a
declared state. Each unresolved reference is a violation; one error is emitted
per dangling reference.

**Diagnostic forms.**
`transition in state S targets undeclared state 'T'`
`reset target 'T' is not a declared state`

This guarantees there are no dangling state references.

---

## 8. Construct / Rule → Verilog Hazard Table

Each row names the specific Verilog coding hazard that the construct or rule
removes. There is one row per construct (7) and one row per safety rule (4),
plus rows for the codegen-level unused-input waiver (§2.2) and guard-width
rendering (§2.7).

| # | Construct or Rule | Verilog hazard it removes |
| - | ----------------- | ------------------------- |
| 1 | `machine` declaration | Hand-written module scaffolding errors: mismatched `module`/`endmodule`, mis-wired port lists, and missing or duplicated `clk`/`rst` plumbing. One file → exactly one module with auto clock/reset. |
| 2 | `in` (input port) declaration | Implicit-net inputs and width mismatches. A typed input cannot become an accidental 1-bit implicit wire of the wrong width. |
| 3 | `out` (output port) declaration | Implicit-net / wrong-width outputs and `reg`/`wire` (`logic`) type confusion on output signals. The type fixes the emitted width and signal kind. |
| 4 | `reset = STATE` declaration | Reset bugs: asynchronous-vs-synchronous confusion, wrong reset polarity, and uninitialized state. Reset is forced synchronous, active-high, and confined to the clocked block. |
| 5 | `state` declaration | Hand-rolled state-encoding errors: overlapping, illegal, or wrong-width state codes. The transpiler owns the `enum logic` encoding and its width. |
| 6 | output assignment (`name = VALUE`) | Inferred latches from unassigned outputs and Mealy-style input-dependent output glitches. Each output is a constant per state (Moore), assigned in a defaulted combinational block. |
| 7 | transition (`when` / `else`) | Incomplete next-state logic (inferred latch on the state register) and ambiguous transition priority. First-match ordering plus a mandatory `else` makes next-state total and deterministic. |
| 8 | Safety rule: **Total Outputs** | Inferred latch caused by an output left unassigned on some path through a state. |
| 9 | Safety rule: **Total Transitions** | Inferred latch on the state register caused by an incomplete `case`/`if` with no covering default. |
| 10 | Safety rule: **Single Driver** | Multiple-driver bus contention (`X`/unknown values) from an output driven by more than one source. |
| 11 | Safety rule: **Name Resolution** | Dangling / undefined state references that cause elaboration errors or undefined next-state behavior. |
| 12 | Codegen waiver: **Unused input** | Verilator `UNUSEDSIGNAL` (`%Warning-UNUSEDSIGNAL` under `-Wall`) on a declared input that no transition reads. Handled by a *scoped codegen waiver* (see §2.2), **not** by forbidding the port: the generator emits a targeted, per-signal "intentionally unused" read so the module stays `-Wall` clean while remaining interface-conformant. |
| 13 | Codegen rendering: **Guard width** | Verilator `WIDTH` / `WIDTHTRUNC` (`%Warning-WIDTHTRUNC`, e.g. "Logical operator IF expects 1 bit, but 'f' generates N bits") from a multi-bit signal used in a boolean guard, or an unsized literal compared against a narrow signal; and `CMPCONST` ("comparison is constant due to limited range") from a width-trivial comparison like `e <= 3` on a 2-bit `e`. Handled by *width-correct codegen* (see §2.7): multi-bit boolean operands are reduced with `|`, comparison literals are sized to the signal width, and width-trivial comparisons are folded to `1'b1`/`1'b0` — **not** by suppressing the warnings (which could mask a real truncation). An over-wide comparison literal is rejected at compile time. |

---

## 9. Validation Commands and Pass Conditions

Generated SystemVerilog (and each golden file) is validated by two external
tools with the following exact commands and pass conditions.

### 9.1 Lint — Verilator

```
verilator --lint-only -Wall MODULE.sv
```

**Pass condition:** Verilator reports **zero warnings and zero errors** and the
process terminates with a **success (zero) exit status**. Any warning or error
fails the lint gate; each reported warning is surfaced with its source file
name and line number and the checked file is left unmodified.

### 9.2 Latch check — Yosys synthesis

```
yosys -p "read_verilog -sv MODULE.sv; synth; stat"
```

**Pass condition:** the synthesis statistics report a **`$dlatch` cell count of
exactly zero** (`Dlatch_Count == 0`). Any `$dlatch` cell fails the latch gate;
the failing module identifier and its `Dlatch_Count` are reported.

A module is considered correct only when **both** gates pass: zero Verilator
warnings/errors **and** zero inferred latches from Yosys. If either tool
terminates with an execution error or exceeds its per-module time budget, the
corresponding gate is marked failed.

---

## 10. A Complete Example

A "101" overlapping sequence detector — a complete, valid FSM_DSL program that
exercises every construct and passes all four safety rules:

```
# seq_detect_101.fsm — asserts 'y' on the cycle that completes a "101" pattern.
machine seq_detect_101 {
  in  bit x          # serial input bit
  out bit y          # 1 only when a "101" completes

  reset = S0

  state S0 {         # seen nothing / reset
    y = 0
    when x -> S1     # saw '1'
    else  -> S0
  }
  state S1 {         # saw "1"
    y = 0
    when x -> S1     # "11" -> stay, last bit is still '1'
    else  -> S2      # saw "10"
  }
  state S2 {         # saw "10"
    y = 0
    when x -> S3     # saw "101" -> completed next cycle
    else  -> S0
  }
  state S3 {         # "101" just completed (overlapping)
    y = 1
    when x -> S1     # overlap: this '1' can start a new "1"
    else  -> S2
  }
}
```

---

## 11. Freeze Statement

**The Transpiler is frozen.** Once the Test_Harness passes under
`uv run pytest`, the transpiler is recorded as frozen (version identifier and
ISO 8601 freeze date) in `FROZEN.md`, and it is modified **only through a
re-freeze** — re-running the full Test_Harness to a passing result and updating
the recorded version and date — never silently during experiments.

Because the transpiler is fixed, **any change in model pass-rate must be
attributable to changes in the language (or examples), not to transpiler
drift.** Every code-generation decision lives in the frozen transpiler, so an
experiment that changes results has changed the *language* it measures, not the
machinery that compiles it. Any later phase that modifies the language or
examples requires a completed re-freeze (a passing Test_Harness result) before
the modified transpiler output is treated as validated.
