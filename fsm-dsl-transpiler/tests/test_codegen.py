"""Unit tests for the Code_Generator state-type emission (task 7.1).

Covers :func:`transpiler.codegen.state_width` and
:func:`transpiler.codegen.emit_state_type`:

* width is ``max(1, ceil(log2(N)))`` for representative state counts
  (Req 13.2);
* the emitted ``enum logic`` members are exactly the declared states, in
  declared order (Req 13.1);
* ``state``/``next_state`` are declared with the enum type and no literal
  state codes are emitted (Req 13.3).
"""

from __future__ import annotations

import re

import pytest

from transpiler.ast import Condition, Loc, Machine, State, Transition
from transpiler.codegen import (
    emit_next_state_block,
    emit_output_block,
    emit_sequential_block,
    emit_state_type,
    render_guard,
    state_width,
)

_LOC = Loc(file="<test>.fsm", line=1, column=1)


def _machine(n_states: int) -> Machine:
    """Build a minimal machine with ``n_states`` declared states (S0..S{n-1})."""
    states = tuple(
        State(name=f"S{i}", outputs=(), transitions=(), loc=_LOC)
        for i in range(n_states)
    )
    return Machine(
        name="m",
        inputs=(),
        outputs=(),
        reset_state=states[0].name,
        states=states,
        loc=_LOC,
    )


@pytest.mark.parametrize(
    ("n_states", "expected_width"),
    [
        (1, 1),  # ceil(log2(1)) == 0 -> clamped to 1
        (2, 1),
        (3, 2),
        (4, 2),
        (5, 3),
        (8, 3),
        (9, 4),
    ],
)
def test_state_width(n_states: int, expected_width: int) -> None:
    assert state_width(_machine(n_states)) == expected_width


def test_emit_state_type_members_match_declared_states_in_order() -> None:
    m = Machine(
        name="seq",
        inputs=(),
        outputs=(),
        reset_state="idle",
        states=(
            State("idle", (), (), _LOC),
            State("s1", (), (), _LOC),
            State("s10", (), (), _LOC),
        ),
        loc=_LOC,
    )
    emitted = emit_state_type(m)

    # The enum body holds exactly the declared state names, in declared order.
    body = re.search(r"\{(.*?)\}", emitted)
    assert body is not None
    members = [name.strip() for name in body.group(1).split(",")]
    assert members == ["idle", "s1", "s10"]


def test_emit_state_type_declares_signals_with_enum_type() -> None:
    m = _machine(3)
    emitted = emit_state_type(m)

    # A single typedef enum sized to width-1, plus state/next_state of that type.
    assert "typedef enum logic [1:0] {" in emitted
    assert "} state_t;" in emitted
    assert "state_t state, next_state;" in emitted


def test_emit_state_type_width_one_for_single_state() -> None:
    emitted = emit_state_type(_machine(1))
    assert "enum logic [0:0]" in emitted


def test_emit_state_type_emits_no_literal_state_codes() -> None:
    # No hand-written integer/bit-vector literal encodings (Req 13.3): the only
    # numbers present are the [W-1:0] range bounds, and there are no sized
    # literals like 2'b01 or assignments of integers to state members.
    emitted = emit_state_type(_machine(5))
    assert "'b" not in emitted
    assert "'d" not in emitted
    assert "'h" not in emitted
    # state members carry no explicit = code assignment.
    assert "=" not in emitted.split("{", 1)[1].split("}", 1)[0]


# ---------------------------------------------------------------------------
# Next-state combinational block (task 7.2): Req 8.5, 11.1, 11.3, 11.6, 12.1,
# 12.2.
# ---------------------------------------------------------------------------


def _when(text: str, target: str) -> Transition:
    """A ``when COND -> target`` transition with guard text ``text``."""
    return Transition(
        kind="when",
        condition=Condition(text=text, loc=_LOC),
        target=target,
        loc=_LOC,
    )


def _else(target: str) -> Transition:
    """An ``else -> target`` transition."""
    return Transition(kind="else", condition=None, target=target, loc=_LOC)


def _machine_with_states(states: tuple[State, ...]) -> Machine:
    return Machine(
        name="m",
        inputs=(),
        outputs=(),
        reset_state=states[0].name,
        states=states,
        loc=_LOC,
    )


def test_next_state_block_is_single_always_comb_with_default_then_case() -> None:
    m = _machine_with_states(
        (
            State("S0", (), (_when("a", "S1"), _else("S0")), _LOC),
            State("S1", (), (_else("S1"),), _LOC),
        )
    )
    emitted = emit_next_state_block(m)
    lines = [line.strip() for line in emitted.splitlines()]

    # Exactly one always_comb header for the next-state block.
    assert emitted.count("always_comb begin") == 1
    # Opens with the unconditional default before any conditional (Req 11.6/12.1).
    assert lines[0] == "always_comb begin"
    assert lines[1] == "next_state = state;"
    assert lines[2] == "case (state)"
    assert "endcase" in lines


def test_next_state_block_has_exactly_one_default_arm() -> None:
    m = _machine_with_states(
        (
            State("S0", (), (_when("a", "S1"), _else("S0")), _LOC),
            State("S1", (), (_else("S1"),), _LOC),
        )
    )
    emitted = emit_next_state_block(m)
    # Single total default arm assigning next_state = state (Req 12.2).
    assert emitted.count("default: next_state = state;") == 1


def test_next_state_block_preserves_guard_order_as_if_else_if() -> None:
    m = _machine_with_states(
        (
            State(
                "S0",
                (),
                (_when("c1", "T1"), _when("c2", "T2"), _when("c3", "T3"), _else("E")),
                _LOC,
            ),
        )
    )
    emitted = emit_next_state_block(m)

    # First guard is `if`, subsequent guards are `else if`, in declared order.
    assert "if (c1) next_state = T1;" in emitted
    assert "else if (c2) next_state = T2;" in emitted
    assert "else if (c3) next_state = T3;" in emitted
    # Order preserved: c1 before c2 before c3.
    assert (
        emitted.index("c1") < emitted.index("c2") < emitted.index("c3")
    )
    # The first guard line is a plain `if`, not `else if`.
    assert "else if (c1)" not in emitted


def test_next_state_block_else_maps_to_trailing_else_within_arm() -> None:
    m = _machine_with_states(
        (State("S0", (), (_when("g", "T"), _else("HOME")), _LOC),)
    )
    emitted = emit_next_state_block(m)

    # The always-true else becomes the trailing `else next_state = HOME;`.
    assert "else next_state = HOME;" in emitted
    # The else clause comes after the guard within the arm.
    assert emitted.index("if (g) next_state = T;") < emitted.index(
        "else next_state = HOME;"
    )


def test_next_state_block_else_only_state_assigns_directly() -> None:
    # A state with only an else (no whens) assigns its target directly, with no
    # if/else chain.
    m = _machine_with_states((State("ONLY", (), (_else("ONLY"),), _LOC),))
    emitted = emit_next_state_block(m)
    assert "ONLY: next_state = ONLY;" in emitted


def test_next_state_block_uses_only_blocking_assignment() -> None:
    m = _machine_with_states(
        (
            State("S0", (), (_when("a", "S1"), _else("S0")), _LOC),
            State("S1", (), (_else("S1"),), _LOC),
        )
    )
    emitted = emit_next_state_block(m)
    # Combinational block: no non-blocking `<=` assignments (Req 11.3).
    assert "<=" not in emitted


# ---------------------------------------------------------------------------
# Output combinational block (task 7.3): Req 11.1, 11.3, 11.6, 12.1, 12.2.
# ---------------------------------------------------------------------------

from transpiler.ast import OutputAssignment, Port, PortType, Value


def _out_port(name: str, high: int = 0, low: int = 0) -> Port:
    """An output port ``name`` of type ``bit[high:low]`` (scalar by default)."""
    return Port(
        direction="out",
        type=PortType(high=high, low=low),
        name=name,
        loc=_LOC,
    )


def _assign(name: str, bits: int) -> OutputAssignment:
    """An output assignment ``name = bits`` for use in a state body."""
    return OutputAssignment(
        output_name=name, value=Value(bits=bits, loc=_LOC), loc=_LOC
    )


def _machine_with_outputs(
    outputs: tuple[Port, ...], states: tuple[State, ...]
) -> Machine:
    return Machine(
        name="m",
        inputs=(),
        outputs=outputs,
        reset_state=states[0].name,
        states=states,
        loc=_LOC,
    )


def test_output_block_is_single_always_comb_opening_with_defaults() -> None:
    outs = (_out_port("y"), _out_port("z", 1, 0))
    m = _machine_with_outputs(
        outs,
        (
            State("S0", (_assign("y", 1), _assign("z", 3)), (), _LOC),
            State("S1", (_assign("y", 0), _assign("z", 1)), (), _LOC),
        ),
    )
    emitted = emit_output_block(m)
    lines = [line.strip() for line in emitted.splitlines()]

    # Exactly one always_comb header for the output block (Req 11.1).
    assert emitted.count("always_comb begin") == 1
    assert lines[0] == "always_comb begin"
    # Opens with a defined default for EVERY output before the case
    # (Req 11.6/12.1), then the case.
    assert lines[1] == "y = '0;"
    assert lines[2] == "z = '0;"
    assert lines[3] == "case (state)"
    assert "endcase" in lines


def test_output_block_state_arm_assigns_each_output_to_sized_literal() -> None:
    outs = (_out_port("y"), _out_port("z", 1, 0))
    m = _machine_with_outputs(
        outs,
        (State("S0", (_assign("y", 1), _assign("z", 3)), (), _LOC),),
    )
    emitted = emit_output_block(m)

    # Each output assigned to a width-sized decimal literal W'dVALUE.
    # y is 1-bit -> 1'd1; z is 2-bit -> 2'd3.
    assert "S0: begin y = 1'd1; z = 2'd3; end" in emitted


def test_output_block_has_single_default_arm_assigning_all_outputs() -> None:
    outs = (_out_port("y"), _out_port("z", 1, 0))
    m = _machine_with_outputs(
        outs,
        (
            State("S0", (_assign("y", 1), _assign("z", 3)), (), _LOC),
            State("S1", (_assign("y", 0), _assign("z", 0)), (), _LOC),
        ),
    )
    emitted = emit_output_block(m)

    # Exactly one default arm, and it assigns every declared output (Req 12.2).
    assert emitted.count("default:") == 1
    assert "default: begin y = '0; z = '0; end" in emitted


def test_output_block_falls_back_to_default_for_unassigned_output() -> None:
    # If a state omits an output, the arm still assigns it (to '0) so the arm
    # remains total even on un-validated input.
    outs = (_out_port("y"), _out_port("z", 1, 0))
    m = _machine_with_outputs(
        outs,
        (State("S0", (_assign("y", 1),), (), _LOC),),
    )
    emitted = emit_output_block(m)
    assert "S0: begin y = 1'd1; z = '0; end" in emitted


def test_output_block_uses_only_blocking_assignment() -> None:
    outs = (_out_port("y"),)
    m = _machine_with_outputs(
        outs,
        (
            State("S0", (_assign("y", 1),), (), _LOC),
            State("S1", (_assign("y", 0),), (), _LOC),
        ),
    )
    emitted = emit_output_block(m)
    # Combinational block: no non-blocking `<=` assignments (Req 11.3).
    assert "<=" not in emitted


def test_output_block_with_no_outputs_is_well_formed() -> None:
    m = _machine_with_outputs(
        (),
        (State("S0", (), (), _LOC),),
    )
    emitted = emit_output_block(m)
    assert emitted.count("always_comb begin") == 1
    assert "case (state)" in emitted
    assert "default: begin  end" in emitted
    assert "<=" not in emitted


# ---------------------------------------------------------------------------
# Sequential state-register block (task 7.4): Req 11.2, 11.4, 11.5, 13.4-13.6.
# ---------------------------------------------------------------------------


def _machine_with_reset(reset_state: str = "S0") -> Machine:
    """A two-state machine whose reset target is ``reset_state``."""
    return Machine(
        name="m",
        inputs=(),
        outputs=(),
        reset_state=reset_state,
        states=(
            State("S0", (), (_else("S0"),), _LOC),
            State("S1", (), (_else("S1"),), _LOC),
        ),
        loc=_LOC,
    )


def test_sequential_block_header_is_synchronous_posedge_clk_only() -> None:
    emitted = emit_sequential_block(_machine_with_reset())
    lines = [line.strip() for line in emitted.splitlines()]

    # Exactly one always_ff block whose sensitivity list is just posedge clk.
    assert emitted.count("always_ff @(posedge clk) begin") == 1
    assert lines[0] == "always_ff @(posedge clk) begin"
    # No asynchronous reset term in the sensitivity list (Req 13.5).
    assert "posedge rst" not in emitted
    assert "negedge" not in emitted


def test_sequential_block_reset_is_active_high_loading_reset_state() -> None:
    emitted = emit_sequential_block(_machine_with_reset("S1"))

    # Active-high reset (`if (rst)`) loads the machine's reset_state (Req 13.6).
    assert "if (rst) state <= S1;" in emitted
    # Reset precedes the next_state update.
    assert emitted.index("if (rst) state <= S1;") < emitted.index(
        "state <= next_state;"
    )


def test_sequential_block_else_loads_next_state() -> None:
    emitted = emit_sequential_block(_machine_with_reset())
    assert "else" in emitted
    assert "state <= next_state;" in emitted


def test_sequential_block_uses_only_non_blocking_assignment() -> None:
    emitted = emit_sequential_block(_machine_with_reset())

    # Non-blocking `<=` is used (Req 11.2, 11.4).
    assert "<=" in emitted
    # No blocking assignment to a register: every `=` is part of `<=` (the
    # only `=` characters appear immediately after a `<`). Strip `<=` and the
    # equality operator `==`, then assert no bare `=` remains.
    residue = emitted.replace("<=", "").replace("==", "")
    assert "=" not in residue


def test_sequential_block_loads_only_the_state_register() -> None:
    # The block assigns `state` and nothing else (Req 11.5): the only
    # assignment targets are `state`.
    emitted = emit_sequential_block(_machine_with_reset())
    assignments = [
        line.strip() for line in emitted.splitlines() if "<=" in line
    ]
    assert assignments == [
        "if (rst) state <= S0;",
        "else     state <= next_state;",
    ]
    for line in assignments:
        # Left of `<=` resolves to the `state` register only.
        lhs = line.split("<=")[0]
        assert lhs.split()[-1] == "state"


# ---------------------------------------------------------------------------
# Full module assembly via generate() (task 7.5): Req 2.3, 2.4, 3.4, 11.1.
# ---------------------------------------------------------------------------

from transpiler.ast import build_ast
from transpiler.codegen import generate
from transpiler.parser import parse


def _in_port(name: str, high: int = 0, low: int = 0) -> Port:
    """An input port ``name`` of type ``bit[high:low]`` (scalar by default)."""
    return Port(
        direction="in",
        type=PortType(high=high, low=low),
        name=name,
        loc=_LOC,
    )


def _full_machine() -> Machine:
    """A small 2-state machine with scalar and vector inputs/outputs."""
    return Machine(
        name="ctrl",
        inputs=(_in_port("go"), _in_port("cmd", 1, 0)),
        outputs=(_out_port("done"), _out_port("code", 3, 0)),
        states=(
            State(
                "IDLE",
                (_assign("done", 0), _assign("code", 0)),
                (_when("go", "RUN"), _else("IDLE")),
                _LOC,
            ),
            State(
                "RUN",
                (_assign("done", 1), _assign("code", 5)),
                (_else("IDLE"),),
                _LOC,
            ),
        ),
        reset_state="IDLE",
        loc=_LOC,
    )


def test_generate_emits_module_header_with_name_and_implicit_clk_rst() -> None:
    emitted = generate(_full_machine())
    assert "module ctrl (" in emitted
    # Implicit clk/rst inputs are added first, never author-declared (Req 3.4).
    assert "input  logic clk" in emitted
    assert "input  logic rst" in emitted
    assert emitted.index("input  logic clk") < emitted.index("input  logic rst")
    assert emitted.rstrip().endswith("endmodule")


def test_generate_declares_ports_at_correct_widths() -> None:
    emitted = generate(_full_machine())
    # Scalar bit ports carry no range (Req 2.3).
    assert "input  logic go" in emitted
    assert "output logic done" in emitted
    # Vector bit[H:L] ports carry their [high:low] range (Req 2.4).
    assert "input  logic [1:0] cmd" in emitted
    assert "output logic [3:0] code" in emitted


def test_generate_port_list_has_no_trailing_comma() -> None:
    emitted = generate(_full_machine())
    header = emitted.split(");", 1)[0]
    port_lines = [
        line.rstrip()
        for line in header.splitlines()
        if "logic" in line
    ]
    # Every port line but the last ends with a comma; the last has none.
    for line in port_lines[:-1]:
        assert line.endswith(","), line
    assert not port_lines[-1].endswith(","), port_lines[-1]


def test_generate_contains_exactly_three_procedural_blocks() -> None:
    emitted = generate(_full_machine())
    # Exactly two always_comb and one always_ff -> three procedural blocks (Req 11.1).
    assert emitted.count("always_comb begin") == 2
    assert emitted.count("always_ff @(posedge clk) begin") == 1


def test_generate_includes_state_type_and_sequential_reset() -> None:
    emitted = generate(_full_machine())
    assert "typedef enum logic" in emitted
    assert "state_t state, next_state;" in emitted
    assert "if (rst) state <= IDLE;" in emitted


def test_generate_from_parsed_source_produces_well_formed_module() -> None:
    source = """
    machine seq3 {
        in bit a
        out bit y
        reset = S0

        state S0 {
            y = 0
            when a -> S1
            else -> S0
        }
        state S1 {
            y = 0
            when a -> S2
            else -> S0
        }
        state S2 {
            y = 1
            else -> S0
        }
    }
    """
    program = build_ast(parse(source, file="<input>"), source_file="<input>")
    machine = program.machines[0]
    emitted = generate(machine)

    # Header + implicit clk/rst + declared scalar ports (Req 2.3, 3.4).
    assert "module seq3 (" in emitted
    assert "input  logic clk" in emitted
    assert "input  logic rst" in emitted
    assert "input  logic a" in emitted
    assert "output logic y" in emitted
    # Three procedural blocks (Req 11.1) and a single 2-bit state enum (3 states).
    assert emitted.count("always_comb begin") == 2
    assert emitted.count("always_ff @(posedge clk) begin") == 1
    assert "enum logic [1:0]" in emitted
    assert emitted.rstrip().endswith("endmodule")


# ---------------------------------------------------------------------------
# Property 17 (task 7.6): three procedural blocks with separated assignment
# operators. Validates Requirements 11.1, 11.2, 11.3, 11.4.
# ---------------------------------------------------------------------------

from hypothesis import given, settings

from tests import strategies as S


def _procedural_blocks(module: str) -> list[tuple[str, str]]:
    """Split ``module`` into its procedural blocks.

    Returns a list of ``(kind, body)`` tuples where ``kind`` is ``"always_comb"``
    or ``"always_ff"`` and ``body`` is the block's full text from its header
    line through its closing level-1 ``end``. Procedural blocks never nest an
    ``always``, and every block emitter closes with a four-space ``    end``
    line, while every inner ``end``/``endcase`` is indented deeper. So a block
    runs from an ``always*`` header to the next line that is exactly ``    end``.
    """
    lines = module.splitlines()
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("always_comb") or stripped.startswith("always_ff"):
            kind = "always_ff" if stripped.startswith("always_ff") else "always_comb"
            body_lines = [lines[i]]
            j = i + 1
            while j < len(lines):
                body_lines.append(lines[j])
                if lines[j] == "    end":  # the block's closing level-1 end
                    break
                j += 1
            blocks.append((kind, "\n".join(body_lines)))
            i = j + 1
        else:
            i += 1
    return blocks


def _strip_conditions(text: str) -> str:
    """Remove parenthesized guard/case selectors so only statements remain.

    Comparison operators (``<=``, ``>=``, ``==`` ...) live inside ``if (...)`` /
    ``else if (...)`` guard expressions and the ``case (state)`` selector. The
    grammar admits no nested parentheses in a guard, so removing each ``(...)``
    group strips every comparison operator and leaves only assignment
    statements — letting an *assignment* ``<=`` or ``=`` be detected without
    confusing it with a comparison.
    """
    return re.sub(r"\([^()]*\)", "", text)


def _strip_non_blocking(text: str) -> str:
    """Remove every non-`=`-assignment operator so a bare blocking `=` stands out.

    Drops ``<=``, ``>=``, ``==``, and ``!=`` so the only ``=`` left in the
    result is a blocking assignment operator.
    """
    for op in ("<=", ">=", "==", "!="):
        text = text.replace(op, "")
    return text


# Feature: fsm-dsl-transpiler, Property 17: Generated module has exactly three
# procedural blocks with separated assignment operators
@settings(max_examples=200, deadline=None)
@given(S.valid_machine())
def test_three_procedural_blocks_with_separated_operators(machine) -> None:
    """Property 17: exactly three procedural blocks, operators never mixed.

    For any valid machine, the generated module contains exactly three
    procedural blocks — two ``always_comb`` and one ``always_ff @(posedge
    clk)`` — where non-blocking ``<=`` occurs only in the ``always_ff`` block,
    blocking ``=`` occurs only in the ``always_comb`` blocks, and no single
    block contains both operators.

    **Validates: Requirements 11.1, 11.2, 11.3, 11.4**
    """
    module = generate(machine)

    # Req 11.1: exactly two always_comb and one always_ff -> three blocks total.
    assert module.count("always_comb begin") == 2
    assert module.count("always_ff @(posedge clk) begin") == 1

    blocks = _procedural_blocks(module)
    assert len(blocks) == 3, blocks
    kinds = [kind for kind, _ in blocks]
    assert kinds.count("always_comb") == 2
    assert kinds.count("always_ff") == 1

    for kind, body in blocks:
        # Comparison operators live inside guard/case parentheses; strip them
        # so only assignment statements remain before classifying operators.
        statements = _strip_conditions(body)
        if kind == "always_ff":
            # Sequential block: non-blocking `<=` assignment is used
            # (Req 11.2, 11.4) and no blocking `=` assignment appears.
            assert "<=" in statements
            assert "=" not in _strip_non_blocking(statements), body
        else:
            # Combinational block: blocking `=` assignment is used and no
            # non-blocking `<=` assignment appears (Req 11.3). Empty-output
            # machines may carry no `=`, so only the absence of an assignment
            # `<=` is universal here.
            assert "<=" not in statements, body


# ---------------------------------------------------------------------------
# Property 18 (task 7.7): combinational blocks assign defaults to every target
# before any conditional, and each case has exactly one total default arm.
# Validates Requirements 11.6, 12.1, 12.2.
# ---------------------------------------------------------------------------


def _split_at_case(body: str) -> tuple[list[str], list[str]]:
    """Split a combinational block ``body`` around its ``case (state)`` line.

    Returns ``(pre_lines, arm_lines)`` where ``pre_lines`` are the statements
    between the ``always_comb begin`` header and the ``case (state)`` selector
    (i.e. the unconditional defaults), and ``arm_lines`` are the lines between
    ``case (state)`` and ``endcase`` (the state arms plus the ``default:`` arm).
    """
    lines = body.splitlines()
    case_idx = next(
        i for i, line in enumerate(lines) if line.strip().startswith("case (state)")
    )
    endcase_idx = next(
        i for i, line in enumerate(lines) if line.strip() == "endcase"
    )
    pre_lines = lines[1:case_idx]
    arm_lines = lines[case_idx + 1 : endcase_idx]
    return pre_lines, arm_lines


def _assignment_targets(text: str) -> set[str]:
    """Return the LHS identifier of every blocking assignment in ``text``.

    Guard/case selectors live inside ``(...)`` groups, so they are stripped
    first (reusing :func:`_strip_conditions`) to drop comparison operators.
    Each remaining ``;``-terminated statement that contains a blocking ``=``
    contributes its left-hand-side identifier — the last whitespace-separated
    token before the ``=`` (so ``if next_state = T`` and ``else y = '0`` both
    resolve to their assigned signal).
    """
    cleaned = _strip_conditions(text)
    targets: set[str] = set()
    for statement in cleaned.split(";"):
        if " = " not in statement:
            continue
        lhs = statement.split(" = ", 1)[0].strip()
        targets.add(lhs.split()[-1])
    return targets


# Feature: fsm-dsl-transpiler, Property 18: Combinational blocks assign defaults
# to all targets and cases have one total default arm
@settings(max_examples=200, deadline=None)
@given(S.valid_machine())
def test_combinational_defaults_and_total_default_arm(machine) -> None:
    """Property 18: defaults precede conditionals; one total default arm.

    For any valid machine, each generated ``always_comb`` block assigns a
    default to every signal it targets *before* the ``case`` statement, and the
    ``case`` contains exactly one ``default:`` arm that assigns every signal
    assigned by any other arm of that case.

    * Next-state block: targets ``{next_state}``; opens with
      ``next_state = state;`` before the case; the single ``default:`` arm
      assigns ``next_state``.
    * Output block: targets every declared output; before the case every output
      has a ``<out> = '0;`` default; the single ``default:`` arm assigns all
      outputs.

    **Validates: Requirements 11.6, 12.1, 12.2**
    """
    module = generate(machine)
    output_names = {port.name for port in machine.outputs}

    comb_blocks = [
        body for kind, body in _procedural_blocks(module) if kind == "always_comb"
    ]
    assert len(comb_blocks) == 2, comb_blocks

    saw_next_state = False
    saw_output = False

    for body in comb_blocks:
        # Req 12.2: exactly one default arm in this block's case.
        assert body.count("default:") == 1, body

        pre_lines, arm_lines = _split_at_case(body)
        default_lines = [
            line for line in arm_lines if line.strip().startswith("default:")
        ]
        state_arm_lines = [
            line for line in arm_lines if not line.strip().startswith("default:")
        ]
        assert len(default_lines) == 1

        pre_targets = _assignment_targets("\n".join(pre_lines))
        default_targets = _assignment_targets("\n".join(default_lines))
        state_arm_targets = _assignment_targets("\n".join(state_arm_lines))

        if "next_state" in pre_targets:
            # Next-state block: sole target is next_state (Req 12.1).
            saw_next_state = True
            assert pre_targets == {"next_state"}
            # Opens with the unconditional default before the case (Req 11.6).
            assert pre_lines[0].strip() == "next_state = state;"
            # The single default arm assigns next_state (Req 12.2).
            assert default_targets == {"next_state"}
            # Every state arm assigns only next_state.
            assert state_arm_targets <= {"next_state"}
        else:
            # Output block: defaults cover every declared output (Req 11.6/12.1).
            saw_output = True
            assert pre_targets == output_names
            for port in machine.outputs:
                assert f"{port.name} = '0;" in "\n".join(pre_lines)
            # The single default arm assigns all outputs (Req 12.2).
            assert default_targets == output_names
            # Defaults precede the case selector for every targeted signal.
            assert state_arm_targets == output_names or not output_names

        # The default arm assigns exactly the signals assigned by the other arms
        # of this case (Req 12.2): defaults, state arms, and the default arm all
        # target the same signal set.
        assert default_targets == pre_targets
        assert state_arm_targets <= default_targets

    assert saw_next_state and saw_output


# ---------------------------------------------------------------------------
# Property 19 (task 7.8): the state type is an enum whose members are exactly
# the declared states, sized to the correct width.
# Validates Requirements 13.1, 13.2, 13.3.
# ---------------------------------------------------------------------------

import math


# Feature: fsm-dsl-transpiler, Property 19: State type is an enum whose members
# are exactly the declared states with correct width
@settings(max_examples=200, deadline=None)
@given(S.valid_machine())
def test_state_type_is_enum_of_exactly_declared_states_with_correct_width(
    machine,
) -> None:
    """Property 19: enum members are exactly the declared states, correctly sized.

    For any valid machine with ``N`` declared states, the generated module
    declares a single ``enum logic`` state type whose members are exactly the
    ``N`` declared state names (no more, no fewer), sized to
    ``max(1, ceil(log2(N)))`` bits, and declares ``state`` and ``next_state``
    with that type using no hand-written integer/bit-vector literal state codes.

    **Validates: Requirements 13.1, 13.2, 13.3**
    """
    module = generate(machine)

    declared = [state.name for state in machine.states]
    n = len(declared)
    expected_width = max(1, math.ceil(math.log2(n))) if n > 1 else 1

    # The width helper agrees with the independently-computed expectation.
    assert state_width(machine) == expected_width

    # Req 13.1/13.2: exactly one typedef enum logic [W-1:0] { ... } state_t;
    # whose range is [state_width-1:0].
    enum_pattern = re.compile(
        r"typedef enum logic \[(\d+):0\] \{(.*?)\} state_t;"
    )
    matches = enum_pattern.findall(module)
    assert len(matches) == 1, module
    high_bound, body = matches[0]
    assert int(high_bound) == expected_width - 1

    # Req 13.1: members between { } are exactly the declared states, in order.
    members = [name.strip() for name in body.split(",")]
    assert members == declared

    # Req 13.3: state/next_state are declared with the enum type.
    assert "state_t state, next_state;" in module

    # Req 13.3: no hand-written literal state codes. The enum body carries no
    # `=` assignment and no sized literals (`'b`, `'d`, `'h`).
    assert "=" not in body
    assert "'b" not in body
    assert "'d" not in body
    assert "'h" not in body

    # state/next_state use the enum type, not a hand-written bit vector.
    assert not re.search(r"logic \[\d+:\d+\] (?:state|next_state)\b", module)


# ---------------------------------------------------------------------------
# Property 20 (task 7.9): reset logic is synchronous, active-high, and confined
# to the sequential block.
# Validates Requirements 11.5, 13.4, 13.5.
# ---------------------------------------------------------------------------


# Feature: fsm-dsl-transpiler, Property 20: Reset logic is synchronous,
# active-high, and confined to the sequential block
@settings(max_examples=200, deadline=None)
@given(S.valid_machine())
def test_reset_logic_is_synchronous_active_high_and_confined(machine) -> None:
    """Property 20: synchronous, active-high reset confined to the always_ff block.

    For any valid machine, the generated reset logic appears ONLY inside the
    ``always_ff @(posedge clk)`` block, with no asynchronous reset term in the
    sensitivity list, and never appears in any combinational block.

    * The single ``always_ff`` header is exactly ``always_ff @(posedge clk)``
      — no ``posedge rst``, ``negedge``, or ``or rst`` async term (Req 13.5).
    * The sequential block carries the active-high ``if (rst)`` reset that loads
      the machine's reset state into ``state`` (Req 11.5, 13.4).
    * Neither ``always_comb`` block references ``rst`` — the reset is confined
      to the sequential block (Req 13.4).

    **Validates: Requirements 11.5, 13.4, 13.5**
    """
    module = generate(machine)

    # Req 13.5: no asynchronous reset term anywhere in the module sensitivity
    # lists. The only edge-sensitive construct is `@(posedge clk)`.
    assert "posedge rst" not in module
    assert "negedge" not in module
    assert "or rst" not in module

    blocks = _procedural_blocks(module)
    ff_blocks = [body for kind, body in blocks if kind == "always_ff"]
    comb_blocks = [body for kind, body in blocks if kind == "always_comb"]

    # Exactly one sequential block and two combinational blocks.
    assert len(ff_blocks) == 1, blocks
    assert len(comb_blocks) == 2, blocks

    ff_body = ff_blocks[0]
    ff_header = ff_body.splitlines()[0].strip()

    # The always_ff header is exactly `always_ff @(posedge clk)` — purely
    # synchronous, no async reset term in the sensitivity list (Req 13.5).
    assert ff_header == "always_ff @(posedge clk) begin"

    # Req 11.5/13.4: the reset lives in the sequential block, is active-high,
    # and loads the machine's reset state into `state`.
    assert "rst" in ff_body
    assert f"if (rst) state <= {machine.reset_state};" in ff_body

    # Active-high reset: the condition is `if (rst)`, never `if (!rst)` or
    # `if (~rst)`.
    assert "if (!rst)" not in ff_body
    assert "if (~rst)" not in ff_body

    # Req 13.4: reset is confined to the sequential block — no combinational
    # block references `rst`.
    for body in comb_blocks:
        assert "rst" not in body, body

# ---------------------------------------------------------------------------
# Property 21 (task 7.10): an asserted reset loads the reset state, overriding
# the next-state transition value.
# Validates Requirements 13.6.
# ---------------------------------------------------------------------------

import shutil
import subprocess
import tempfile
from pathlib import Path


def _sequential_block_body(module: str) -> str:
    """Return the body text of the module's single ``always_ff`` block."""
    ff_blocks = [
        body for kind, body in _procedural_blocks(module) if kind == "always_ff"
    ]
    assert len(ff_blocks) == 1, module
    return ff_blocks[0]


# Feature: fsm-dsl-transpiler, Property 21: Asserted reset loads the reset
# state, overriding next-state
@settings(max_examples=200, deadline=None)
@given(S.valid_machine())
def test_asserted_reset_loads_reset_state_overriding_next_state(machine) -> None:
    """Property 21: an asserted reset loads the reset state, overriding next-state.

    For any valid machine, when ``rst`` is high at a rising edge of ``clk`` the
    state register takes the value of the ``reset`` declaration on the next
    cycle, taking precedence over any next-state transition value.

    The ``always_ff @(posedge clk)`` block is the source of truth for this
    behavior, so the property is verified structurally against that block:

    * the reset is checked FIRST — the ``if (rst)`` branch loads exactly
      ``machine.reset_state`` and appears before the ``else`` branch;
    * the ``else`` branch (taken only when ``rst`` is low) loads ``next_state``.

    In SystemVerilog an ``if (rst) ... else ...`` chain evaluates the ``if``
    branch first, so when ``rst`` is high the reset assignment wins regardless
    of the ``next_state`` value — structurally guaranteeing reset precedence
    (Req 13.6).

    **Validates: Requirements 13.6**
    """
    module = generate(machine)
    ff_body = _sequential_block_body(module)

    reset_line = f"if (rst) state <= {machine.reset_state};"
    next_line = "state <= next_state;"

    # The reset branch loads exactly the reset declaration's state.
    assert reset_line in ff_body, ff_body
    # The else branch (rst low) loads the next-state value.
    assert next_line in ff_body, ff_body

    # Reset is checked first and takes precedence: the `if (rst)` reset
    # assignment appears before the `else` next-state assignment, and the
    # next-state load is the `else` arm of that same if/else chain.
    reset_idx = ff_body.index(reset_line)
    else_idx = ff_body.index("else")
    next_idx = ff_body.index(next_line)
    assert reset_idx < else_idx < next_idx + len(next_line)
    # The next-state load is guarded by `else`, never an unconditional load
    # that could override the reset.
    assert f"else     state <= next_state;" in ff_body or "else" in ff_body


# Optional dynamic confirmation: if a Verilog simulator is available on PATH,
# additionally simulate that asserting rst loads the reset state. Skipped when
# no simulator is installed (the structural assertion above is the always-run
# core of Property 21).
_IVERILOG = shutil.which("iverilog")
_VVP = shutil.which("vvp")


@pytest.mark.skipif(
    _IVERILOG is None or _VVP is None,
    reason="iverilog/vvp not on PATH; structural reset-precedence check covers Property 21",
)
def test_asserted_reset_loads_reset_state_in_simulation() -> None:
    """If iverilog is present, confirm rst loads the reset state in simulation.

    Drives the state register so that, absent reset, ``next_state`` would move
    to ``B`` on the next edge; asserting ``rst`` instead must land in the reset
    state ``A`` (Req 13.6).
    """
    m = Machine(
        name="rprec",
        inputs=(_in_port("go"),),
        outputs=(_out_port("y"),),
        states=(
            State("A", (_assign("y", 0),), (_when("go", "B"), _else("A")), _LOC),
            State("B", (_assign("y", 1),), (_else("B"),), _LOC),
        ),
        reset_state="A",
        loc=_LOC,
    )
    module = generate(m)

    tb = """
module tb;
  logic clk = 0, rst = 0, go = 1;
  logic y;
  rprec dut(.clk(clk), .rst(rst), .go(go), .y(y));
  initial begin
    // Release reset, take one edge so state would advance toward B.
    rst = 0; go = 1;
    #1 clk = 1; #1 clk = 0;
    // Now assert reset at the next rising edge: must load reset state A (y==0).
    rst = 1;
    #1 clk = 1; #1 clk = 0;
    if (y !== 1'b0) begin
      $display("FAIL: reset did not load reset state, y=%b", y);
      $finish(1);
    end
    $display("PASS");
    $finish(0);
  end
endmodule
"""
    with tempfile.TemporaryDirectory() as d:
        dpath = Path(d)
        (dpath / "dut.sv").write_text(module, encoding="utf-8")
        (dpath / "tb.sv").write_text(tb, encoding="utf-8")
        out = dpath / "sim.out"
        compile_proc = subprocess.run(
            [_IVERILOG, "-g2012", "-o", str(out), str(dpath / "dut.sv"), str(dpath / "tb.sv")],
            capture_output=True,
            text=True,
        )
        assert compile_proc.returncode == 0, compile_proc.stderr
        run_proc = subprocess.run(
            [_VVP, str(out)], capture_output=True, text=True
        )
        assert "PASS" in run_proc.stdout, run_proc.stdout + run_proc.stderr


# ---------------------------------------------------------------------------
# Property 22 (task 7.11): transition selection preserves declared order with
# else as the default.
# Validates Requirements 8.5.
# ---------------------------------------------------------------------------


def _next_state_case_arms(machine) -> list[list[str]]:
    """Split the next-state block's ``case`` into per-state arms, in order.

    Returns one group of *stripped* source lines per ``case`` arm, in the order
    they are emitted, **excluding** the trailing ``default:`` arm. A guarded
    arm is a multi-line ``NAME: begin ... end`` group (the begin line, the
    ``if``/``else if``/``else`` chain, and the closing ``end``); an else-only
    arm is a single ``NAME: next_state = TARGET;`` line.

    Arms are returned positionally so they zip directly against
    ``machine.states`` in declared order — this avoids any ambiguity if a state
    happens to be named ``default``.
    """
    block = emit_next_state_block(machine)
    lines = block.splitlines()
    case_idx = next(
        i for i, line in enumerate(lines) if line.strip() == "case (state)"
    )
    endcase_idx = next(
        i for i, line in enumerate(lines) if line.strip() == "endcase"
    )
    arm_lines = lines[case_idx + 1 : endcase_idx]

    arms: list[list[str]] = []
    i = 0
    while i < len(arm_lines):
        stripped = arm_lines[i].strip()
        if stripped.endswith("begin"):
            group = [stripped]
            i += 1
            while arm_lines[i].strip() != "end":
                group.append(arm_lines[i].strip())
                i += 1
            group.append("end")  # the matching level-3 close
            i += 1
            arms.append(group)
        else:
            arms.append([stripped])
            i += 1

    # The final arm is always the single-line `default: next_state = state;`.
    assert arms, block
    assert arms[-1] == ["default: next_state = state;"], arms[-1]
    return arms[:-1]


# Feature: fsm-dsl-transpiler, Property 22: Transition selection preserves
# declared order with else as default
@settings(max_examples=200, deadline=None)
@given(S.valid_machine())
def test_transition_selection_preserves_declared_order(machine) -> None:
    """Property 22: next-state logic preserves declared transition order.

    For any state with an ordered list of guarded transitions ending in
    ``else -> STATE``, the generated next-state logic selects the target of the
    first guard that evaluates true and the ``else`` target when no guard is
    true, matching the declared top-to-bottom order.

    Verified structurally against the next-state ``always_comb`` block. For
    each state arm:

    * with one or more ``when`` guards, the arm is an ``if`` / ``else if``
      chain in declared order — the first guard uses ``if`` (never
      ``else if``), every subsequent guard uses ``else if``, each guard's
      condition text and target match the machine's declared transition order,
      and the chain ends with ``else next_state = <else_target>;`` whose target
      is the state's final ``else`` transition;
    * with only an ``else`` (no guards), the arm is the single line
      ``STATE: next_state = <else_target>;``.

    **Validates: Requirements 8.5**
    """
    arms = _next_state_case_arms(machine)
    # One arm per declared state, in declared order (the default arm excluded).
    assert len(arms) == len(machine.states), (arms, machine.states)

    # Guards are rendered width-correctly; build the expected chain with the
    # same renderer the generator uses so the comparison checks declared order
    # (not raw guard text).
    widths = {port.name: port.type.width for port in machine.inputs}

    for state, arm in zip(machine.states, arms):
        whens = [t for t in state.transitions if t.kind == "when"]
        else_targets = [t.target for t in state.transitions if t.kind == "else"]
        # A valid machine always ends every state with exactly one `else`.
        assert len(else_targets) == 1, state
        else_target = else_targets[0]

        if not whens:
            # Else-only state: a single direct assignment to the else target.
            assert arm == [f"{state.name}: next_state = {else_target};"], arm
            continue

        # Guarded state: `NAME: begin` ... if/else-if chain ... `end`.
        assert arm[0] == f"{state.name}: begin", arm
        assert arm[-1] == "end", arm
        body = arm[1:-1]

        # Build the expected chain from the declared order: first guard `if`,
        # subsequent guards `else if`, then the trailing `else` default.
        expected: list[str] = []
        for index, transition in enumerate(whens):
            keyword = "if" if index == 0 else "else if"
            guard = render_guard(transition.condition, widths)
            expected.append(
                f"{keyword} ({guard}) next_state = {transition.target};"
            )
        expected.append(f"else next_state = {else_target};")

        # The emitted chain matches the declared order exactly (conditions,
        # targets, and if/else-if/else structure).
        assert body == expected, (body, expected)

        # Explicitly: the first guard is a plain `if`, not `else if`.
        assert body[0].startswith("if ("), body[0]
        assert not body[0].startswith("else if"), body[0]
        # Every subsequent guard line is an `else if`.
        for guard_line in body[1 : len(whens)]:
            assert guard_line.startswith("else if ("), guard_line
        # The trailing line is the always-true `else` default.
        assert body[-1] == f"else next_state = {else_target};", body[-1]
