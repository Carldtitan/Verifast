"""Unit tests for the Safety_Checker.

Covers the total-outputs check (Req 7): exact diagnostic form (7.2), one error
per unassigned output (7.3), the zero-states / zero-outputs case (7.4), and the
all-assigned case reporting nothing (7.6).
"""

from __future__ import annotations

from transpiler.ast import (
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
from transpiler.safety import (
    check,
    check_name_resolution,
    check_single_driver,
    check_total_outputs,
    check_total_transitions,
)


def _loc(line: int = 1) -> Loc:
    return Loc(file="m.fsm", line=line, column=1)


def _bit_port(name: str, direction: str = "out") -> Port:
    return Port(direction=direction, type=PortType(high=0, low=0), name=name, loc=_loc())


def _assign(name: str, bits: int = 0) -> OutputAssignment:
    return OutputAssignment(output_name=name, value=Value(bits=bits, loc=_loc()), loc=_loc())


def _else(target: str) -> Transition:
    return Transition(kind="else", condition=None, target=target, loc=_loc())


def _when(target: str) -> Transition:
    from transpiler.ast import Condition

    return Transition(
        kind="when",
        condition=Condition(text="c", loc=_loc()),
        target=target,
        loc=_loc(),
    )


def _state_with_transitions(
    name: str, transitions: tuple[Transition, ...], line: int = 1
) -> State:
    return State(name=name, outputs=(), transitions=transitions, loc=_loc(line))


def _state(name: str, outputs: tuple[OutputAssignment, ...], line: int = 1) -> State:
    return State(
        name=name,
        outputs=outputs,
        transitions=(_else(name),),
        loc=_loc(line),
    )


def _machine(outputs: tuple[Port, ...], states: tuple[State, ...]) -> Machine:
    return Machine(
        name="M",
        inputs=(),
        outputs=outputs,
        reset_state=states[0].name if states else "S0",
        states=states,
        loc=_loc(),
    )


def test_all_outputs_assigned_no_errors() -> None:
    out_x = _bit_port("x")
    out_y = _bit_port("y")
    s0 = _state("S0", (_assign("x"), _assign("y")))
    s1 = _state("S1", (_assign("x"), _assign("y")))
    m = _machine((out_x, out_y), (s0, s1))
    assert check_total_outputs(m) == []


def test_one_missing_output_one_error_exact_message() -> None:
    out_x = _bit_port("x")
    s0 = _state("S0", ())  # assigns nothing
    m = _machine((out_x,), (s0,))
    errors = check_total_outputs(m)
    assert len(errors) == 1
    assert errors[0].rule == "total_outputs"
    assert errors[0].message == "state S0 does not assign output 'x'"


def test_multiple_missing_in_one_state_one_error_per_output() -> None:
    out_x = _bit_port("x")
    out_y = _bit_port("y")
    out_z = _bit_port("z")
    s0 = _state("S0", (_assign("y"),))  # only y assigned; x and z missing
    m = _machine((out_x, out_y, out_z), (s0,))
    errors = check_total_outputs(m)
    messages = [e.message for e in errors]
    # Declared output order: x, y, z -> errors for x then z.
    assert messages == [
        "state S0 does not assign output 'x'",
        "state S0 does not assign output 'z'",
    ]


def test_missing_across_multiple_states_ordered_by_state() -> None:
    out_x = _bit_port("x")
    s0 = _state("S0", (), line=1)
    s1 = _state("S1", (_assign("x"),), line=2)
    s2 = _state("S2", (), line=3)
    m = _machine((out_x,), (s0, s1, s2))
    messages = [e.message for e in check_total_outputs(m)]
    assert messages == [
        "state S0 does not assign output 'x'",
        "state S2 does not assign output 'x'",
    ]


def test_zero_states_no_errors() -> None:
    out_x = _bit_port("x")
    m = _machine((out_x,), ())
    assert check_total_outputs(m) == []


def test_zero_outputs_no_errors() -> None:
    s0 = _state("S0", ())
    m = _machine((), (s0,))
    assert check_total_outputs(m) == []


# --- total-transitions check (Req 8) ------------------------------------


def test_state_ending_in_else_no_error() -> None:
    s0 = _state_with_transitions("S0", (_when("S1"), _else("S0")))
    m = _machine((), (s0,))
    assert check_total_transitions(m) == []


def test_state_with_no_else_one_error_naming_state() -> None:
    s0 = _state_with_transitions("S0", (_when("S1"),))
    m = _machine((), (s0,))
    errors = check_total_transitions(m)
    assert len(errors) == 1
    assert errors[0].rule == "total_transitions"
    assert errors[0].message == (
        "state S0 does not end with a final 'else -> STATE' transition"
    )


def test_state_with_else_not_last_one_error() -> None:
    s0 = _state_with_transitions("S0", (_else("S0"), _when("S1")))
    m = _machine((), (s0,))
    errors = check_total_transitions(m)
    assert len(errors) == 1
    assert errors[0].message == (
        "state S0 does not end with a final 'else -> STATE' transition"
    )


def test_empty_transitions_one_error() -> None:
    s0 = _state_with_transitions("S0", ())
    m = _machine((), (s0,))
    errors = check_total_transitions(m)
    assert len(errors) == 1
    assert errors[0].message == (
        "state S0 does not end with a final 'else -> STATE' transition"
    )


def test_multiple_offending_states_one_error_each_ordered() -> None:
    s0 = _state_with_transitions("S0", (), line=1)  # offending
    s1 = _state_with_transitions("S1", (_else("S1"),), line=2)  # ok
    s2 = _state_with_transitions("S2", (_when("S0"),), line=3)  # offending
    m = _machine((), (s0, s1, s2))
    messages = [e.message for e in check_total_transitions(m)]
    assert messages == [
        "state S0 does not end with a final 'else -> STATE' transition",
        "state S2 does not end with a final 'else -> STATE' transition",
    ]


# --- name-resolution check (Req 10) -------------------------------------


def _machine_reset(
    states: tuple[State, ...], reset_state: str
) -> Machine:
    """Build a machine with an explicit reset target (for name-resolution)."""
    return Machine(
        name="M",
        inputs=(),
        outputs=(),
        reset_state=reset_state,
        states=states,
        loc=_loc(),
    )


def test_all_targets_resolve_no_errors() -> None:
    s0 = _state_with_transitions("S0", (_when("S1"), _else("S0")))
    s1 = _state_with_transitions("S1", (_else("S0"),))
    m = _machine_reset((s0, s1), reset_state="S0")
    assert check_name_resolution(m) == []


def test_unresolved_when_target_one_error_naming_it() -> None:
    s0 = _state_with_transitions("S0", (_when("GHOST"), _else("S0")))
    m = _machine_reset((s0,), reset_state="S0")
    errors = check_name_resolution(m)
    assert len(errors) == 1
    assert errors[0].rule == "name_resolution"
    assert errors[0].message == (
        "transition in state S0 targets undeclared state 'GHOST'"
    )


def test_unresolved_else_target_one_error() -> None:
    s0 = _state_with_transitions("S0", (_when("S0"), _else("NOWHERE")))
    m = _machine_reset((s0,), reset_state="S0")
    errors = check_name_resolution(m)
    assert len(errors) == 1
    assert errors[0].rule == "name_resolution"
    assert errors[0].message == (
        "transition in state S0 targets undeclared state 'NOWHERE'"
    )


def test_unresolved_reset_target_one_error() -> None:
    s0 = _state_with_transitions("S0", (_else("S0"),))
    m = _machine_reset((s0,), reset_state="START")
    errors = check_name_resolution(m)
    assert len(errors) == 1
    assert errors[0].rule == "name_resolution"
    assert errors[0].message == "reset target 'START' is not a declared state"


def test_multiple_unresolved_one_error_each_transitions_then_reset() -> None:
    s0 = _state_with_transitions("S0", (_when("A"), _else("S0")), line=1)
    s1 = _state_with_transitions("S1", (_else("B"),), line=2)
    m = _machine_reset((s0, s1), reset_state="C")
    messages = [e.message for e in check_name_resolution(m)]
    # Transition targets in declared order first, then the reset target last.
    assert messages == [
        "transition in state S0 targets undeclared state 'A'",
        "transition in state S1 targets undeclared state 'B'",
        "reset target 'C' is not a declared state",
    ]


# --- single-driver check (Req 9) ----------------------------------------
#
# This check spans machines, so the tests construct Program models directly
# (the parser forbids multi-machine files, so source can't express them).


def _port_at(name: str, line: int, direction: str = "out") -> Port:
    return Port(
        direction=direction,
        type=PortType(high=0, low=0),
        name=name,
        loc=Loc(file="m.fsm", line=line, column=1),
    )


def _assign_at(name: str, line: int, bits: int = 0) -> OutputAssignment:
    loc = Loc(file="m.fsm", line=line, column=1)
    return OutputAssignment(output_name=name, value=Value(bits=bits, loc=loc), loc=loc)


def _named_machine(
    name: str,
    outputs: tuple[Port, ...],
    states: tuple[State, ...],
    line: int = 1,
) -> Machine:
    return Machine(
        name=name,
        inputs=(),
        outputs=outputs,
        reset_state=states[0].name if states else "S0",
        states=states,
        loc=Loc(file="m.fsm", line=line, column=1),
    )


def _program(*machines: Machine) -> Program:
    return Program(machines=tuple(machines), source_file="m.fsm")


def test_single_machine_outputs_assigned_in_own_states_no_errors() -> None:
    out_x = _bit_port("x")
    s0 = _state("S0", (_assign("x"),))
    s1 = _state("S1", (_assign("x"),))
    m = _named_machine("M", (out_x,), (s0, s1))
    assert check_single_driver(_program(m)) == []


def test_same_output_name_in_two_machines_one_violation() -> None:
    m1 = _named_machine(
        "M1", (_port_at("x", line=2),), (_state("A", (_assign("x"),)),)
    )
    m2 = _named_machine(
        "M2", (_port_at("x", line=20),), (_state("B", (_assign("x"),)),)
    )
    errors = check_single_driver(_program(m1, m2))
    assert len(errors) == 1
    assert errors[0].rule == "single_driver"
    # Located at the duplicate (second) declaration, and the message names the
    # output plus the location of every declaring machine (Req 9.3).
    assert errors[0].loc.line == 20
    assert "'x'" in errors[0].message
    assert "M1 (m.fsm:2)" in errors[0].message
    assert "M2 (m.fsm:20)" in errors[0].message


def test_same_output_name_in_three_machines_one_error_per_duplicate() -> None:
    m1 = _named_machine("M1", (_port_at("x", 2),), (_state("A", (_assign("x"),)),))
    m2 = _named_machine("M2", (_port_at("x", 12),), (_state("B", (_assign("x"),)),))
    m3 = _named_machine("M3", (_port_at("x", 22),), (_state("C", (_assign("x"),)),))
    errors = check_single_driver(_program(m1, m2, m3))
    # One error per declaring machine after the first.
    assert len(errors) == 2
    assert {e.loc.line for e in errors} == {12, 22}
    assert all(e.rule == "single_driver" for e in errors)


def test_output_assigned_in_state_of_other_machine_violation() -> None:
    # M1 declares output x. M2 declares its own output y but a state of M2
    # assigns x (declared by M1) -> cross-machine driver violation (Req 9.2).
    m1 = _named_machine("M1", (_port_at("x", 2),), (_state("A", (_assign("x"),)),))
    s_b = State(
        name="B",
        outputs=(_assign_at("y", 30), _assign_at("x", 31)),
        transitions=(_else("B"),),
        loc=Loc(file="m.fsm", line=29, column=1),
    )
    m2 = _named_machine("M2", (_port_at("y", 20),), (s_b,))
    errors = check_single_driver(_program(m1, m2))
    assert len(errors) == 1
    assert errors[0].rule == "single_driver"
    # Located at the offending assignment (Req 9.2).
    assert errors[0].loc.line == 31
    assert errors[0].message == (
        "output 'x' is assigned in state B of machine M2 but is declared by "
        "machine M1"
    )


def test_assignment_of_undeclared_name_is_out_of_scope() -> None:
    # 'ghost' is declared by no machine, so single-driver ignores it.
    s_a = State(
        name="A",
        outputs=(_assign("x"), _assign_at("ghost", 9)),
        transitions=(_else("A"),),
        loc=_loc(),
    )
    m = _named_machine("M", (_bit_port("x"),), (s_a,))
    assert check_single_driver(_program(m)) == []


def test_multiple_single_driver_violations_all_reported() -> None:
    # A duplicate declaration AND a cross-machine assignment in one program.
    m1 = _named_machine("M1", (_port_at("x", 2),), (_state("A", (_assign("x"),)),))
    # M2 also declares x (duplicate) and additionally assigns x's twin name in
    # a state -- plus assigns w which is declared only by M3.
    m2 = _named_machine("M2", (_port_at("x", 12),), (_state("B", (_assign("x"),)),))
    s_c = State(
        name="C",
        outputs=(_assign_at("w", 40),),
        transitions=(_else("C"),),
        loc=Loc(file="m.fsm", line=39, column=1),
    )
    m3 = _named_machine("M3", (_port_at("w", 22),), (s_c,))
    # Make M3 also assign x (declared by M1/M2) for a cross-machine violation.
    s_c2 = State(
        name="C",
        outputs=(_assign_at("w", 40), _assign_at("x", 41)),
        transitions=(_else("C"),),
        loc=Loc(file="m.fsm", line=39, column=1),
    )
    m3 = _named_machine("M3", (_port_at("w", 22),), (s_c2,))
    errors = check_single_driver(_program(m1, m2, m3))
    rules = {e.rule for e in errors}
    assert rules == {"single_driver"}
    # One duplicate-declaration error (M2's x) and one cross-machine assignment
    # error (M3 assigns x) -> every violation reported (Req 9.4).
    assert len(errors) == 2
    messages = "\n".join(e.message for e in errors)
    assert "declared by more than one machine" in messages
    assert "assigned in state C of machine M3" in messages


# --- check driver (Req 16.1, 16.5) --------------------------------------
#
# The driver runs all four checks to completion and returns the aggregated,
# ordered diagnostics. An empty list means the program is safe to generate.


def test_check_valid_single_machine_returns_empty() -> None:
    # x assigned in every state, every state ends with else, all targets and
    # the reset target resolve, and x is driven by exactly one machine.
    out_x = _bit_port("x")
    s0 = _state("S0", (_assign("x"),))
    s1 = _state("S1", (_assign("x"),))
    m = _machine((out_x,), (s0, s1))
    assert check(_program(m)) == []


def test_check_aggregates_violations_across_all_rules() -> None:
    # A single machine that violates three rules at once:
    #   * output x is never assigned in S0      -> total_outputs
    #   * S0 has no final else transition        -> total_transitions
    #   * S0's only transition targets GHOST     -> name_resolution
    out_x = _bit_port("x")
    s0 = State(
        name="S0",
        outputs=(),  # x unassigned
        transitions=(_when("GHOST"),),  # no else; GHOST undeclared
        loc=_loc(),
    )
    m = _machine((out_x,), (s0,))
    errors = check(_program(m))

    violated_rules = {e.rule for e in errors}
    assert violated_rules == {
        "total_outputs",
        "total_transitions",
        "name_resolution",
    }
    # Exactly one diagnostic per violated rule (no short-circuiting).
    assert len(errors) == 3
    # Deterministic order: total_outputs, total_transitions, name_resolution.
    assert [e.rule for e in errors] == [
        "total_outputs",
        "total_transitions",
        "name_resolution",
    ]


def test_check_includes_single_driver_violations_last() -> None:
    # Two machines both declaring x triggers a single-driver violation, which
    # the driver appends after the per-machine checks. Each machine is itself
    # internally valid so only single_driver fires.
    m1 = _named_machine("M1", (_port_at("x", 2),), (_state("A", (_assign("x"),)),))
    m2 = _named_machine("M2", (_port_at("x", 20),), (_state("B", (_assign("x"),)),))
    errors = check(_program(m1, m2))
    assert {e.rule for e in errors} == {"single_driver"}
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# Property-based test
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 9: Total-outputs diagnostics are exact
#
# Validates: Requirements 7.1, 7.2, 7.3, 7.6
#
# For any machine, ``check_total_outputs`` reports exactly one error of the
# form ``state S does not assign output 'x'`` for each (state, declared output)
# pair where the state does not assign that output, and reports zero errors
# when every declared output is assigned in every declared state.
#
# The test has two halves:
#   1. A machine drawn from ``valid_machine()`` assigns every output in every
#      state, so the check reports nothing (Req 7.6).
#   2. Starting from a valid machine, we remove a randomly chosen *set* of
#      (state, output) assignments, tracking exactly which (state, output)
#      pairs we dropped. The multiset of returned error messages must equal,
#      exactly, the set of expected messages -- one per removed pair, in the
#      exact message form (Req 7.1, 7.2, 7.3).

from dataclasses import replace as _replace  # noqa: E402

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as _st  # noqa: E402

from tests.strategies import identifiers, valid_machine  # noqa: E402


def _expected_message(state_name: str, output_name: str) -> str:
    """The exact total-outputs diagnostic for a missing (state, output) pair."""
    return f"state {state_name} does not assign output '{output_name}'"


@settings(max_examples=200, deadline=None)
@given(valid_machine())
def test_total_outputs_reports_nothing_when_all_assigned(m: Machine) -> None:
    # A valid machine assigns every declared output in every declared state, so
    # the totality check is silent (Req 7.6).
    assert check_total_outputs(m) == []


@_st.composite
def _machine_with_dropped_assignments(
    draw: _st.DrawFn,
) -> tuple[Machine, set[tuple[str, str]]]:
    """Draw a valid machine and remove a chosen set of (state, output) pairs.

    Returns ``(machine, removed_pairs)`` where ``removed_pairs`` is the set of
    ``(state_name, output_name)`` assignments that were dropped. Each removed
    pair should produce exactly one total-outputs error.
    """
    m = draw(valid_machine(min_outputs=1))

    output_names = [p.name for p in m.outputs]
    # Enumerate every (state index, output name) pair, then choose a subset to
    # drop. Drawing the subset as a list of booleans keeps the choice shrinkable
    # and lets the empty-subset case (drop nothing) occur naturally.
    all_pairs = [
        (si, oname)
        for si in range(len(m.states))
        for oname in output_names
    ]
    flags = draw(
        _st.lists(
            _st.booleans(),
            min_size=len(all_pairs),
            max_size=len(all_pairs),
        )
    )
    to_drop = {pair for pair, flag in zip(all_pairs, flags) if flag}

    removed: set[tuple[str, str]] = set()
    new_states = []
    for si, state in enumerate(m.states):
        drop_here = {oname for (s, oname) in to_drop if s == si}
        if drop_here:
            kept = tuple(
                a for a in state.outputs if a.output_name not in drop_here
            )
            state = _replace(state, outputs=kept)
            for oname in drop_here:
                removed.add((state.name, oname))
        new_states.append(state)

    return _replace(m, states=tuple(new_states)), removed


@settings(max_examples=200, deadline=None)
@given(_machine_with_dropped_assignments())
def test_total_outputs_diagnostics_match_removed_pairs_exactly(
    data: tuple[Machine, set[tuple[str, str]]],
) -> None:
    machine, removed = data

    errors = check_total_outputs(machine)

    # Every reported error carries the total_outputs rule (Req 7.1).
    assert all(e.rule == "total_outputs" for e in errors)

    # The multiset of messages corresponds EXACTLY to the removed pairs: one
    # error per missing (state, output) pair, in the exact message form
    # (Req 7.2, 7.3). When nothing was removed, there are zero errors (Req 7.6).
    actual_messages = sorted(e.message for e in errors)
    expected_messages = sorted(
        _expected_message(state_name, output_name)
        for (state_name, output_name) in removed
    )
    assert actual_messages == expected_messages
    # No duplicate diagnostics: exactly one error per removed pair.
    assert len(errors) == len(removed)


# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 10: Every state must end with a final else transition
#
# Validates: Requirements 8.1, 8.2, 8.3
#
# For any machine, ``check_total_transitions`` reports exactly one error of the
# form ``state S does not end with a final 'else -> STATE' transition`` for
# each declared state whose transition list does not end with a final ``else``
# clause, naming each offending state, and reports zero errors when every state
# ends with a final ``else`` (Req 8.1).
#
# The test has two halves:
#   1. A machine drawn from ``valid_machine()`` has every state ending in a
#      final ``else``, so the totality check reports nothing (Req 8.1).
#   2. Starting from a valid machine, we strip the trailing ``else`` from a
#      randomly chosen *set* of states, tracking exactly which. A state with
#      its ``else`` stripped now ends in a ``when`` (or is empty) -- both
#      offending. The set of returned error messages must equal, exactly, the
#      set of expected messages: one per offending state, in the exact message
#      form (Req 8.2, 8.3).


def _expected_transition_message(state_name: str) -> str:
    """The exact total-transitions diagnostic for an offending state."""
    return (
        f"state {state_name} does not end with a final 'else -> STATE' "
        f"transition"
    )


@settings(max_examples=200, deadline=None)
@given(valid_machine())
def test_total_transitions_reports_nothing_when_all_end_in_else(
    m: Machine,
) -> None:
    # A valid machine has every state ending in a final `else`, so the
    # totality check is silent (Req 8.1).
    assert check_total_transitions(m) == []


@_st.composite
def _machine_with_stripped_elses(
    draw: _st.DrawFn,
) -> tuple[Machine, set[str]]:
    """Draw a valid machine and strip the trailing ``else`` from a set of states.

    Returns ``(machine, offending_state_names)`` where ``offending_state_names``
    is the set of state names whose final ``else`` was removed. Each such state
    should produce exactly one total-transitions error.
    """
    m = draw(valid_machine())

    # Choose, per state, whether to strip its trailing `else`. Drawing booleans
    # keeps the choice shrinkable and lets the strip-nothing case occur.
    flags = draw(
        _st.lists(
            _st.booleans(),
            min_size=len(m.states),
            max_size=len(m.states),
        )
    )

    offending: set[str] = set()
    new_states = []
    for state, strip in zip(m.states, flags):
        if strip:
            # valid_machine guarantees the last transition is the final `else`.
            state = _replace(state, transitions=state.transitions[:-1])
            offending.add(state.name)
        new_states.append(state)

    return _replace(m, states=tuple(new_states)), offending


@settings(max_examples=200, deadline=None)
@given(_machine_with_stripped_elses())
def test_total_transitions_diagnostics_match_offending_states_exactly(
    data: tuple[Machine, set[str]],
) -> None:
    machine, offending = data

    errors = check_total_transitions(machine)

    # Every reported error carries the total_transitions rule.
    assert all(e.rule == "total_transitions" for e in errors)

    # The set of messages corresponds EXACTLY to the offending states: one
    # error per state whose final `else` was stripped, in the exact message
    # form (Req 8.2, 8.3). When nothing was stripped, there are zero errors
    # (Req 8.1).
    actual_messages = sorted(e.message for e in errors)
    expected_messages = sorted(
        _expected_transition_message(name) for name in offending
    )
    assert actual_messages == expected_messages
    # No duplicate diagnostics: exactly one error per offending state.
    assert len(errors) == len(offending)


# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 11: Every transition and reset target resolves to a declared state
#
# Validates: Requirements 8.4, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
#
# For any machine, ``check_name_resolution`` reports exactly one name-resolution
# error for each transition target -- including ``else -> STATE`` targets
# (Req 8.4, 10.1, 10.3) -- and for the ``reset = STATE`` target (Req 10.2, 10.4)
# that does not name a declared state, naming each unresolved target (Req 10.5),
# and reports zero errors when every transition target and the reset target
# resolve (Req 10.6).
#
# The test has two halves:
#   1. A machine drawn from ``valid_machine()`` has every transition target and
#      the reset target resolving to a declared state, so the check is silent
#      (Req 10.6).
#   2. Starting from a valid machine, we repoint a randomly chosen *set* of
#      transition targets (both ``when`` and ``else``) and/or the reset target
#      to fresh undeclared names, tracking the expected unresolved references
#      together with their state context. The multiset of returned error
#      messages must equal, exactly, the expected messages -- one per
#      unresolved reference, in the exact documented message forms.


def _expected_transition_resolution_message(state_name: str, target: str) -> str:
    """The exact name-resolution diagnostic for an unresolved transition target."""
    return f"transition in state {state_name} targets undeclared state '{target}'"


def _expected_reset_resolution_message(target: str) -> str:
    """The exact name-resolution diagnostic for an unresolved reset target."""
    return f"reset target '{target}' is not a declared state"


@settings(max_examples=200, deadline=None)
@given(valid_machine())
def test_name_resolution_reports_nothing_when_all_targets_resolve(
    m: Machine,
) -> None:
    # A valid machine has every transition target and the reset target
    # resolving to a declared state, so the check is silent (Req 10.6).
    assert check_name_resolution(m) == []


@_st.composite
def _machine_with_repointed_targets(
    draw: _st.DrawFn,
) -> tuple[Machine, list[str]]:
    """Draw a valid machine and repoint a set of targets to undeclared names.

    Repoints a chosen subset of transition targets (both ``when`` and ``else``
    clauses) and, optionally, the ``reset`` target to fresh names that are not
    among the declared state names. Returns ``(machine, expected_messages)``
    where ``expected_messages`` is the list (multiset) of name-resolution
    diagnostics the check should emit -- one per repointed reference, in the
    exact documented message form.
    """
    m = draw(valid_machine())
    declared = {s.name for s in m.states}

    def fresh_undeclared() -> str:
        return draw(identifiers().filter(lambda n: n not in declared))

    expected: list[str] = []

    new_states: list[State] = []
    for state in m.states:
        new_transitions: list[Transition] = []
        for transition in state.transitions:
            repoint = draw(_st.booleans())
            if repoint:
                target = fresh_undeclared()
                new_transitions.append(_replace(transition, target=target))
                expected.append(
                    _expected_transition_resolution_message(state.name, target)
                )
            else:
                new_transitions.append(transition)
        new_states.append(_replace(state, transitions=tuple(new_transitions)))

    machine = _replace(m, states=tuple(new_states))

    # Optionally repoint the reset target to a fresh undeclared name.
    if draw(_st.booleans()):
        reset_target = fresh_undeclared()
        machine = _replace(machine, reset_state=reset_target)
        expected.append(_expected_reset_resolution_message(reset_target))

    return machine, expected


@settings(max_examples=200, deadline=None)
@given(_machine_with_repointed_targets())
def test_name_resolution_diagnostics_match_repointed_targets_exactly(
    data: tuple[Machine, list[str]],
) -> None:
    machine, expected_messages = data

    errors = check_name_resolution(machine)

    # Every reported error carries the name_resolution rule (Req 10.1, 10.2).
    assert all(e.rule == "name_resolution" for e in errors)

    # The multiset of messages corresponds EXACTLY to the repointed references:
    # one error per unresolved transition target (when and else, Req 8.4, 10.1,
    # 10.3) and the reset target (Req 10.2, 10.4), naming each unresolved target
    # (Req 10.5), in the exact message forms. When nothing was repointed, there
    # are zero errors (Req 10.6).
    actual_messages = sorted(e.message for e in errors)
    assert actual_messages == sorted(expected_messages)
    # No duplicate diagnostics: exactly one error per unresolved reference.
    assert len(errors) == len(expected_messages)


# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 12: Each output is driven by exactly one machine
#
# Validates: Requirements 9.1, 9.2, 9.3, 9.4
#
# For any program, ``check_single_driver`` reports a single-driver error for
# each output assigned within a state of a machine other than the one declaring
# it (Req 9.1, 9.2) and for each output declared by more than one machine
# (Req 9.3), reporting EVERY such violation rather than stopping at the first
# (Req 9.4), naming the offending output.
#
# The test has three halves:
#   1. A single-machine program drawn from ``valid_program()`` declares unique
#      outputs each assigned only within its own states, so the check is silent
#      (each output is driven by exactly one machine).
#   2. The ``duplicate_output_across_machines()`` perturbation builds two
#      machines that share an output name; the check must flag at least one
#      single-driver violation naming the shared output (Req 9.3).
#   3. Programs constructed directly with a controlled number of cross-machine
#      violations (duplicate declarations across 2-3 machines and/or
#      cross-machine assignments) must have EVERY violation reported -- the
#      error count must equal the exact expected count (Req 9.1-9.4).

from collections import Counter as _Counter  # noqa: E402

from hypothesis import assume  # noqa: E402

from tests.strategies import (  # noqa: E402
    duplicate_output_across_machines,
    valid_program,
)


@settings(max_examples=200, deadline=None)
@given(valid_program())
def test_single_driver_silent_for_valid_single_machine_program(p: Program) -> None:
    # A valid single-machine program declares unique outputs, each assigned
    # only within that machine's own states, so every output is driven by
    # exactly one machine and the check is silent (Req 9.1).
    assert check_single_driver(p) == []


@settings(max_examples=150, deadline=None)
@given(duplicate_output_across_machines())
def test_single_driver_flags_output_shared_across_machines(
    data: tuple[Program, str],
) -> None:
    program, kind = data
    assert kind == "duplicate_output_across_machines"

    # Determine which output names are actually declared by more than one
    # machine in the constructed program.
    decl_counts: _Counter[str] = _Counter()
    for machine in program.machines:
        for name in {port.name for port in machine.outputs}:
            decl_counts[name] += 1
    shared_names = {name for name, count in decl_counts.items() if count > 1}

    # The perturbation intends a shared output; skip the rare degenerate draw
    # where no name ends up shared.
    assume(shared_names)

    errors = check_single_driver(program)

    # At least one single-driver violation is reported (Req 9.3) and every
    # reported error carries the single_driver rule.
    assert errors, "expected at least one single_driver error"
    assert all(e.rule == "single_driver" for e in errors)

    # The shared output name appears in some diagnostic message.
    messages = "\n".join(e.message for e in errors)
    for name in shared_names:
        assert f"'{name}'" in messages


@_st.composite
def _multi_machine_program_with_violations(
    draw: _st.DrawFn,
) -> tuple[Program, int]:
    """Build a multi-machine program with a known number of violations.

    Each machine declares exactly one output drawn (with repeats) from a small
    shared pool and assigns that output in its single state. A machine may
    additionally assign outputs declared by *other* machines, producing
    cross-machine assignment violations (Req 9.1, 9.2). Output names declared
    by more than one machine produce duplicate-declaration violations (Req 9.3).

    Returns ``(program, expected_violation_count)`` where the expected count is
    computed exactly from the construction:

    * one duplicate-declaration error per declaring machine after the first,
      for each name declared by more than one machine; plus
    * one cross-machine assignment error per assignment of an output the
      assigning machine does not itself declare.

    The check must report exactly this many violations -- every violation, not
    just the first (Req 9.4).
    """
    pool_size = draw(_st.integers(min_value=1, max_value=3))
    output_pool = draw(
        _st.lists(
            identifiers(), min_size=pool_size, max_size=pool_size, unique=True
        )
    )
    n_machines = draw(_st.integers(min_value=2, max_value=4))
    machine_names = draw(
        _st.lists(
            identifiers().filter(lambda n: n not in output_pool),
            min_size=n_machines,
            max_size=n_machines,
            unique=True,
        )
    )

    # Each machine declares exactly one output name (repeats across machines
    # create duplicate declarations).
    declared = [draw(_st.sampled_from(output_pool)) for _ in range(n_machines)]
    declared_set = set(declared)

    machines: list[Machine] = []
    cross_assignment_count = 0
    line = 1
    for i, mname in enumerate(machine_names):
        own = declared[i]
        # Candidate cross-machine assignments: outputs declared by some machine
        # other than this one's own declaration.
        others = sorted(declared_set - {own})
        if others:
            flags = draw(
                _st.lists(
                    _st.booleans(), min_size=len(others), max_size=len(others)
                )
            )
            cross = [o for o, flag in zip(others, flags) if flag]
        else:
            cross = []
        cross_assignment_count += len(cross)

        assignments = (_assign_at(own, line),) + tuple(
            _assign_at(o, line + 1 + k) for k, o in enumerate(cross)
        )
        state = State(
            name=f"S{i}",
            outputs=assignments,
            transitions=(_else(f"S{i}"),),
            loc=Loc(file="m.fsm", line=line, column=1),
        )
        machines.append(
            _named_machine(mname, (_port_at(own, line),), (state,), line=line)
        )
        line += 10

    program = Program(machines=tuple(machines), source_file="m.fsm")

    counts = _Counter(declared)
    duplicate_errors = sum(count - 1 for count in counts.values())
    expected_total = duplicate_errors + cross_assignment_count
    return program, expected_total


@settings(max_examples=200, deadline=None)
@given(_multi_machine_program_with_violations())
def test_single_driver_reports_every_violation(
    data: tuple[Program, int],
) -> None:
    program, expected_total = data

    errors = check_single_driver(program)

    # Every reported error carries the single_driver rule (Req 9.1-9.3).
    assert all(e.rule == "single_driver" for e in errors)

    # EVERY violation is reported, not just the first: the number of errors
    # equals the exact number of constructed violations (Req 9.4).
    assert len(errors) == expected_total


# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 13: All safety checks run to completion and every violation is reported
#
# Validates: Requirements 16.1
#
# For any program containing violations that span more than one safety rule,
# the ``check`` driver runs ALL four checks to completion and reports a
# diagnostic for EVERY violated rule rather than stopping at the first one.
#
# The test has two halves:
#   1. A valid single-machine program drawn from ``valid_program()`` violates
#      no rule, so ``check`` reports nothing (no false positives).
#   2. Starting from a valid machine, we inject a Hypothesis-chosen, non-empty
#      subset of three independent per-machine rule violations and track which
#      rules we injected:
#        * total_outputs     -- drop one output assignment from a state;
#        * total_transitions -- strip the trailing ``else`` from a state;
#        * name_resolution   -- repoint the ``reset`` target to an undeclared
#                               name.
#      These three mutations are mutually independent (they touch a state's
#      outputs, a state's transitions, and the machine's reset target,
#      respectively), so each injected rule is guaranteed to be detectable.
#      The rule-set of ``check``'s diagnostics must be a SUPERSET of the
#      injected rules, and every injected rule must contribute at least one
#      error -- proving no check short-circuits another (Req 16.1).


@settings(max_examples=200, deadline=None)
@given(valid_program())
def test_check_no_false_positives_for_valid_program(p: Program) -> None:
    # A fully valid program violates no safety rule, so the aggregating driver
    # reports nothing (Req 16.5) -- the baseline that makes the multi-rule
    # completeness assertion meaningful.
    assert check(p) == []


@_st.composite
def _machine_with_multi_rule_violations(
    draw: _st.DrawFn,
) -> tuple[Program, set[str]]:
    """Draw a valid machine and inject a non-empty subset of rule violations.

    Injects an independently-detectable violation for each rule in a chosen
    non-empty subset of ``{total_outputs, total_transitions, name_resolution}``
    and returns ``(program, injected_rules)`` where ``injected_rules`` is the
    set of rules deliberately broken. The three mutations are independent:

    * ``total_outputs``     drops one output assignment from a chosen state;
    * ``total_transitions`` strips the trailing ``else`` from a chosen state;
    * ``name_resolution``   repoints the ``reset`` target to an undeclared name.

    Because they touch disjoint parts of the model (a state's outputs, a state's
    transitions, the machine's reset target) they never interfere -- even when
    the two state-level mutations land on the same state -- so each injected
    rule is guaranteed to produce at least one diagnostic.
    """
    m = draw(valid_machine(min_outputs=1))

    rules = ["total_outputs", "total_transitions", "name_resolution"]
    selected = draw(
        _st.lists(_st.sampled_from(rules), min_size=1, max_size=3, unique=True)
    )

    states = list(m.states)
    injected: set[str] = set()

    if "total_outputs" in selected:
        # Drop one assignment from a chosen state. valid_machine(min_outputs=1)
        # assigns every output exactly once in every state, so removing one
        # assignment leaves that output unassigned in that state.
        si = draw(_st.integers(min_value=0, max_value=len(states) - 1))
        state = states[si]
        oi = draw(_st.integers(min_value=0, max_value=len(state.outputs) - 1))
        new_outputs = state.outputs[:oi] + state.outputs[oi + 1 :]
        states[si] = _replace(state, outputs=new_outputs)
        injected.add("total_outputs")

    if "total_transitions" in selected:
        # Strip the trailing `else` from a chosen state. valid_machine
        # guarantees the last transition is the final `else`, so the remaining
        # list either ends in a `when` or is empty -- both offending.
        si = draw(_st.integers(min_value=0, max_value=len(states) - 1))
        state = states[si]
        states[si] = _replace(state, transitions=state.transitions[:-1])
        injected.add("total_transitions")

    machine = _replace(m, states=tuple(states))

    if "name_resolution" in selected:
        # Repoint the reset target to a fresh undeclared name. This is fully
        # independent of any transition mutation above.
        declared = {s.name for s in machine.states}
        undeclared = draw(identifiers().filter(lambda n: n not in declared))
        machine = _replace(machine, reset_state=undeclared)
        injected.add("name_resolution")

    program = Program(machines=(machine,), source_file="<generated>.fsm")
    return program, injected


@settings(max_examples=200, deadline=None)
@given(_machine_with_multi_rule_violations())
def test_check_runs_all_checks_and_reports_every_violated_rule(
    data: tuple[Program, set[str]],
) -> None:
    program, injected = data

    errors = check(program)
    reported_rules = {e.rule for e in errors}

    # Every injected rule is reported: the driver runs all checks to completion
    # rather than stopping at the first violated rule (Req 16.1).
    assert injected <= reported_rules, (
        f"injected rules {sorted(injected)} not all reported; "
        f"got {sorted(reported_rules)}"
    )

    # Each injected rule contributes at least one diagnostic -- no check
    # short-circuits another.
    for rule in injected:
        assert any(e.rule == rule for e in errors), (
            f"no diagnostic reported for injected rule {rule!r}"
        )
