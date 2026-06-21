"""Code_Generator for the FSM_DSL transpiler.

This module turns a *validated* :class:`~transpiler.ast.Machine` into a single
three-always-block SystemVerilog module (design "Module Layout"):

* a single ``enum logic`` state type whose members are exactly the declared
  states, sized ``max(1, ceil(log2(N)))`` bits, with ``state``/``next_state``
  declared using that type and no hand-written literal state codes
  (Req 13.1-13.3);
* an ``always_comb`` next-state block (Req 11/12);
* an ``always_comb`` output block (Req 11/12);
* an ``always_ff @(posedge clk)`` sequential block with synchronous,
  active-high reset (Req 11.2, 13.4-13.6).

The generator runs only after the Safety_Checker has returned an empty
diagnostic list; :func:`generate` documents that precondition.

Task 7.1 implements the state-type emission (:func:`state_width`,
:func:`emit_state_type`) and the supporting module-level scaffolding
(:data:`INDENT`, :func:`_indent`). Tasks 7.2-7.4 add the next-state block,
output block, and sequential block; task 7.5 adds :func:`generate`, which
emits the module header (implicit ``clk``/``rst`` plus declared ports at their
correct widths) and assembles it with the three procedural blocks into the
complete module.
"""

from __future__ import annotations

import math
import re

from transpiler.ast import (
    And,
    BitSelect,
    Compare,
    Condition,
    Expr,
    Ident,
    IntLiteral,
    Machine,
    Not,
    Or,
    Port,
    State,
)

__all__ = [
    "INDENT",
    "state_width",
    "emit_state_type",
    "render_guard",
    "emit_next_state_block",
    "emit_output_block",
    "emit_sequential_block",
    "unused_inputs",
    "emit_unused_input_waiver",
    "generate",
]

# One level of indentation inside the emitted module body. All block emitters
# share this so the assembled module has consistent formatting.
INDENT = "    "


def _indent(line: str, level: int = 1) -> str:
    """Indent a single source ``line`` by ``level`` units of :data:`INDENT`."""
    return f"{INDENT * level}{line}"


def state_width(m: Machine) -> int:
    """Return the bit width of the state encoding for machine ``m``.

    The width is ``max(1, ceil(log2(N)))`` where ``N`` is the number of
    declared states (Req 13.2). For ``N <= 1`` this is ``1`` (``ceil(log2(1))``
    is ``0``), so the encoding is never zero-width.

    Args:
        m: The machine whose state encoding width is computed.

    Returns:
        The number of bits in the ``enum logic [W-1:0]`` state type.
    """
    n = len(m.states)
    return max(1, math.ceil(math.log2(n))) if n > 1 else 1


def emit_state_type(m: Machine) -> str:
    """Emit the ``enum logic`` state type and the state/next-state signals.

    Produces, at one level of indentation inside the module body::

        typedef enum logic [W-1:0] { S0, S1, ... } state_t;
        state_t state, next_state;

    The enumeration members are exactly the declared state names, in declared
    order, one per state and no more (Req 13.1). The type is sized to
    :func:`state_width` (Req 13.2), and both ``state`` and ``next_state`` are
    declared with that enum type, so no hand-written integer or bit-vector
    literal state codes are emitted (Req 13.3).

    Args:
        m: A validated machine with at least one declared state.

    Returns:
        The two declaration lines as a single newline-joined string.
    """
    width = state_width(m)
    members = ", ".join(state.name for state in m.states)
    typedef = f"typedef enum logic [{width - 1}:0] {{ {members} }} state_t;"
    signals = "state_t state, next_state;"
    return "\n".join((_indent(typedef), _indent(signals)))


def _signal_width(expr: Expr, widths: dict[str, int]) -> int | None:
    """Return the bit width of ``expr`` when it is a signal operand, else None.

    An :class:`Ident` resolves to its declared width (defaulting to 1 if the
    name is unknown), and a :class:`BitSelect` is always 1 bit. Anything else
    (a literal or a compound expression) has no single "signal width".
    """
    if isinstance(expr, Ident):
        return widths.get(expr.name, 1)
    if isinstance(expr, BitSelect):
        return 1
    return None


def _render_value(expr: Expr, width: int, widths: dict[str, int]) -> str:
    """Render ``expr`` as a value operand of a comparison, sizing literals.

    A signal is emitted verbatim (``name`` / ``name[i]``); an integer literal is
    sized to ``width`` as ``width'dVALUE`` so a comparison ``signal OP literal``
    is width-matched and lint-clean (no WIDTH/WIDTHTRUNC). The literal is
    guaranteed to fit ``width`` because the AST builder rejects over-wide
    comparison literals.
    """
    if isinstance(expr, Ident):
        return expr.name
    if isinstance(expr, BitSelect):
        return f"{expr.name}[{expr.index}]"
    if isinstance(expr, IntLiteral):
        return f"{width}'d{expr.value}"
    # A compound operand inside a comparison is unusual; render it as a boolean
    # (1-bit) so the comparison stays width-consistent.
    return _render_bool(expr, widths)


def _const_compare_result(op: str, width: int, k: int, sig_on_left: bool) -> bool | None:
    """Fold a ``signal OP literal`` comparison that is constant over the width.

    An unsigned signal of ``width`` bits ranges over ``[0, 2**width - 1]``. For
    a comparison against an in-range literal ``k`` this returns ``True`` if the
    comparison is *always* true, ``False`` if it is *always* false, or ``None``
    if its value genuinely depends on the signal. ``sig_on_left`` says whether
    the signal is the left operand (``sig OP k``) or the right (``k OP sig``);
    in the latter case the operator is mirrored. This lets the generator emit a
    width-trivial guard (e.g. ``e <= 3`` for a 2-bit ``e``) as a plain ``1'b1``
    / ``1'b0`` instead of a constant comparison that Verilator flags as
    ``CMPCONST`` under ``-Wall``.
    """
    lo, hi = 0, (1 << width) - 1
    if not sig_on_left:
        op = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "==": "==", "!=": "!="}[op]
    if op == "<":
        return True if k > hi else (False if k <= lo else None)
    if op == "<=":
        return True if k >= hi else (False if k < lo else None)
    if op == ">":
        return False if k >= hi else (True if k < lo else None)
    if op == ">=":
        return True if k <= lo else (False if k > hi else None)
    if op == "==":
        return False if (k < lo or k > hi) else None
    if op == "!=":
        return True if (k < lo or k > hi) else None
    return None


def _render_compare(expr: Compare, widths: dict[str, int]) -> str:
    """Render a comparison, sizing its literal and folding width-trivial cases.

    The signal operand's width (from either side) sizes the integer literal on
    the other side, e.g. ``f == 3'd5`` for a 3-bit signal. If the width makes
    the comparison *constant* (e.g. ``e <= 3`` with ``e`` 2 bits is always true),
    it is folded to ``1'b1`` / ``1'b0`` so Verilator does not flag ``CMPCONST``
    under ``-Wall`` — the guard's truth value is unchanged. When neither side is
    a signal the literals fall back to a 32-bit size; when both sides are signals
    they are emitted verbatim (the strategy never generates that shape).
    """
    sig_on_left = isinstance(expr.left, (Ident, BitSelect))
    sig_expr = expr.left if sig_on_left else (
        expr.right if isinstance(expr.right, (Ident, BitSelect)) else None
    )
    if isinstance(expr.left, IntLiteral):
        lit = expr.left
    elif isinstance(expr.right, IntLiteral):
        lit = expr.right
    else:
        lit = None

    # Fold a width-trivial constant comparison (signal vs in-range literal).
    if sig_expr is not None and lit is not None:
        sig_w = 1 if isinstance(sig_expr, BitSelect) else widths.get(sig_expr.name, 1)
        folded = _const_compare_result(expr.op, sig_w, lit.value, sig_on_left)
        if folded is True:
            return "1'b1"
        if folded is False:
            return "1'b0"

    sig_width = _signal_width(expr.left, widths)
    if sig_width is None:
        sig_width = _signal_width(expr.right, widths)
    width = sig_width if sig_width is not None else 32
    lhs = _render_value(expr.left, width, widths)
    rhs = _render_value(expr.right, width, widths)
    return f"({lhs} {expr.op} {rhs})"


def _render_bool(expr: Expr, widths: dict[str, int]) -> str:
    """Render ``expr`` coerced to a 1-bit boolean for a boolean context.

    A boolean context is the top-level guard or an operand of ``!`` / ``&&`` /
    ``||``. A multi-bit signal is reduced to 1 bit with the reduction-OR
    operator (``(|sig)``), meaning "non-zero"; a 1-bit signal and a bit-select
    are already 1 bit and pass through unchanged; a comparison is already a
    1-bit result; and an integer literal becomes ``1'b1`` / ``1'b0`` by its
    truth value. This is what keeps guards ``-Wall`` clean (no WIDTHTRUNC from a
    wide signal in a logical context) without suppressing warnings.
    """
    if isinstance(expr, Or):
        return f"({_render_bool(expr.left, widths)} || {_render_bool(expr.right, widths)})"
    if isinstance(expr, And):
        return f"({_render_bool(expr.left, widths)} && {_render_bool(expr.right, widths)})"
    if isinstance(expr, Not):
        return f"(!{_render_bool(expr.operand, widths)})"
    if isinstance(expr, Compare):
        return _render_compare(expr, widths)
    if isinstance(expr, BitSelect):
        return f"{expr.name}[{expr.index}]"
    if isinstance(expr, Ident):
        width = widths.get(expr.name, 1)
        return f"(|{expr.name})" if width > 1 else expr.name
    if isinstance(expr, IntLiteral):
        return "1'b1" if expr.value != 0 else "1'b0"
    raise TypeError(f"not a guard expression node: {expr!r}")


def render_guard(condition: Condition, widths: dict[str, int]) -> str:
    """Render a transition guard to width-correct SystemVerilog.

    ``widths`` maps signal names to declared bit widths (typically the
    machine's input ports). The guard is rendered in a boolean context so a
    multi-bit signal is reduced with ``|`` and comparison literals are sized to
    their signal operand's width, producing a guard that is genuinely
    ``verilator --lint-only -Wall`` clean.

    When the condition carries no typed tree (``condition.expr is None`` — e.g.
    a condition hand-built in a low-level unit test), the normalized
    ``condition.text`` is used verbatim as a fallback.

    Args:
        condition: The transition guard to render.
        widths: Signal-name → declared-width map for width-correct rendering.

    Returns:
        The SystemVerilog guard expression text (without the surrounding
        ``if (...)``).
    """
    if condition.expr is None:
        return condition.text
    return _render_bool(condition.expr, widths)


def _emit_state_arm(state: State, widths: dict[str, int]) -> list[str]:
    """Render the ``case`` arm for one ``state`` of the next-state block.

    The state's transitions are rendered in declared order (Req 8.5): each
    ``when`` guard becomes an ``if`` / ``else if`` clause that selects the first
    true guard's target, and the always-true ``else`` clause becomes the
    trailing ``else next_state = <target>;`` (Req 8.5). Each guard is rendered
    width-correctly via :func:`render_guard` (``widths`` maps signal names to
    declared widths). All assignments use the blocking ``=`` operator required
    inside ``always_comb`` (Req 11.3).

    Three shapes are produced:

    * with one or more ``when`` guards -> a ``begin ... end`` arm holding the
      ``if``/``else if`` chain and (if present) the trailing ``else``;
    * with only an ``else`` (no guards) -> a single ``next_state = <target>;``
      assignment with no ``begin``/``end`` wrapper;
    * with no transitions at all -> ``next_state = state;`` so the arm still
      defines a behavior (a validated machine always has a covering ``else``,
      so this is a defensive fallback).

    Args:
        state: The state whose ordered transitions are rendered.
        widths: Signal-name → declared-width map for width-correct guards.

    Returns:
        The arm's source lines, indented for placement inside ``case (state)``.
    """
    whens = [t for t in state.transitions if t.kind == "when"]
    else_targets = [t.target for t in state.transitions if t.kind == "else"]
    else_target = else_targets[0] if else_targets else None

    # No guards: emit the (always-true) else target directly, or hold state.
    if not whens:
        target = else_target if else_target is not None else "state"
        return [_indent(f"{state.name}: next_state = {target};", 3)]

    arm = [_indent(f"{state.name}: begin", 3)]
    for index, transition in enumerate(whens):
        keyword = "if" if index == 0 else "else if"
        guard = render_guard(transition.condition, widths)
        arm.append(
            _indent(
                f"{keyword} ({guard}) next_state = {transition.target};",
                4,
            )
        )
    if else_target is not None:
        arm.append(_indent(f"else next_state = {else_target};", 4))
    arm.append(_indent("end", 3))
    return arm


def emit_next_state_block(m: Machine) -> str:
    """Emit the ``always_comb`` next-state combinational block for ``m``.

    Produces, at one level of indentation inside the module body::

        always_comb begin
            next_state = state;
            case (state)
                S0: begin
                    if (cond1) next_state = T1;
                    else if (cond2) next_state = T2;
                    else next_state = ELSE_TARGET;
                end
                ...
                default: next_state = state;
            endcase
        end

    The block is a single ``always_comb`` (Req 11.1) that opens with the
    unconditional default ``next_state = state;`` so every path assigns the
    signal (Req 11.6, 12.1). The ``case (state)`` carries exactly one
    ``default:`` arm, which also holds state (Req 12.2). Each state arm selects
    the first true guard's target in declared order, with the ``else`` clause as
    the always-true default (Req 8.5). Only blocking ``=`` is used, as required
    inside a combinational block (Req 11.3).

    Args:
        m: A validated machine with at least one declared state.

    Returns:
        The next-state block as a single newline-joined string.
    """
    # Guards are rendered width-correctly against the declared signal widths
    # (input ports, plus outputs defensively) so a multi-bit signal in a
    # boolean/comparison context produces lint-clean SystemVerilog.
    widths = {
        port.name: port.type.width for port in (*m.inputs, *m.outputs)
    }
    lines = [
        _indent("always_comb begin", 1),
        _indent("next_state = state;", 2),
        _indent("case (state)", 2),
    ]
    for state in m.states:
        lines.extend(_emit_state_arm(state, widths))
    lines.append(_indent("default: next_state = state;", 3))
    lines.append(_indent("endcase", 2))
    lines.append(_indent("end", 1))
    return "\n".join(lines)


def _output_literal(port: Port, bits: int) -> str:
    """Render a width-sized decimal literal for ``port`` carrying ``bits``.

    The literal is ``W'dVALUE`` where ``W`` is the port's declared width
    (:attr:`PortType.width`), e.g. a 2-bit output assigned ``3`` becomes
    ``2'd3``. Sizing the literal to the port width keeps the emitted code
    lint-clean (no width-mismatch warnings).
    """
    return f"{port.type.width}'d{bits}"


def _emit_output_arm(state: State, outputs: tuple[Port, ...]) -> str:
    """Render the single-line ``case`` arm for one ``state`` of the output block.

    Every declared output is assigned in the arm (Req 12.1): the value comes
    from the state's :class:`OutputAssignment` for that output, sized to the
    output width via :func:`_output_literal`. A validated machine assigns every
    output in every state, but to keep the arm total even when called on
    un-validated input, any output the state does not assign falls back to the
    width-agnostic default ``'0``. Only blocking ``=`` is used (Req 11.3).

    Args:
        state: The state whose output assignments are rendered.
        outputs: The machine's declared output ports, in declared order.

    Returns:
        A single ``"<name>: begin ... end"`` source line, indented for
        placement inside ``case (state)``.
    """
    assigned = {oa.output_name: oa.value.bits for oa in state.outputs}
    parts = []
    for port in outputs:
        if port.name in assigned:
            parts.append(f"{port.name} = {_output_literal(port, assigned[port.name])};")
        else:
            parts.append(f"{port.name} = '0;")
    body = " ".join(parts)
    return _indent(f"{state.name}: begin {body} end", 3)


def emit_output_block(m: Machine) -> str:
    """Emit the ``always_comb`` Moore output combinational block for ``m``.

    Produces, at one level of indentation inside the module body::

        always_comb begin
            out0 = '0;
            out1 = '0;
            case (state)
                S0: begin out0 = 1'd1; out1 = 2'd3; end
                ...
                default: begin out0 = '0; out1 = '0; end
            endcase
        end

    The block is a single ``always_comb`` (Req 11.1) whose outputs are a
    function of ``state`` only (Moore). It opens with a defined default ``'0``
    for *every* declared output before the ``case`` so no path can leave an
    output unassigned (Req 11.6, 12.1). The ``case (state)`` carries exactly one
    ``default:`` arm, which also assigns *all* outputs to ``'0`` so the case is
    total (Req 12.2). Each state arm assigns every output to its width-sized
    value for that state. Only blocking ``=`` is used, as required inside a
    combinational block (Req 11.3).

    With no declared outputs, the block degenerates to an ``always_comb`` whose
    ``case`` arms have empty bodies; it remains a single well-formed block.

    Args:
        m: A validated machine with at least one declared state.

    Returns:
        The output block as a single newline-joined string.
    """
    outputs = m.outputs
    lines = [_indent("always_comb begin", 1)]
    # Defaults for every output, before any conditional (Req 11.6, 12.1).
    for port in outputs:
        lines.append(_indent(f"{port.name} = '0;", 2))
    lines.append(_indent("case (state)", 2))
    for state in m.states:
        lines.append(_emit_output_arm(state, outputs))
    # Single total default arm assigning all outputs to '0 (Req 12.2).
    default_body = " ".join(f"{port.name} = '0;" for port in outputs)
    lines.append(_indent(f"default: begin {default_body} end", 3))
    lines.append(_indent("endcase", 2))
    lines.append(_indent("end", 1))
    return "\n".join(lines)


def emit_sequential_block(m: Machine) -> str:
    """Emit the ``always_ff`` sequential state-register block for ``m``.

    Produces, at one level of indentation inside the module body::

        always_ff @(posedge clk) begin
            if (rst) state <= RESET_STATE;
            else     state <= next_state;
        end

    The sensitivity list is exactly ``@(posedge clk)`` — the register is purely
    synchronous, with no ``posedge rst`` / asynchronous term (Req 13.5). Reset
    is active-high (``if (rst)``) and loads the machine's ``reset_state`` into
    ``state``, taking precedence over the ``next_state`` update (Req 13.6). Only
    the non-blocking ``<=`` operator is used, as required inside a clocked
    block (Req 11.2, 11.4), and the reset logic is confined to this single
    block (Req 13.4). This is the only block in the module that loads the
    ``state`` register (Req 11.5).

    Args:
        m: A validated machine whose ``reset_state`` names a declared state.

    Returns:
        The sequential block as a single newline-joined string.
    """
    return "\n".join(
        (
            _indent("always_ff @(posedge clk) begin", 1),
            _indent(f"if (rst) state <= {m.reset_state};", 2),
            _indent("else     state <= next_state;", 2),
            _indent("end", 1),
        )
    )


def _port_decl(direction: str, port: Port) -> str:
    """Render one declared port as a SystemVerilog ``logic`` declaration.

    The direction keyword is padded so ``input`` and ``output`` align their
    ``logic`` columns (``"input  logic"`` / ``"output logic"``), matching the
    design's module-header layout. A scalar ``bit`` port (``high == low == 0``,
    width 1) is emitted with no range, e.g. ``input  logic a`` (Req 2.3); a
    vector ``bit[H:L]`` port is emitted with its declared range, e.g.
    ``output logic [7:0] q``, spanning ``high`` down to ``low`` (Req 2.4).

    Args:
        direction: ``"input"`` or ``"output"`` (the SystemVerilog keyword).
        port: The declared port whose type fixes the width rendering.

    Returns:
        The single declaration text, without indentation or trailing comma.
    """
    keyword = "input " if direction == "input" else "output"
    ptype = port.type
    # Scalar bit -> no range; vector bit[H:L] -> explicit [high:low] (Req 2.3/2.4).
    if ptype.high == 0 and ptype.low == 0:
        return f"{keyword} logic {port.name}"
    return f"{keyword} logic [{ptype.high}:{ptype.low}] {port.name}"


def _emit_module_header(m: Machine) -> str:
    """Emit the ``module NAME ( ... );`` header for machine ``m``.

    The port list always begins with the implicit ``clk`` and ``rst`` inputs
    (Req 3.4), which the author never declares, followed by every declared
    input then every declared output, each at its correct width (Req 2.3,
    2.4). Ports are comma-separated with no trailing comma after the last, so
    the list is valid SystemVerilog regardless of how many ports are declared.

    Args:
        m: A validated machine.

    Returns:
        The header lines (``module ... (`` through ``);``) joined by newlines.
    """
    decls = ["input  logic clk", "input  logic rst"]
    decls.extend(_port_decl("input", port) for port in m.inputs)
    decls.extend(_port_decl("output", port) for port in m.outputs)

    lines = [f"module {m.name} ("]
    for index, decl in enumerate(decls):
        comma = "," if index < len(decls) - 1 else ""
        lines.append(f"{_indent(decl)}{comma}")
    lines.append(");")
    return "\n".join(lines)


def _collect_full_reads(expr: Expr, names: set[str]) -> None:
    """Record signal names read at *full width* within a guard expression.

    A bare :class:`Ident` reads every bit of its signal (as does any signal
    operand of a comparison or boolean operator, which the tree represents as an
    ``Ident``). A :class:`BitSelect` reads only one bit, so it is **not** a
    full-width read and is intentionally ignored here. Integer literals carry no
    signal.
    """
    if isinstance(expr, Ident):
        names.add(expr.name)
    elif isinstance(expr, (And, Or, Compare)):
        _collect_full_reads(expr.left, names)
        _collect_full_reads(expr.right, names)
    elif isinstance(expr, Not):
        _collect_full_reads(expr.operand, names)
    # BitSelect / IntLiteral: no full-width signal read.


def _fully_read_input_names(m: Machine) -> set[str]:
    """Return the input names read at full width by at least one guard.

    Walks the typed guard tree (:attr:`Condition.expr`) collecting every signal
    referenced as a whole (an :class:`Ident`); a signal touched only by
    bit-selects is *not* fully read (some of its bits go unused). For conditions
    that carry no tree (``expr is None`` — only low-level, input-free unit-test
    conditions), a whole-word text scan is used as a conservative fallback.
    """
    full: set[str] = set()
    for state in m.states:
        for transition in state.transitions:
            if transition.kind != "when" or transition.condition is None:
                continue
            condition = transition.condition
            if condition.expr is not None:
                _collect_full_reads(condition.expr, full)
            else:  # fallback for tree-less conditions (no input ports in tests)
                for port in m.inputs:
                    if re.search(rf"\b{re.escape(port.name)}\b", condition.text):
                        full.add(port.name)
    return full


def unused_inputs(m: Machine) -> tuple[Port, ...]:
    """Return the declared input ports not read at full width by any guard.

    A correct Moore machine need not branch on every declared input, nor read
    every bit of one: the port list is frequently fixed by an external
    interface/testbench, and reserved/strobe signals (or vector inputs only a
    few bits of which matter) may legitimately go partly or wholly unread. Such
    inputs are **legal** -- they are never rejected.

    A port is "fully read" only when some guard references it as a whole signal
    (an :class:`~transpiler.ast.Ident`, e.g. ``f``, ``|f``, ``f == k``,
    ``f && ...``). Two cases are therefore returned for the lint waiver:

    * an input referenced by **no** guard at all, and
    * a multi-bit input referenced **only** through bit-selects (``f[i]``),
      whose remaining bits would otherwise trip Verilator's ``UNUSEDSIGNAL``
      under ``-Wall``.

    The Code_Generator reads the *whole* of each returned port in a targeted
    waiver (see :func:`emit_unused_input_waiver`), marking every bit used so the
    module is ``-Wall`` clean without suppressing the warning class.

    Args:
        m: The machine whose inputs are classified.

    Returns:
        The declared input ports not read at full width, in declared order;
        empty when every input is fully read (or none are declared).
    """
    fully_read = _fully_read_input_names(m)
    return tuple(port for port in m.inputs if port.name not in fully_read)


def emit_unused_input_waiver(m: Machine) -> str:
    """Emit a targeted Verilator ``UNUSEDSIGNAL`` waiver for unused inputs.

    For every declared input not referenced by any transition guard
    (:func:`unused_inputs`), this emits the canonical Verilator
    "intentionally unused" read idiom: a single ``wire`` whose name contains
    ``unused`` (so Verilator exempts it) and whose value reduces a concatenation
    that *reads* each otherwise-unused input::

        // unused inputs are legal; this read keeps the module -Wall clean
        wire _unused_ok = &{1'b0, c, sel};

    Because the wire reads every listed input, those ports are no longer
    "unused", so ``verilator --lint-only -Wall`` reports no ``UNUSEDSIGNAL``
    warning -- *without* dropping ``-Wall`` and *without* a blanket
    ``-Wno-UNUSEDSIGNAL``: the waiver targets only the genuinely-unused input
    ports and nothing else. The leading ``1'b0`` makes the concatenation
    well-formed even for a single input and keeps the reduction value benign.

    Returns the empty string when every declared input is used (or none are
    declared), so the waiver appears only when actually needed.

    Args:
        m: A validated machine.

    Returns:
        The waiver line(s) (comment + ``wire`` declaration) as a newline-joined
        string, or ``""`` when no input is unused.
    """
    unused = unused_inputs(m)
    if not unused:
        return ""
    terms = ", ".join(("1'b0", *(port.name for port in unused)))
    comment = (
        "// inputs not read at full width are legal (fixed interface / reserved "
        "/ partial-bit use);"
    )
    note = "// this intentional whole-signal read keeps lint -Wall clean (UNUSEDSIGNAL)."
    waiver = f"wire _unused_ok = &{{{terms}}};"
    return "\n".join((_indent(comment), _indent(note), _indent(waiver)))


def generate(m: Machine) -> str:
    """Assemble the full SystemVerilog module for machine ``m``.

    Precondition: ``check()`` returned ``[]`` for the program containing ``m``;
    :func:`generate` performs no safety validation of its own.

    Produces the complete module (design "Module Layout"): the
    ``module NAME ( ... );`` header listing the implicit ``clk``/``rst`` inputs
    plus every declared input and output at its correct width (Req 2.3, 2.4,
    3.4), then the state-type declarations, then exactly the three procedural
    blocks — the ``always_comb`` next-state block, the ``always_comb`` output
    block, and the ``always_ff @(posedge clk)`` sequential block (Req 11.1) —
    and finally ``endmodule``.

    Any declared input not referenced by a transition guard is legal and is
    *not* rejected; the generator emits a targeted ``UNUSEDSIGNAL`` waiver
    (:func:`emit_unused_input_waiver`) so the output stays lint-clean under
    ``verilator --lint-only -Wall``.

    Args:
        m: A validated machine with at least one declared state.

    Returns:
        The full module source as a single newline-terminated string.
    """
    waiver = emit_unused_input_waiver(m)
    sections = [
        _emit_module_header(m),
        emit_state_type(m),
        emit_next_state_block(m),
        emit_output_block(m),
        emit_sequential_block(m),
    ]
    # Targeted UNUSEDSIGNAL waiver for unused inputs, emitted only when needed
    # so a fully-used machine is byte-for-byte unchanged.
    if waiver:
        sections.append(waiver)
    sections.append("endmodule")
    return "\n".join(sections) + "\n"