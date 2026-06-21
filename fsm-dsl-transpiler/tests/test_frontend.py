"""Unit tests for the AST builder (``transpiler.ast.build_ast``).

Covers the structural and type validation performed when transforming a lark
parse tree into the typed model (task 3.2):
  * building a valid program with locations attached;
  * scalar and vector port widths (Req 2.1-2.4);
  * invalid / unrecognized type rejection (Req 2.5, 2.6);
  * reserved ``clk``/``rst`` port-name rejection (Req 3.2, 3.3);
  * the exactly-one-machine rule (Req 1.2, 1.3);
  * the exactly-one-reset rule (Req 1.6, 1.7);
  * duplicate state-name rejection (Req 1.8, 1.9).
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from transpiler.ast import (
    Condition,
    Machine,
    OutputAssignment,
    Port,
    Program,
    State,
    Transition,
    build_ast,
)
from transpiler.errors import CompileError, TypeError_
from transpiler.parser import parse

VALID_PROGRAM = """\
# a tiny two-state machine
machine blink {
    in bit go
    out bit led
    reset = OFF

    state OFF {
        led = 0
        when go -> ON
        else -> OFF
    }

    state ON {
        led = 1
        when go -> ON
        else -> OFF
    }
}
"""


def _build(source: str, file: str = "prog.fsm") -> Program:
    return build_ast(parse(source, file=file), source_file=file)


# --- a valid program -------------------------------------------------------
def test_build_valid_program_structure() -> None:
    prog = _build(VALID_PROGRAM)
    assert isinstance(prog, Program)
    assert prog.source_file == "prog.fsm"
    assert len(prog.machines) == 1

    m = prog.machines[0]
    assert isinstance(m, Machine)
    assert m.name == "blink"
    assert m.reset_state == "OFF"
    assert [p.name for p in m.inputs] == ["go"]
    assert [p.name for p in m.outputs] == ["led"]
    assert [s.name for s in m.states] == ["OFF", "ON"]

    off = m.states[0]
    assert isinstance(off.outputs[0], OutputAssignment)
    assert off.outputs[0].output_name == "led"
    assert off.outputs[0].value.bits == 0
    # transitions preserve declared order, ending with the else clause
    assert [t.kind for t in off.transitions] == ["when", "else"]
    assert off.transitions[-1].target == "OFF"


def test_build_attaches_locations() -> None:
    prog = _build(VALID_PROGRAM)
    m = prog.machines[0]
    # every node carries the source file and a positive line/column
    assert m.loc.file == "prog.fsm"
    assert m.loc.line >= 1 and m.loc.column >= 1
    assert m.inputs[0].loc.file == "prog.fsm"
    assert m.states[0].transitions[0].loc.line >= 1


def test_when_condition_text_is_reconstructed() -> None:
    src = """\
machine m {
    in bit a
    in bit b
    out bit y
    reset = S0
    state S0 {
        y = 0
        when a && b -> S0
        else -> S0
    }
}
"""
    prog = _build(src)
    when = prog.machines[0].states[0].transitions[0]
    assert isinstance(when.condition, Condition)
    assert "a" in when.condition.text
    assert "&&" in when.condition.text
    assert "b" in when.condition.text


# --- vector widths ---------------------------------------------------------
def test_vector_width_from_index_range() -> None:
    src = """\
machine counter {
    in bit[1:0] sel
    out bit[3:0] q
    reset = S0
    state S0 {
        q = 0
        else -> S0
    }
}
"""
    prog = _build(src)
    m = prog.machines[0]
    assert m.inputs[0].type.width == 2
    assert m.inputs[0].type.high == 1 and m.inputs[0].type.low == 0
    assert m.outputs[0].type.width == 4


def test_scalar_width_is_one() -> None:
    prog = _build(VALID_PROGRAM)
    assert prog.machines[0].inputs[0].type.width == 1


# --- invalid types ---------------------------------------------------------
def test_unrecognized_type_is_rejected() -> None:
    src = """\
machine m {
    in byte go
    out bit led
    reset = S0
    state S0 { led = 0  else -> S0 }
}
"""
    with pytest.raises(TypeError_) as excinfo:
        _build(src)
    assert "unrecognized type" in excinfo.value.message
    assert excinfo.value.loc.line >= 1


def test_vector_high_less_than_low_is_rejected() -> None:
    src = """\
machine m {
    out bit[0:3] q
    reset = S0
    state S0 { q = 0  else -> S0 }
}
"""
    with pytest.raises(TypeError_) as excinfo:
        _build(src)
    assert "H >= L" in excinfo.value.message


def test_vector_index_out_of_range_is_rejected() -> None:
    src = """\
machine m {
    out bit[65536:0] q
    reset = S0
    state S0 { q = 0  else -> S0 }
}
"""
    with pytest.raises(TypeError_) as excinfo:
        _build(src)
    assert "0..65535" in excinfo.value.message


# --- reserved names --------------------------------------------------------
@pytest.mark.parametrize("reserved", ["clk", "rst"])
def test_reserved_port_name_is_rejected(reserved: str) -> None:
    src = f"""\
machine m {{
    in bit {reserved}
    out bit led
    reset = S0
    state S0 {{ led = 0  else -> S0 }}
}}
"""
    with pytest.raises(CompileError) as excinfo:
        _build(src)
    assert reserved in excinfo.value.message
    assert "reserved" in excinfo.value.message


def test_non_reserved_clock_like_name_is_accepted() -> None:
    # case-sensitive exact match only: `Clk`/`clock` are ordinary identifiers
    src = """\
machine m {
    in bit Clk
    in bit clock
    out bit led
    reset = S0
    state S0 { led = 0  else -> S0 }
}
"""
    prog = _build(src)
    assert {p.name for p in prog.machines[0].inputs} == {"Clk", "clock"}


# --- machine count ---------------------------------------------------------
def test_zero_machines_is_rejected() -> None:
    with pytest.raises(CompileError) as excinfo:
        _build("# just a comment\n")
    assert "no machine" in excinfo.value.message


def test_multiple_machines_is_rejected() -> None:
    src = """\
machine a {
    out bit x
    reset = S0
    state S0 { x = 0  else -> S0 }
}
machine b {
    out bit y
    reset = S0
    state S0 { y = 0  else -> S0 }
}
"""
    with pytest.raises(CompileError) as excinfo:
        _build(src)
    assert "2 machines" in excinfo.value.message


# --- reset declarations ----------------------------------------------------
def test_missing_reset_is_rejected() -> None:
    src = """\
machine m {
    out bit led
    state S0 { led = 0  else -> S0 }
}
"""
    with pytest.raises(CompileError) as excinfo:
        _build(src)
    assert "no reset declaration" in excinfo.value.message


def test_multiple_resets_are_rejected() -> None:
    src = """\
machine m {
    out bit led
    reset = S0
    reset = S0
    state S0 { led = 0  else -> S0 }
}
"""
    with pytest.raises(CompileError) as excinfo:
        _build(src)
    assert "reset declarations" in excinfo.value.message


# --- duplicate states ------------------------------------------------------
def test_duplicate_state_names_are_rejected() -> None:
    src = """\
machine m {
    out bit led
    reset = S0
    state S0 { led = 0  else -> S0 }
    state S0 { led = 1  else -> S0 }
}
"""
    with pytest.raises(CompileError) as excinfo:
        _build(src)
    assert "duplicate state" in excinfo.value.message
    assert "S0" in excinfo.value.message


# ---------------------------------------------------------------------------
# Property-based test
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 5: Vector width matches the declared
# index range
#
# Validates: Requirements 2.2, 2.3, 2.4
#
# For any port declared `bit[H:L]` with valid indices (H >= L >= 0), the built
# signal spans H down to L with width H - L + 1; a port declared `bit` yields a
# width-1 signal (high == low == 0). We generate a declared port type (scalar
# `bit` or a vector `bit[H:L]`), embed it in a minimal program that parses and
# builds, then assert the resulting Port.type matches the declared range.


@st.composite
def _declared_port_types(draw: st.DrawFn) -> tuple[str, int, int]:
    """Draw a port type as ``(rendered_source, expected_high, expected_low)``.

    Includes the scalar ``bit`` case (width 1, high == low == 0) and vector
    ``bit[H:L]`` cases with ``0 <= L <= H`` (upper bound kept modest for fast
    tests while still exercising single- and multi-bit widths).
    """
    if draw(st.booleans()):
        return "bit", 0, 0
    low = draw(st.integers(min_value=0, max_value=32))
    width = draw(st.integers(min_value=1, max_value=32))
    high = low + width - 1
    return f"bit[{high}:{low}]", high, low


@settings(max_examples=200, deadline=None)
@given(_declared_port_types(), st.sampled_from(["in", "out"]))
def test_vector_width_matches_index_range(
    case: tuple[str, int, int], direction: str
) -> None:
    type_src, high, low = case
    # A minimal program that declares exactly one port of the drawn type and
    # parses/builds (build_ast performs structural + type validation only).
    src = (
        "machine m {\n"
        f"    {direction} {type_src} p\n"
        "    reset = S0\n"
        "    state S0 {\n"
        "        else -> S0\n"
        "    }\n"
        "}\n"
    )
    prog = build_ast(parse(src, file="<input>"), source_file="<input>")
    m = prog.machines[0]
    ports = m.inputs if direction == "in" else m.outputs
    assert len(ports) == 1
    port_type = ports[0].type

    # The built signal spans H down to L with width H - L + 1 (Req 2.2, 2.4).
    assert port_type.high == high
    assert port_type.low == low
    assert port_type.width == high - low + 1

    # A scalar `bit` yields a width-1 signal with high == low == 0 (Req 2.1/2.3).
    if type_src == "bit":
        assert port_type.width == 1
        assert port_type.high == 0
        assert port_type.low == 0


# ---------------------------------------------------------------------------
# Property-based test
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 6: Invalid types are rejected without
# emitting a signal
#
# Validates: Requirements 2.5, 2.6
#
# For any port type token that is neither `bit` nor a well-formed `bit[H:L]`
# with H >= L >= 0 integer indices, the declaration SHALL be rejected with a
# located error and no SystemVerilog signal SHALL be emitted for that port.
# Because build_ast raises before producing a Program, "no signal emitted" is
# witnessed by the exception (no Program is returned).
#
# Reachable invalid-type families via FSM_DSL source:
#   1. Unrecognized type names: any identifier other than `bit` (and not a
#      reserved keyword, which would be a parse error rather than a type
#      error), e.g. "byte", "word", "logic", "Bit", "BIT".
#   2. Vector with H < L: `bit[H:L]` where the high index is below the low one.
# Negative and non-integer indices cannot be lexed (INT is /[0-9]+/), so they
# are unreachable from source text and need not be generated here.

# The closed, case-sensitive keyword set. A keyword in type position lexes as a
# keyword and fails to parse (ParseError), so we keep generated type names out
# of this set to ensure the AST builder reaches type validation (TypeError_).
_KEYWORDS = frozenset(
    {"machine", "in", "out", "reset", "state", "when", "else"}
)

# Identifiers matching the grammar's NAME terminal: /[a-zA-Z_][a-zA-Z0-9_]*/.
_identifiers = st.from_regex(r"[a-zA-Z_][a-zA-Z0-9_]*", fullmatch=True)


@st.composite
def _invalid_type_tokens(draw: st.DrawFn) -> str:
    """Draw an invalid port-type token rendered as it appears in source.

    Either an unrecognized scalar type name (an identifier != ``bit`` and not a
    reserved keyword) or a vector range ``bit[H:L]`` with ``H < L``.
    """
    if draw(st.booleans()):
        # Family 1: unrecognized type name (covers misspellings and case
        # variants like "Bit"/"BIT" as well as arbitrary identifiers).
        name = draw(
            _identifiers.filter(lambda s: s != "bit" and s not in _KEYWORDS)
        )
        return name
    # Family 2: vector with H < L. low >= 1 leaves room for high in 0..low-1;
    # both indices stay in 0..65535 so this exercises the H >= L rule (not the
    # out-of-range rule).
    low = draw(st.integers(min_value=1, max_value=65535))
    high = draw(st.integers(min_value=0, max_value=low - 1))
    return f"bit[{high}:{low}]"


@settings(max_examples=200, deadline=None)
@given(_invalid_type_tokens(), st.sampled_from(["in", "out"]))
def test_invalid_types_are_rejected(type_token: str, direction: str) -> None:
    # A minimal program that parses but declares one port of the invalid type.
    src = (
        "machine m {\n"
        f"    {direction} {type_token} p\n"
        "    out bit led\n"
        "    reset = S0\n"
        "    state S0 {\n"
        "        led = 0\n"
        "        else -> S0\n"
        "    }\n"
        "}\n"
    )

    # The declaration is rejected with a located type error; because the
    # exception is raised, build_ast returns no Program and emits no signal.
    with pytest.raises(TypeError_) as excinfo:
        build_ast(parse(src, file="<input>"), source_file="<input>")

    # The error indicates the problem and carries a usable source location.
    assert excinfo.value.message
    assert excinfo.value.loc.line >= 1
    assert excinfo.value.loc.column >= 1


# ---------------------------------------------------------------------------
# Property-based test
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 7: Reserved clock/reset names are
# rejected; valid machines gain clk and rst
#
# Validates: Requirements 3.2, 3.3, 3.4
#
# Two sub-properties:
#   1. (Req 3.2, 3.3) For any program that declares a port named exactly "clk"
#      or "rst" (case-sensitive, exact match), build_ast raises a located
#      CompileError naming the offending reserved identifier, and no Program /
#      module is produced (the raised exception witnesses "no module emitted").
#   2. (Req 3.4) For any otherwise-valid program with no reserved-name
#      violation, the machine builds and `clk` / `rst` are NOT among the
#      author-declared ports (they are implicit, added only at codegen). When
#      transpiler.codegen.generate is available (not a stub), the emitted module
#      header additionally includes `clk` and `rst` as input ports.

from transpiler import codegen as _codegen
from tests.strategies import render_program, valid_program

_RESERVED_PORT_NAMES = ("clk", "rst")


@st.composite
def _program_with_reserved_port(draw: st.DrawFn) -> tuple[str, str]:
    """Render a valid program then inject a reserved-name port declaration.

    Returns ``(source, reserved_name)`` where ``source`` is valid FSM_DSL with a
    single ``in bit <reserved>`` line inserted as the machine's first item, so
    the program parses cleanly but violates the reserved-name rule (Req 3.2).
    """
    program = draw(valid_program())
    reserved = draw(st.sampled_from(_RESERVED_PORT_NAMES))
    source = render_program(program)
    head, sep, tail = source.partition("\n")
    # `head` is `machine NAME {`; insert the reserved port as the first item.
    return f"{head}{sep}    in bit {reserved}{sep}{tail}", reserved


@settings(max_examples=150, deadline=None)
@given(_program_with_reserved_port())
def test_reserved_clk_rst_names_are_rejected(case: tuple[str, str]) -> None:
    source, reserved = case

    # Sub-property 1 (Req 3.2, 3.3): a port named exactly clk/rst is rejected
    # with a located CompileError naming the reserved identifier; because the
    # exception is raised, build_ast returns no Program (no module emitted).
    with pytest.raises(CompileError) as excinfo:
        build_ast(parse(source, file="<input>"), source_file="<input>")

    assert reserved in excinfo.value.message
    assert "reserved" in excinfo.value.message
    assert excinfo.value.loc.line >= 1
    assert excinfo.value.loc.column >= 1


@settings(max_examples=150, deadline=None)
@given(valid_program())
def test_valid_machine_excludes_clk_rst_and_codegen_adds_them(
    program: Program,
) -> None:
    source = render_program(program)

    # Sub-property 2 (Req 3.4), model level: the program builds and the
    # author-declared ports never include the implicit clk/rst names.
    built = build_ast(parse(source, file="<input>"), source_file="<input>")
    assert len(built.machines) == 1
    machine = built.machines[0]
    declared = {p.name for p in machine.inputs} | {p.name for p in machine.outputs}
    for reserved in _RESERVED_PORT_NAMES:
        assert reserved not in declared

    # Sub-property 2 (Req 3.4), codegen level: if generate() is implemented
    # (task 7.5), the emitted module header adds clk and rst as input ports.
    # While generate() is still a stub it raises NotImplementedError, so this
    # half is skipped until task 7.5 lands.
    try:
        emitted = _codegen.generate(machine)
    except NotImplementedError:
        return
    assert "input" in emitted and "clk" in emitted
    assert "input" in emitted and "rst" in emitted


# ---------------------------------------------------------------------------
# Property-based test
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 4: Exactly one machine yields exactly
# one module; otherwise rejection
#
# Validates: Requirements 1.2, 1.3
#
# *For any* source program, transpilation emits exactly one SystemVerilog
# module if and only if the program declares exactly one machine; a program
# declaring zero or more than one machine produces a compile-time error, writes
# nothing to stdout, and exits non-zero.
#
# This test exercises the build/codegen layer (the CLI stdout/exit aspects are
# covered by Property 14 / task 8.2):
#   1. A valid single-machine program builds with exactly one machine, and
#      ``codegen.generate`` produces exactly one module (one "module " token).
#      While ``generate`` is still a stub (NotImplementedError, task 7.5), the
#      single-machine build is still asserted.
#   2. Zero machines (comment-only / whitespace-only source) raises a located
#      CompileError -- no Program, hence no module emitted.
#   3. N >= 2 machines (concatenated rendered machines with distinct names)
#      raises a located CompileError -- no Program, hence no module emitted.

from dataclasses import replace as _replace

from tests.strategies import render_machine, valid_machine


@st.composite
def _comment_only_source(draw: st.DrawFn) -> str:
    """Draw a source file containing zero machine declarations.

    The file is made only of blank lines and ``#`` line comments, so it parses
    cleanly (``start: machine*`` admits zero machines) but declares no machine.
    """
    n = draw(st.integers(min_value=0, max_value=5))
    lines: list[str] = []
    for _ in range(n):
        if draw(st.booleans()):
            text = draw(
                st.text(
                    alphabet=st.characters(blacklist_characters="\n"),
                    max_size=24,
                )
            )
            lines.append(f"# {text}")
        else:
            lines.append("")
    return "\n".join(lines) + "\n"


@st.composite
def _multi_machine_source(draw: st.DrawFn) -> tuple[str, int]:
    """Render 2..3 valid machines (distinct names) into one source file.

    Returns ``(source, machine_count)``. Machines are renamed ``mach0``,
    ``mach1``, ... so their declarations carry distinct, valid identifiers and
    the only violated rule is the exactly-one-machine rule.
    """
    n = draw(st.integers(min_value=2, max_value=3))
    machines = [draw(valid_machine()) for _ in range(n)]
    renamed = [_replace(m, name=f"mach{i}") for i, m in enumerate(machines)]
    return "\n".join(render_machine(m) for m in renamed), n


@settings(max_examples=150, deadline=None)
@given(valid_program())
def test_single_machine_yields_exactly_one_module(program: Program) -> None:
    source = render_program(program)

    # Exactly one machine builds successfully (Req 1.2).
    built = build_ast(parse(source, file="<input>"), source_file="<input>")
    assert len(built.machines) == 1
    machine = built.machines[0]

    # Codegen emits exactly one module for the single machine. While generate()
    # is still a stub (task 7.5) it raises NotImplementedError; in that case the
    # single-machine build above is the assertion we can make.
    try:
        emitted = _codegen.generate(machine)
    except NotImplementedError:
        return
    assert emitted.count("module ") == 1


@settings(max_examples=150, deadline=None)
@given(_comment_only_source())
def test_zero_machines_are_rejected(source: str) -> None:
    # Zero machines: a located compile-time error and no Program (no module).
    with pytest.raises(CompileError) as excinfo:
        build_ast(parse(source, file="<input>"), source_file="<input>")
    assert "no machine" in excinfo.value.message
    assert excinfo.value.loc.line >= 1
    assert excinfo.value.loc.column >= 1


@settings(max_examples=150, deadline=None)
@given(_multi_machine_source())
def test_multiple_machines_are_rejected(case: tuple[str, int]) -> None:
    source, count = case
    # More than one machine: a located compile-time error and no Program.
    with pytest.raises(CompileError) as excinfo:
        build_ast(parse(source, file="<input>"), source_file="<input>")
    assert f"{count} machines" in excinfo.value.message
    assert excinfo.value.loc.line >= 1
    assert excinfo.value.loc.column >= 1


# ---------------------------------------------------------------------------
# Property-based test
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 8: Duplicate state names are rejected
#
# Validates: Requirements 1.9
#
# For any machine in which two or more states share a name, the AST builder
# reports a compile-time error naming the duplicated state and emits no module.
# The duplicate-state check is structural and performed at build_ast time, so a
# program whose only violation is a repeated state name parses cleanly (the
# grammar admits multiple `state` blocks) yet fails at build_ast.
#
# We use the `duplicate_state` perturbation, which takes a valid machine and
# appends a copy of one of its existing states, producing a single machine with
# a repeated state name. Rendering it yields parseable source whose sole defect
# is the duplicate; build_ast must raise a located CompileError that mentions
# "duplicate" and names the offending state.

from tests.strategies import duplicate_state


@settings(max_examples=200, deadline=None)
@given(duplicate_state())
def test_duplicate_state_names_are_rejected_property(
    case: tuple[Program, str],
) -> None:
    program, kind = case
    assert kind == "duplicate_state"

    # The perturbation repeats exactly one state within the single machine.
    machine = program.machines[0]
    state_names = [s.name for s in machine.states]
    duplicated = next(
        name for name in state_names if state_names.count(name) > 1
    )

    source = render_program(program)

    # The source parses cleanly (the duplicate is a structural, not syntactic,
    # defect), then build_ast rejects it with a located compile-time error.
    with pytest.raises(CompileError) as excinfo:
        build_ast(parse(source, file="<input>"), source_file="<input>")

    # The diagnostic names the duplicated state and carries a usable location;
    # because the exception is raised, build_ast returns no Program (no module).
    assert "duplicate state" in excinfo.value.message
    assert duplicated in excinfo.value.message
    assert excinfo.value.loc.line >= 1
    assert excinfo.value.loc.column >= 1
