"""Unit tests for the AST data model.

Covers the structural invariants encoded in the frozen dataclasses (Req 2.1,
2.2): the ``PortType.width`` computation, immutability, the ``Loc`` re-export,
and the condition/kind invariant on transitions.
"""

from __future__ import annotations

import pytest

from transpiler import ast
from transpiler.ast import (
    Condition,
    Loc,
    Machine,
    OutputAssignment,
    Port,
    PortType,
    Program,
    State,
    Transition,
    Value,
)
from transpiler.errors import Loc as ErrorsLoc


def _loc() -> Loc:
    return Loc(file="m.fsm", line=1, column=1)


def test_loc_is_reexported_from_errors() -> None:
    # ast.Loc must be the very same type as errors.Loc, not a redefinition.
    assert ast.Loc is ErrorsLoc


def test_port_type_scalar_width() -> None:
    assert PortType(high=0, low=0).width == 1


@pytest.mark.parametrize(
    ("high", "low", "expected"),
    [(0, 0, 1), (7, 0, 8), (3, 1, 3), (15, 8, 8), (65535, 0, 65536)],
)
def test_port_type_vector_width(high: int, low: int, expected: int) -> None:
    assert PortType(high=high, low=low).width == expected


def test_port_type_rejects_high_less_than_low() -> None:
    with pytest.raises(ValueError):
        PortType(high=0, low=3)


def test_port_type_rejects_negative_low() -> None:
    with pytest.raises(ValueError):
        PortType(high=2, low=-1)


def test_port_type_is_frozen() -> None:
    pt = PortType(high=3, low=0)
    with pytest.raises(Exception):
        pt.high = 4  # type: ignore[misc]


def test_port_construction_and_direction_validation() -> None:
    p = Port(direction="in", type=PortType(0, 0), name="go", loc=_loc())
    assert p.direction == "in"
    assert p.type.width == 1
    with pytest.raises(ValueError):
        Port(direction="inout", type=PortType(0, 0), name="x", loc=_loc())


def test_value_rejects_negative() -> None:
    assert Value(bits=5, loc=_loc()).bits == 5
    with pytest.raises(ValueError):
        Value(bits=-1, loc=_loc())


def test_when_transition_requires_condition() -> None:
    cond = Condition(text="go", loc=_loc())
    t = Transition(kind="when", condition=cond, target="S1", loc=_loc())
    assert t.condition is cond
    with pytest.raises(ValueError):
        Transition(kind="when", condition=None, target="S1", loc=_loc())


def test_else_transition_forbids_condition() -> None:
    t = Transition(kind="else", condition=None, target="S0", loc=_loc())
    assert t.condition is None
    with pytest.raises(ValueError):
        Transition(
            kind="else",
            condition=Condition(text="go", loc=_loc()),
            target="S0",
            loc=_loc(),
        )


def test_transition_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        Transition(kind="maybe", condition=None, target="S0", loc=_loc())


def test_full_program_construction() -> None:
    loc = _loc()
    out = Port(direction="out", type=PortType(1, 0), name="code", loc=loc)
    inp = Port(direction="in", type=PortType(0, 0), name="tick", loc=loc)
    s0 = State(
        name="S0",
        outputs=(OutputAssignment("code", Value(0, loc), loc),),
        transitions=(
            Transition("when", Condition("tick", loc), "S1", loc),
            Transition("else", None, "S0", loc),
        ),
        loc=loc,
    )
    s1 = State(
        name="S1",
        outputs=(OutputAssignment("code", Value(1, loc), loc),),
        transitions=(Transition("else", None, "S0", loc),),
        loc=loc,
    )
    m = Machine(
        name="light",
        inputs=(inp,),
        outputs=(out,),
        reset_state="S0",
        states=(s0, s1),
        loc=loc,
    )
    prog = Program(machines=(m,), source_file="m.fsm")

    assert prog.source_file == "m.fsm"
    assert len(prog.machines) == 1
    assert prog.machines[0].reset_state == "S0"
    assert prog.machines[0].states[0].transitions[-1].kind == "else"
    # Frozen + tuple collections => hashable.
    assert hash(prog) == hash(prog)
