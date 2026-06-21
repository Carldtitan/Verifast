"""Typed AST data model for the FSM_DSL transpiler.

This module defines the in-memory model the AST builder produces from a lark
parse tree and that the Safety_Checker and Code_Generator consume. Every node
is a frozen dataclass and every node carries a :class:`Loc` (re-exported from
:mod:`transpiler.errors`) so diagnostics can name the offending element and
point at its source location.

The shapes mirror the design's "Data Models" section exactly. Collections are
stored as tuples so every node is immutable and hashable. Structural
invariants that can be encoded in the types are enforced here in
``__post_init__``; the remaining *semantic* invariants (e.g. totality of
outputs, name resolution) are verified later by the Safety_Checker.

Re-exported here rather than redefined: ``Loc`` is the canonical
source-location type defined in :mod:`transpiler.errors`.
"""

from __future__ import annotations

from dataclasses import dataclass

from lark import Token, Transformer, v_args
from lark.exceptions import VisitError
from lark.tree import Meta

# Re-export the canonical Loc rather than defining a conflicting type. AST
# nodes attach this same Loc that CompileErrors carry.
from transpiler.errors import CompileError, Loc, TypeError_

__all__ = [
    "Loc",
    "PortType",
    "Port",
    "Value",
    "OutputAssignment",
    "Condition",
    "Transition",
    "State",
    "Machine",
    "Program",
    "build_ast",
    # Typed guard-expression tree (carried on Condition.expr).
    "Ident",
    "BitSelect",
    "IntLiteral",
    "Compare",
    "And",
    "Or",
    "Not",
    "Expr",
    "expr_to_text",
]

# The largest legal vector index (Req 2.2): indices live in 0..65535.
_MAX_INDEX = 65535

# Reserved port names that are supplied implicitly and may not be author-
# declared (Req 3.1-3.3). The comparison is case-sensitive and exact.
_RESERVED_PORT_NAMES = frozenset({"clk", "rst"})

# Allowed values for structural fields, encoded as module-level constants.
_PORT_DIRECTIONS = frozenset({"in", "out"})
_TRANSITION_KINDS = frozenset({"when", "else"})


@dataclass(frozen=True)
class PortType:
    """A port's bit type: scalar ``bit`` or vector ``bit[H:L]``.

    For a scalar ``bit``, ``high == low == 0`` (width 1). For a vector, the
    indices satisfy ``high >= low >= 0`` and the width is ``high - low + 1``
    (Req 2.2).
    """

    high: int
    low: int

    def __post_init__(self) -> None:
        if not isinstance(self.high, int) or not isinstance(self.low, int):
            raise TypeError("PortType indices must be integers")
        if self.low < 0:
            raise ValueError(f"PortType low index must be >= 0, got {self.low}")
        if self.high < self.low:
            raise ValueError(
                f"PortType requires high >= low, got high={self.high}, "
                f"low={self.low}"
            )

    @property
    def width(self) -> int:
        """The bit width of the port: ``high - low + 1`` (Req 2.2)."""
        return self.high - self.low + 1


@dataclass(frozen=True)
class Port:
    """A declared input or output port.

    ``direction`` is ``"in"`` or ``"out"``; ``type`` is the port's
    :class:`PortType`; ``name`` is the author-declared identifier.
    """

    direction: str
    type: PortType
    name: str
    loc: Loc

    def __post_init__(self) -> None:
        if self.direction not in _PORT_DIRECTIONS:
            raise ValueError(
                f"Port direction must be one of {sorted(_PORT_DIRECTIONS)}, "
                f"got {self.direction!r}"
            )


@dataclass(frozen=True)
class Value:
    """A non-negative integer literal assigned to an output in a state."""

    bits: int
    loc: Loc

    def __post_init__(self) -> None:
        if not isinstance(self.bits, int):
            raise TypeError("Value.bits must be an integer")
        if self.bits < 0:
            raise ValueError(f"Value.bits must be non-negative, got {self.bits}")


@dataclass(frozen=True)
class OutputAssignment:
    """An assignment ``output_name = value`` inside a state body."""

    output_name: str
    value: Value
    loc: Loc


# ---------------------------------------------------------------------------
# Typed guard-expression tree
# ---------------------------------------------------------------------------
#
# A ``when COND -> STATE`` guard is carried both as normalized source ``text``
# (for diagnostics and round-tripping) and as a small typed expression tree on
# :attr:`Condition.expr`. The tree lets the Code_Generator render width-correct
# SystemVerilog: a multi-bit signal used in a boolean context is reduced with
# ``|`` and a comparison literal is sized to its signal operand's width, so the
# generated guards are genuinely ``verilator --lint-only -Wall`` clean (no
# WIDTH/WIDTHTRUNC), without suppressing warnings.


@dataclass(frozen=True)
class Ident:
    """A reference to a declared signal (typically an input port) by name."""

    name: str
    loc: Loc


@dataclass(frozen=True)
class BitSelect:
    """A single-bit select ``name[index]`` (always 1 bit wide)."""

    name: str
    index: int
    loc: Loc


@dataclass(frozen=True)
class IntLiteral:
    """A non-negative integer literal appearing in a guard expression."""

    value: int
    loc: Loc


@dataclass(frozen=True)
class Compare:
    """A comparison ``left OP right`` with ``OP`` in == != < <= > >= (1-bit)."""

    op: str
    left: "Expr"
    right: "Expr"
    loc: Loc


@dataclass(frozen=True)
class And:
    """A short-circuit boolean conjunction ``left && right`` (1-bit)."""

    left: "Expr"
    right: "Expr"
    loc: Loc


@dataclass(frozen=True)
class Or:
    """A short-circuit boolean disjunction ``left || right`` (1-bit)."""

    left: "Expr"
    right: "Expr"
    loc: Loc


@dataclass(frozen=True)
class Not:
    """A boolean negation ``!operand`` (1-bit)."""

    operand: "Expr"
    loc: Loc


# The union of guard-expression node types.
Expr = Ident | BitSelect | IntLiteral | Compare | And | Or | Not


def expr_to_text(expr: Expr) -> str:
    """Render a guard expression to normalized FSM_DSL source text.

    The text mirrors the parser's normalization (compound expressions are
    parenthesized, names and integer literals are emitted verbatim) so it both
    reads cleanly in diagnostics and re-parses to an equivalent tree, preserving
    source round-tripping. It is **not** the width-correct SystemVerilog form;
    the Code_Generator renders that separately from the same tree.
    """
    if isinstance(expr, Ident):
        return expr.name
    if isinstance(expr, BitSelect):
        return f"{expr.name}[{expr.index}]"
    if isinstance(expr, IntLiteral):
        return str(expr.value)
    if isinstance(expr, Compare):
        return f"({expr_to_text(expr.left)} {expr.op} {expr_to_text(expr.right)})"
    if isinstance(expr, And):
        return f"({expr_to_text(expr.left)} && {expr_to_text(expr.right)})"
    if isinstance(expr, Or):
        return f"({expr_to_text(expr.left)} || {expr_to_text(expr.right)})"
    if isinstance(expr, Not):
        return f"(!{expr_to_text(expr.operand)})"
    raise TypeError(f"not a guard expression node: {expr!r}")


@dataclass(frozen=True)
class Condition:
    """A parsed guard expression for a ``when COND -> STATE`` transition.

    ``text`` is the normalized expression over input ports (used for
    diagnostics and source round-tripping). ``expr`` is the typed expression
    tree (:data:`Expr`) the Code_Generator renders width-correctly; it is
    ``None`` only for conditions constructed directly without a tree (e.g. in
    low-level unit tests), in which case the generator falls back to ``text``.
    """

    text: str
    loc: Loc
    expr: Expr | None = None


@dataclass(frozen=True)
class Transition:
    """A single transition clause within a state.

    ``kind`` is ``"when"`` or ``"else"``. ``condition`` is the guard for a
    ``when`` clause and is ``None`` if and only if ``kind == "else"``.
    ``target`` is the destination state name.
    """

    kind: str
    condition: Condition | None
    target: str
    loc: Loc

    def __post_init__(self) -> None:
        if self.kind not in _TRANSITION_KINDS:
            raise ValueError(
                f"Transition kind must be one of {sorted(_TRANSITION_KINDS)}, "
                f"got {self.kind!r}"
            )
        # condition is None iff kind == "else"
        if self.kind == "else" and self.condition is not None:
            raise ValueError("an 'else' transition must not carry a condition")
        if self.kind == "when" and self.condition is None:
            raise ValueError("a 'when' transition must carry a condition")


@dataclass(frozen=True)
class State:
    """A declared state: its output assignments and ordered transitions."""

    name: str
    outputs: tuple[OutputAssignment, ...]
    transitions: tuple[Transition, ...]
    loc: Loc


@dataclass(frozen=True)
class Machine:
    """A finite state machine declaration.

    ``inputs``/``outputs`` exclude the implicit ``clk``/``rst`` ports (Req 3.1).
    ``reset_state`` is the target of the ``reset = STATE`` declaration.
    """

    name: str
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    reset_state: str
    states: tuple[State, ...]
    loc: Loc


@dataclass(frozen=True)
class Program:
    """A whole compilation unit: the machines in one source file."""

    machines: tuple[Machine, ...]
    source_file: str


# ---------------------------------------------------------------------------
# AST builder: lark Transformer + build_ast entry point
# ---------------------------------------------------------------------------
#
# The transformer turns the lark parse tree (Req 15.5 grammar) into the typed
# model above, attaching a Loc to every node. It also performs the structural
# and type validation that must happen before the Safety_Checker runs:
#   * type tokens are exactly `bit` / `bit[H:L]` with 0 <= L <= H <= 65535
#     (Req 2.5, 2.6);
#   * exactly one machine per file (Req 1.2, 1.3);
#   * exactly one reset declaration per machine (Req 1.6, 1.7);
#   * `clk`/`rst` are not author-declared (Req 3.1, 3.2, 3.3);
#   * no duplicate state names within a machine (Req 1.8, 1.9).
# Each violation raises a located error (TypeError_ for type problems, a plain
# located CompileError for the structural ones) so no signal/module is emitted.


@dataclass(frozen=True)
class _ResetDecl:
    """Internal carrier for a parsed ``reset = STATE`` declaration.

    Not part of the public model: the machine builder folds it into
    :attr:`Machine.reset_state` after enforcing the one-reset rule.
    """

    state: str
    loc: Loc


def _tok_loc(token: Token, file: str) -> Loc:
    """Build a :class:`Loc` from a terminal token's 1-based position."""
    return Loc(
        file=file,
        line=getattr(token, "line", 1) or 1,
        column=getattr(token, "column", 1) or 1,
    )


@v_args(meta=True)
class _AstBuilder(Transformer):
    """Transform a lark parse tree into a :class:`Program`.

    Methods are named after grammar rules/aliases. With ``@v_args(meta=True)``
    each receives ``(meta, children)`` where ``meta`` carries the propagated
    source position and ``children`` are the already-transformed sub-results.
    Condition-expression rules return ``(text, loc)`` tuples so the guard text
    can be reconstructed bottom-up; structural rules return model nodes.
    """

    def __init__(self, source_file: str) -> None:
        super().__init__()
        self._file = source_file

    # ---- condition expression -> typed Expr node -------------------------
    def identifier(self, meta: Meta, children: list) -> Ident:
        name = children[0]
        return Ident(name=str(name), loc=_tok_loc(name, self._file))

    def literal(self, meta: Meta, children: list) -> IntLiteral:
        tok = children[0]
        return IntLiteral(value=int(tok), loc=_tok_loc(tok, self._file))

    def bit_select(self, meta: Meta, children: list) -> BitSelect:
        name, index = children
        return BitSelect(
            name=str(name), index=int(index), loc=_tok_loc(name, self._file)
        )

    def not_op(self, meta: Meta, children: list) -> Not:
        operand = children[0]
        return Not(operand=operand, loc=operand.loc)

    def compare(self, meta: Meta, children: list) -> Compare:
        left, op, right = children
        return Compare(op=str(op), left=left, right=right, loc=left.loc)

    def and_op(self, meta: Meta, children: list) -> And:
        left, right = children
        return And(left=left, right=right, loc=left.loc)

    def or_op(self, meta: Meta, children: list) -> Or:
        left, right = children
        return Or(left=left, right=right, loc=left.loc)

    # ---- port types ------------------------------------------------------
    def scalar_type(self, meta: Meta, children: list) -> PortType:
        name = children[0]
        if str(name) != "bit":
            raise TypeError_(
                _tok_loc(name, self._file),
                f"unrecognized type {str(name)!r}; expected 'bit' or 'bit[H:L]'",
            )
        return PortType(high=0, low=0)

    def vector_type(self, meta: Meta, children: list) -> PortType:
        name, high_tok, low_tok = children
        if str(name) != "bit":
            raise TypeError_(
                _tok_loc(name, self._file),
                f"unrecognized type {str(name)!r}; expected 'bit' or 'bit[H:L]'",
            )
        high = int(high_tok)
        low = int(low_tok)
        loc = _tok_loc(name, self._file)
        if high > _MAX_INDEX or low > _MAX_INDEX:
            raise TypeError_(
                loc,
                f"invalid index range bit[{high}:{low}]: indices must be in "
                f"0..{_MAX_INDEX}",
            )
        if high < low:
            raise TypeError_(
                loc,
                f"invalid index range bit[{high}:{low}]: requires H >= L",
            )
        return PortType(high=high, low=low)

    # ---- declarations ----------------------------------------------------
    def _port(self, direction: str, children: list) -> Port:
        port_type, name = children
        loc = _tok_loc(name, self._file)
        if str(name) in _RESERVED_PORT_NAMES:
            raise CompileError(
                loc,
                f"port name {str(name)!r} is reserved; clk and rst are implicit "
                f"and must not be declared",
            )
        return Port(direction=direction, type=port_type, name=str(name), loc=loc)

    def in_decl(self, meta: Meta, children: list) -> Port:
        return self._port("in", children)

    def out_decl(self, meta: Meta, children: list) -> Port:
        return self._port("out", children)

    def reset_decl(self, meta: Meta, children: list) -> _ResetDecl:
        name = children[0]
        return _ResetDecl(state=str(name), loc=_tok_loc(name, self._file))

    def output_assignment(self, meta: Meta, children: list) -> OutputAssignment:
        name, value_tok = children
        return OutputAssignment(
            output_name=str(name),
            value=Value(bits=int(value_tok), loc=_tok_loc(value_tok, self._file)),
            loc=_tok_loc(name, self._file),
        )

    def when_transition(self, meta: Meta, children: list) -> Transition:
        expr, target = children
        return Transition(
            kind="when",
            condition=Condition(
                text=expr_to_text(expr), loc=expr.loc, expr=expr
            ),
            target=str(target),
            loc=_tok_loc(target, self._file),
        )

    def else_transition(self, meta: Meta, children: list) -> Transition:
        target = children[0]
        return Transition(
            kind="else",
            condition=None,
            target=str(target),
            loc=_tok_loc(target, self._file),
        )

    # ---- wrapper rules (identity over their single child) ----------------
    def machine_item(self, meta: Meta, children: list):
        return children[0]

    def state_item(self, meta: Meta, children: list):
        return children[0]

    # ---- state -----------------------------------------------------------
    def state_decl(self, meta: Meta, children: list) -> State:
        name = children[0]
        outputs: list[OutputAssignment] = []
        transitions: list[Transition] = []
        for item in children[1:]:
            if isinstance(item, OutputAssignment):
                outputs.append(item)
            elif isinstance(item, Transition):
                transitions.append(item)
        return State(
            name=str(name),
            outputs=tuple(outputs),
            transitions=tuple(transitions),
            loc=_tok_loc(name, self._file),
        )

    # ---- machine ---------------------------------------------------------
    def machine(self, meta: Meta, children: list) -> Machine:
        name = children[0]
        machine_loc = _tok_loc(name, self._file)
        inputs: list[Port] = []
        outputs: list[Port] = []
        resets: list[_ResetDecl] = []
        states: list[State] = []
        seen_states: dict[str, State] = {}
        for item in children[1:]:
            if isinstance(item, Port):
                (inputs if item.direction == "in" else outputs).append(item)
            elif isinstance(item, _ResetDecl):
                resets.append(item)
            elif isinstance(item, State):
                if item.name in seen_states:
                    raise CompileError(
                        item.loc,
                        f"duplicate state {item.name!r} in machine {str(name)!r}",
                    )
                seen_states[item.name] = item
                states.append(item)

        if not resets:
            raise CompileError(
                machine_loc,
                f"machine {str(name)!r} has no reset declaration; exactly one "
                f"'reset = STATE' is required",
            )
        if len(resets) > 1:
            raise CompileError(
                resets[1].loc,
                f"machine {str(name)!r} has {len(resets)} reset declarations; "
                f"exactly one 'reset = STATE' is required",
            )

        machine_obj = Machine(
            name=str(name),
            inputs=tuple(inputs),
            outputs=tuple(outputs),
            reset_state=resets[0].state,
            states=tuple(states),
            loc=machine_loc,
        )
        _validate_guard_literals(machine_obj)
        return machine_obj

    # ---- top level -------------------------------------------------------
    def start(self, meta: Meta, children: list) -> Program:
        machines = [c for c in children if isinstance(c, Machine)]
        if not machines:
            raise CompileError(
                Loc(file=self._file, line=1, column=1),
                "source file declares no machine; exactly one machine per file "
                "is required",
            )
        if len(machines) > 1:
            raise CompileError(
                machines[1].loc,
                f"source file declares {len(machines)} machines; exactly one "
                f"machine per file is required",
            )
        return Program(machines=tuple(machines), source_file=self._file)


def _iter_compares(expr: Expr):
    """Yield every :class:`Compare` node within a guard expression tree."""
    if isinstance(expr, Compare):
        yield expr
        yield from _iter_compares(expr.left)
        yield from _iter_compares(expr.right)
    elif isinstance(expr, (And, Or)):
        yield from _iter_compares(expr.left)
        yield from _iter_compares(expr.right)
    elif isinstance(expr, Not):
        yield from _iter_compares(expr.operand)
    # Ident / BitSelect / IntLiteral carry no nested comparison.


def _validate_guard_literals(machine: Machine) -> None:
    """Reject a comparison whose literal cannot fit its signal operand's width.

    A ``signal OP literal`` comparison must size the literal to the signal's
    declared width for the generated SystemVerilog to be width-correct (so the
    Code_Generator emits e.g. ``f == 3'd5``). If the literal does not fit that
    width (e.g. ``f == 9`` with ``f`` 2 bits), sizing it would silently truncate
    the value, so the program is rejected with a located diagnostic naming the
    offending value and width — consistent with the project's width-aware
    handling elsewhere. Comparisons whose signal operand is not a declared port
    are left to other checks (no width is known) and are not flagged here.

    Raises:
        TypeError_: For a comparison literal that exceeds its signal operand's
            declared bit width.
    """
    widths = {
        port.name: port.type.width
        for port in (*machine.inputs, *machine.outputs)
    }
    for state in machine.states:
        for transition in state.transitions:
            condition = transition.condition
            if condition is None or condition.expr is None:
                continue
            for cmp in _iter_compares(condition.expr):
                signal: tuple[str, int] | None = None
                literal: IntLiteral | None = None
                for side in (cmp.left, cmp.right):
                    if isinstance(side, Ident) and side.name in widths:
                        signal = (side.name, widths[side.name])
                    elif isinstance(side, BitSelect):
                        signal = (side.name, 1)
                    elif isinstance(side, IntLiteral):
                        literal = side
                if signal is None or literal is None:
                    continue
                name, width = signal
                if literal.value >= (1 << width):
                    raise TypeError_(
                        literal.loc,
                        f"comparison literal {literal.value} does not fit the "
                        f"{width}-bit width of signal '{name}'",
                    )


def build_ast(tree, source_file: str = "<input>") -> Program:
    """Transform a lark parse ``tree`` into a validated :class:`Program`.

    Attaches a :class:`Loc` to every node and enforces the structural and type
    rules that precede the Safety_Checker (Req 1.2-1.9, 2.5, 2.6, 3.2, 3.3).

    Args:
        tree: The lark parse tree produced by :func:`transpiler.parser.parse`.
        source_file: Name used in every node's :class:`Loc` and in diagnostics.

    Returns:
        The typed :class:`Program` model.

    Raises:
        TypeError_: For an invalid or unrecognized port type.
        CompileError: For a structural violation (machine count, reset count,
            reserved port name, or duplicate state name).
    """
    try:
        return _AstBuilder(source_file).transform(tree)
    except VisitError as exc:
        # lark wraps exceptions raised inside transformer methods; surface the
        # original located CompileError/TypeError_ unchanged.
        if isinstance(exc.orig_exc, CompileError):
            raise exc.orig_exc from None
        raise