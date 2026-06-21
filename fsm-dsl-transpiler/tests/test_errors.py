"""Unit tests for the compile-error hierarchy and source locations.

Covers Requirements 16.2 (diagnostics name the rule/element) and 16.4
(rendered form carries the source location, e.g. line number).
"""

from __future__ import annotations

import pytest

from transpiler.errors import (
    SAFETY_RULES,
    CompileError,
    Loc,
    ParseError,
    SafetyError,
    TypeError_,
)


def test_loc_is_frozen() -> None:
    loc = Loc(file="a.fsm", line=3, column=7)
    assert (loc.file, loc.line, loc.column) == ("a.fsm", 3, 7)
    with pytest.raises(Exception):
        loc.line = 4  # type: ignore[misc]


def test_render_format() -> None:
    err = CompileError(Loc(file="machine.fsm", line=12, column=4), "boom")
    assert err.render() == "machine.fsm:12:4: boom"
    # str() delegates to render().
    assert str(err) == "machine.fsm:12:4: boom"


def test_compile_error_message_is_exception_args() -> None:
    err = CompileError(Loc("f.fsm", 1, 1), "oops")
    assert err.message == "oops"
    # Raisable and catchable as an Exception.
    with pytest.raises(CompileError):
        raise err


def test_parse_error_carries_line() -> None:
    err = ParseError(line=5, column=2, message="unexpected token")
    assert isinstance(err, CompileError)
    assert err.loc.line == 5
    assert err.loc.column == 2
    assert err.render() == "<input>:5:2: unexpected token"


def test_parse_error_with_explicit_file() -> None:
    err = ParseError(line=9, column=1, message="bad", file="prog.fsm")
    assert err.render() == "prog.fsm:9:1: bad"


def test_type_error_subclass() -> None:
    err = TypeError_(Loc("p.fsm", 2, 3), "unknown type 'word'")
    assert isinstance(err, CompileError)
    assert err.render() == "p.fsm:2:3: unknown type 'word'"


@pytest.mark.parametrize("rule", sorted(SAFETY_RULES))
def test_safety_error_accepts_known_rules(rule: str) -> None:
    err = SafetyError(rule, Loc("s.fsm", 4, 1), "state S does not assign output 'x'")
    assert isinstance(err, CompileError)
    assert err.rule == rule
    assert err.render() == "s.fsm:4:1: state S does not assign output 'x'"


def test_safety_rules_are_exactly_the_four_documented() -> None:
    assert SAFETY_RULES == {
        "total_outputs",
        "total_transitions",
        "single_driver",
        "name_resolution",
    }


def test_safety_error_rejects_unknown_rule() -> None:
    with pytest.raises(ValueError):
        SafetyError("not_a_rule", Loc("s.fsm", 1, 1), "msg")


def test_subclass_hierarchy() -> None:
    assert issubclass(ParseError, CompileError)
    assert issubclass(TypeError_, CompileError)
    assert issubclass(SafetyError, CompileError)
    assert issubclass(CompileError, Exception)
