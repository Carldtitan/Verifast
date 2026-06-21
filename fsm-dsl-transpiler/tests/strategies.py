"""Shared Hypothesis strategies and a source renderer for FSM_DSL models.

This module is the single source of generated test data for the property-based
tests (Req 17.1). It provides:

* :func:`valid_machine` / :func:`valid_program` -- Hypothesis strategies that
  produce :class:`~transpiler.ast.Machine` / :class:`~transpiler.ast.Program`
  models that satisfy **all four** compile-time safety rules:

    1. *total outputs*      -- every declared output is assigned in every state;
    2. *total transitions*  -- every state's transitions end with a final
       ``else -> STATE`` clause;
    3. *name resolution*    -- every transition target and the ``reset`` target
       resolves to a declared state;
    4. *single driver*      -- output names are unique within a machine.

* :func:`render_machine` / :func:`render_program` -- deterministic renderers
  that turn a model back into FSM_DSL v0.1 source text, so other tests can feed
  generated models through the real pipeline (``parse`` -> ``build_ast`` ->
  ``check`` -> ``generate``). The rendered text always matches the grammar in
  ``transpiler/grammar.lark``.

* Perturbation strategies (:data:`PERTURBATIONS`) that take a valid model and
  break exactly one safety property, each returning a tuple
  ``(program, expected_violation_kind)`` so safety / CLI property tests can
  assert the right rule fires:

    ``drop_output`` | ``strip_else`` | ``repoint_target`` |
    ``inject_clk_rst`` | ``duplicate_state`` |
    ``duplicate_output_across_machines``

All generated identifiers are valid FSM_DSL names that avoid the seven reserved
keywords (``machine in out reset state when else``) and the implicit/reserved
port names (``clk`` / ``rst``). Output ``Value.bits`` always fit the declared
output width.
"""

from __future__ import annotations

from dataclasses import replace

from hypothesis import strategies as st

from transpiler.ast import (
    And,
    BitSelect,
    Compare,
    Condition,
    Ident,
    IntLiteral,
    Loc,
    Machine,
    Not,
    Or,
    OutputAssignment,
    Port,
    PortType,
    Program,
    State,
    Transition,
    Value,
    expr_to_text,
)

__all__ = [
    # building blocks
    "RESERVED_NAMES",
    "identifiers",
    "port_types",
    # valid models
    "valid_machine",
    "valid_program",
    # renderers
    "render_machine",
    "render_program",
    "render_port_type",
    # perturbations
    "PERTURBATIONS",
    "VIOLATION_KINDS",
    "drop_output",
    "strip_else",
    "repoint_target",
    "inject_clk_rst",
    "duplicate_state",
    "duplicate_output_across_machines",
    "invalid_program",
    # invariant helpers (used by the self-test and reusable by other tests)
    "assert_valid_machine_invariants",
    "assert_valid_program_invariants",
]

# The seven reserved keywords plus the two implicit/reserved port names. No
# generated identifier may collide with any of these.
_KEYWORDS = frozenset({"machine", "in", "out", "reset", "state", "when", "else"})
_RESERVED_PORTS = frozenset({"clk", "rst"})
RESERVED_NAMES = _KEYWORDS | _RESERVED_PORTS

# Every generated node carries a fixed, valid location. The exact line/column
# is irrelevant for these tests; only its presence matters.
_LOC = Loc(file="<generated>.fsm", line=1, column=1)

# Comparison operators admitted by the grammar's COMP_OP terminal.
_COMP_OPS = ("==", "!=", "<", "<=", ">", ">=")


# ---------------------------------------------------------------------------
# Building-block strategies
# ---------------------------------------------------------------------------
def identifiers() -> st.SearchStrategy[str]:
    """A strategy of valid FSM_DSL identifiers that avoid reserved words.

    Matches the grammar's ``NAME`` terminal (``[a-zA-Z_][a-zA-Z0-9_]*``) but is
    biased toward short lowercase names and never yields a reserved keyword or
    the implicit ``clk`` / ``rst`` port names.
    """
    return st.from_regex(r"[a-z][a-z0-9_]{0,6}", fullmatch=True).filter(
        lambda name: name not in RESERVED_NAMES
    )


def port_types(*, max_width: int = 8) -> st.SearchStrategy[PortType]:
    """A strategy of :class:`PortType` values with width in ``1..max_width``.

    Produces both scalar (``bit``, ``high == low == 0``) and vector
    (``bit[high:low]``) types with ``high >= low >= 0`` (Req 2.2).
    """

    @st.composite
    def _build(draw: st.DrawFn) -> PortType:
        width = draw(st.integers(min_value=1, max_value=max_width))
        low = draw(st.integers(min_value=0, max_value=3))
        return PortType(high=low + width - 1, low=low)

    return _build()


@st.composite
def _unique_identifiers(draw: st.DrawFn, count: int) -> list[str]:
    """Draw ``count`` globally-unique identifiers."""
    return draw(
        st.lists(identifiers(), min_size=count, max_size=count, unique=True)
    )


@st.composite
def _atom_expr(draw: st.DrawFn, inputs: tuple[Port, ...]):
    """Build a leaf guard expression over one declared input port.

    Produces a typed :class:`~transpiler.ast.Expr` leaf: a bare identifier, a
    ``name OP literal`` comparison (literal sized to fit the port width so the
    program stays valid), or a single-bit select ``name[i]`` for vector inputs.
    """
    port = draw(st.sampled_from(inputs))
    width = port.type.width
    form = draw(st.sampled_from(("bare", "compare", "bit_select")))
    if form == "bit_select" and width > 1:
        index = draw(st.integers(min_value=port.type.low, max_value=port.type.high))
        return BitSelect(port.name, index, _LOC)
    if form == "compare":
        op = draw(st.sampled_from(_COMP_OPS))
        # Literal fits the port width, so the AST builder never rejects it.
        literal = draw(st.integers(min_value=0, max_value=(1 << width) - 1))
        return Compare(op, Ident(port.name, _LOC), IntLiteral(literal, _LOC), _LOC)
    return Ident(port.name, _LOC)


@st.composite
def _condition_expr(draw: st.DrawFn, inputs: tuple[Port, ...], depth: int = 2):
    """Build a guard expression tree over the machine's declared inputs.

    Beyond the leaf forms (bare identifier, comparison, bit-select) this also
    composes guards with ``!`` / ``&&`` / ``||`` over multi-bit and 1-bit inputs,
    so the lint gate exercises every boolean-context rendering path (reduction
    of multi-bit operands, literal width-matching). Recursion is bounded by
    ``depth`` and biased toward leaves so generated machines stay small.
    """
    if depth <= 0:
        return draw(_atom_expr(inputs))
    form = draw(st.sampled_from(("atom", "atom", "not", "and", "or")))
    if form == "atom":
        return draw(_atom_expr(inputs))
    if form == "not":
        return Not(draw(_condition_expr(inputs, depth - 1)), _LOC)
    if form == "and":
        return And(
            draw(_condition_expr(inputs, depth - 1)),
            draw(_condition_expr(inputs, depth - 1)),
            _LOC,
        )
    return Or(
        draw(_condition_expr(inputs, depth - 1)),
        draw(_condition_expr(inputs, depth - 1)),
        _LOC,
    )


# ---------------------------------------------------------------------------
# Valid model strategies
# ---------------------------------------------------------------------------
@st.composite
def valid_machine(
    draw: st.DrawFn,
    *,
    min_states: int = 1,
    max_states: int = 4,
    max_inputs: int = 3,
    min_outputs: int = 1,
    max_outputs: int = 3,
    max_whens: int = 3,
) -> Machine:
    """Strategy producing a :class:`Machine` satisfying all four safety rules.

    The machine has a varied number of states, input/output ports of varied
    widths, an output assignment for *every* output in *every* state, ordered
    ``when`` transitions ending in a mandatory ``else``, and every transition
    plus the ``reset`` target resolving to a declared state.
    """
    n_states = draw(st.integers(min_value=min_states, max_value=max_states))
    n_inputs = draw(st.integers(min_value=0, max_value=max_inputs))
    n_outputs = draw(st.integers(min_value=min_outputs, max_value=max_outputs))

    # Draw one disjoint pool of identifiers so the machine name, state names,
    # input names, and output names never collide with each other.
    names = draw(_unique_identifiers(1 + n_states + n_inputs + n_outputs))
    machine_name = names[0]
    state_names = names[1 : 1 + n_states]
    input_names = names[1 + n_states : 1 + n_states + n_inputs]
    output_names = names[1 + n_states + n_inputs :]

    inputs = tuple(
        Port("in", draw(port_types()), name, _LOC) for name in input_names
    )
    outputs = tuple(
        Port("out", draw(port_types()), name, _LOC) for name in output_names
    )

    reset_state = draw(st.sampled_from(state_names))

    states: list[State] = []
    for sname in state_names:
        # Total outputs: assign every declared output, with a value that fits
        # the output's width.
        assignments = tuple(
            OutputAssignment(
                port.name,
                Value(
                    draw(st.integers(min_value=0, max_value=(1 << port.type.width) - 1)),
                    _LOC,
                ),
                _LOC,
            )
            for port in outputs
        )

        # Ordered `when` clauses (only when there is an input to guard on),
        # then the mandatory final `else`.
        transitions: list[Transition] = []
        n_whens = draw(st.integers(min_value=0, max_value=max_whens)) if inputs else 0
        for _ in range(n_whens):
            expr = draw(_condition_expr(inputs))
            cond = Condition(text=expr_to_text(expr), loc=_LOC, expr=expr)
            target = draw(st.sampled_from(state_names))
            transitions.append(Transition("when", cond, target, _LOC))
        else_target = draw(st.sampled_from(state_names))
        transitions.append(Transition("else", None, else_target, _LOC))

        states.append(State(sname, assignments, tuple(transitions), _LOC))

    return Machine(
        name=machine_name,
        inputs=inputs,
        outputs=outputs,
        reset_state=reset_state,
        states=tuple(states),
        loc=_LOC,
    )


@st.composite
def valid_program(draw: st.DrawFn, **machine_kwargs: object) -> Program:
    """Strategy producing a valid single-machine :class:`Program`.

    A well-formed FSM_DSL file contains exactly one machine (Req 1.2/1.3), so
    the valid program wraps exactly one :func:`valid_machine`.
    """
    machine = draw(valid_machine(**machine_kwargs))  # type: ignore[arg-type]
    return Program(machines=(machine,), source_file="<generated>.fsm")


# ---------------------------------------------------------------------------
# Source renderer
# ---------------------------------------------------------------------------
def render_port_type(pt: PortType) -> str:
    """Render a :class:`PortType` as FSM_DSL source (``bit`` or ``bit[H:L]``)."""
    if pt.high == 0 and pt.low == 0:
        return "bit"
    return f"bit[{pt.high}:{pt.low}]"


def _render_transition(t: Transition) -> str:
    if t.kind == "else":
        return f"        else -> {t.target}"
    assert t.condition is not None  # guaranteed by the AST invariant
    return f"        when {t.condition.text} -> {t.target}"


def _render_state(s: State) -> str:
    lines = [f"    state {s.name} {{"]
    lines.extend(f"        {a.output_name} = {a.value.bits}" for a in s.outputs)
    lines.extend(_render_transition(t) for t in s.transitions)
    lines.append("    }")
    return "\n".join(lines)


def render_machine(m: Machine) -> str:
    """Render a :class:`Machine` to FSM_DSL v0.1 source text.

    The output parses against ``transpiler/grammar.lark`` and round-trips the
    model's structure (declarations, ordered transitions, output assignments).
    """
    lines = [f"machine {m.name} {{"]
    for port in m.inputs:
        lines.append(f"    in {render_port_type(port.type)} {port.name}")
    for port in m.outputs:
        lines.append(f"    out {render_port_type(port.type)} {port.name}")
    lines.append(f"    reset = {m.reset_state}")
    for state in m.states:
        lines.append("")
        lines.append(_render_state(state))
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_program(p: Program) -> str:
    """Render a whole :class:`Program` (one or more machines) to source text."""
    return "\n".join(render_machine(m) for m in p.machines)


# ---------------------------------------------------------------------------
# Perturbation strategies: take a valid model, break exactly one property.
# Each returns ``(program, expected_violation_kind)``.
# ---------------------------------------------------------------------------
def _as_program(m: Machine) -> Program:
    return Program(machines=(m,), source_file="<generated>.fsm")


def _replace_state(m: Machine, index: int, new_state: State) -> Machine:
    states = m.states[:index] + (new_state,) + m.states[index + 1 :]
    return replace(m, states=states)


@st.composite
def drop_output(draw: st.DrawFn) -> tuple[Program, str]:
    """Remove one output assignment from one state (breaks *total outputs*)."""
    m = draw(valid_machine(min_outputs=1))
    si = draw(st.integers(min_value=0, max_value=len(m.states) - 1))
    state = m.states[si]
    oi = draw(st.integers(min_value=0, max_value=len(state.outputs) - 1))
    new_outputs = state.outputs[:oi] + state.outputs[oi + 1 :]
    m2 = _replace_state(m, si, replace(state, outputs=new_outputs))
    return _as_program(m2), "drop_output"


@st.composite
def strip_else(draw: st.DrawFn) -> tuple[Program, str]:
    """Strip the trailing ``else`` from one state (breaks *total transitions*)."""
    m = draw(valid_machine())
    si = draw(st.integers(min_value=0, max_value=len(m.states) - 1))
    state = m.states[si]
    # The valid strategy guarantees the last transition is the `else`.
    new_transitions = state.transitions[:-1]
    m2 = _replace_state(m, si, replace(state, transitions=new_transitions))
    return _as_program(m2), "strip_else"


@st.composite
def repoint_target(draw: st.DrawFn) -> tuple[Program, str]:
    """Repoint one transition target to an undeclared state (breaks *resolution*)."""
    m = draw(valid_machine())
    declared = {s.name for s in m.states}
    undeclared = draw(identifiers().filter(lambda n: n not in declared))
    si = draw(st.integers(min_value=0, max_value=len(m.states) - 1))
    state = m.states[si]
    ti = draw(st.integers(min_value=0, max_value=len(state.transitions) - 1))
    t = state.transitions[ti]
    new_t = replace(t, target=undeclared)
    new_transitions = (
        state.transitions[:ti] + (new_t,) + state.transitions[ti + 1 :]
    )
    m2 = _replace_state(m, si, replace(state, transitions=new_transitions))
    return _as_program(m2), "repoint_target"


@st.composite
def inject_clk_rst(draw: st.DrawFn) -> tuple[Program, str]:
    """Declare an explicit ``clk``/``rst`` port (collides with implicit ports)."""
    m = draw(valid_machine())
    reserved = draw(st.sampled_from(sorted(_RESERVED_PORTS)))
    injected = Port("in", PortType(high=0, low=0), reserved, _LOC)
    m2 = replace(m, inputs=m.inputs + (injected,))
    return _as_program(m2), "inject_clk_rst"


@st.composite
def duplicate_state(draw: st.DrawFn) -> tuple[Program, str]:
    """Append a duplicate state declaration (two states share a name)."""
    m = draw(valid_machine())
    si = draw(st.integers(min_value=0, max_value=len(m.states) - 1))
    m2 = replace(m, states=m.states + (m.states[si],))
    return _as_program(m2), "duplicate_state"


@st.composite
def duplicate_output_across_machines(draw: st.DrawFn) -> tuple[Program, str]:
    """Build two machines that declare the same output name."""
    m1 = draw(valid_machine(min_outputs=1))
    m2 = draw(valid_machine(min_outputs=1))

    shared = m1.outputs[0].name
    old = m2.outputs[0].name
    # The shared name must not already appear among m2's other outputs, else we
    # would also create an intra-machine duplicate and muddy the violation.
    st_assume = shared not in {p.name for p in m2.outputs[1:]}
    if not st_assume:
        # Fall back to a fresh, unique program rather than discarding the draw.
        shared = old

    # Ensure the two machines have distinct names.
    m2_name = m2.name if m2.name != m1.name else f"{m2.name}x"

    # Rename m2's first output port and every assignment that referenced it.
    new_ports = (replace(m2.outputs[0], name=shared),) + m2.outputs[1:]
    new_states = tuple(
        replace(
            s,
            outputs=tuple(
                replace(a, output_name=shared) if a.output_name == old else a
                for a in s.outputs
            ),
        )
        for s in m2.states
    )
    m2b = replace(m2, name=m2_name, outputs=new_ports, states=new_states)

    program = Program(machines=(m1, m2b), source_file="<generated>.fsm")
    return program, "duplicate_output_across_machines"


# Registry of every perturbation by its violation-kind label.
PERTURBATIONS: dict[str, st.SearchStrategy[tuple[Program, str]]] = {
    "drop_output": drop_output(),
    "strip_else": strip_else(),
    "repoint_target": repoint_target(),
    "inject_clk_rst": inject_clk_rst(),
    "duplicate_state": duplicate_state(),
    "duplicate_output_across_machines": duplicate_output_across_machines(),
}

VIOLATION_KINDS: frozenset[str] = frozenset(PERTURBATIONS)


def invalid_program() -> st.SearchStrategy[tuple[Program, str]]:
    """A strategy over all perturbations: ``(program, expected_violation_kind)``."""
    return st.one_of(*PERTURBATIONS.values())


# ---------------------------------------------------------------------------
# Invariant assertions (structural checks usable before the safety checker
# lands; also exercised by the self-test).
# ---------------------------------------------------------------------------
def assert_valid_machine_invariants(m: Machine) -> None:
    """Assert a machine satisfies all four safety rules structurally."""
    state_names = [s.name for s in m.states]
    declared = set(state_names)

    # Exactly one machine's worth of states, all named.
    assert len(state_names) >= 1
    # State names are unique (single, well-formed declarations).
    assert len(declared) == len(state_names), "duplicate state declaration"

    # Output names unique per machine (single driver).
    out_names = [p.name for p in m.outputs]
    assert len(set(out_names)) == len(out_names), "duplicate output declaration"

    # No declared port may shadow the implicit clk/rst ports.
    for port in (*m.inputs, *m.outputs):
        assert port.name not in _RESERVED_PORTS, f"reserved port name {port.name!r}"
        assert port.name not in _KEYWORDS

    # Reset target resolves.
    assert m.reset_state in declared, "reset target not declared"

    required_outputs = set(out_names)
    for s in m.states:
        # Total outputs: every declared output assigned exactly once.
        assigned = [a.output_name for a in s.outputs]
        assert set(assigned) == required_outputs, f"state {s.name} missing outputs"
        assert len(assigned) == len(set(assigned)), f"state {s.name} double-assigns"

        # Total transitions: non-empty and ends with `else`.
        assert s.transitions, f"state {s.name} has no transitions"
        assert s.transitions[-1].kind == "else", f"state {s.name} missing final else"
        # Only the final transition may be `else`.
        for t in s.transitions[:-1]:
            assert t.kind == "when", f"state {s.name} has a non-final else"
        # Name resolution: every transition target resolves.
        for t in s.transitions:
            assert t.target in declared, f"unresolved target {t.target!r}"


def assert_valid_program_invariants(p: Program) -> None:
    """Assert a valid program holds exactly one machine that is itself valid."""
    assert len(p.machines) == 1, "a valid program contains exactly one machine"
    assert_valid_machine_invariants(p.machines[0])
