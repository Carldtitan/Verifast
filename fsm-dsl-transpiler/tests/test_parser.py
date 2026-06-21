"""Unit tests for the FSM_DSL parse loader (``transpiler.parser``).

Covers basic parse success (a well-formed program yields a parse tree) and
parse failure (a malformed program raises ``ParseError`` carrying a line
number). See task 2.2 / Requirements 4.3, 5.2, 15.8.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import assume, given, settings
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
    Program,
    State,
    Transition,
    Value,
    build_ast,
)
from transpiler.errors import ParseError
from transpiler.parser import ParseTree, get_parser, parse
from tests.strategies import (
    assert_valid_program_invariants,
    render_program,
    valid_program,
)

# A minimal but complete, well-formed FSM_DSL program exercising all seven
# constructs: machine, in, out, reset, state, output assignment, transition.
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


def test_parse_returns_a_tree() -> None:
    tree = parse(VALID_PROGRAM)
    assert isinstance(tree, ParseTree)
    # The top rule is `start`; it should contain exactly one machine.
    assert tree.data == "start"
    machines = [c for c in tree.children if getattr(c, "data", None) == "machine"]
    assert len(machines) == 1


def test_parse_accepts_vector_types_and_comparisons() -> None:
    program = """\
machine counter {
    in bit[1:0] sel
    out bit[3:0] q
    reset = S0
    state S0 {
        q = 0
        when sel == 1 -> S0
        else -> S0
    }
}
"""
    tree = parse(program)
    assert isinstance(tree, ParseTree)


def test_parse_accepts_empty_source() -> None:
    # Zero machines is admitted syntactically (the AST builder enforces the
    # "exactly one machine" rule), so an empty program still parses.
    tree = parse("")
    assert isinstance(tree, ParseTree)
    assert tree.data == "start"


def test_get_parser_is_cached() -> None:
    assert get_parser() is get_parser()


def test_malformed_program_raises_parse_error_with_line() -> None:
    # Missing the closing brace and a transition target: a clear grammar error.
    malformed = """\
machine broken {
    in bit go
    out bit led
    reset = S0
    state S0 {
        led = 0
        when go ->
    }
}
"""
    with pytest.raises(ParseError) as excinfo:
        parse(malformed)
    err = excinfo.value
    # The diagnostic must carry the failure line number (Req 15.8, 16.4).
    assert err.loc.line >= 1
    assert err.loc.column >= 1
    assert "parse error" in err.message


def test_unexpected_keyword_case_is_rejected() -> None:
    # Keywords are case-sensitive: `Machine` is not the keyword `machine`.
    with pytest.raises(ParseError):
        parse("Machine foo { }")


def test_parse_error_reports_correct_line() -> None:
    # The stray token sits on line 3; the reported line should point at it.
    src = "machine m {\n    in bit go\n    @@@\n}\n"
    with pytest.raises(ParseError) as excinfo:
        parse(src)
    assert excinfo.value.loc.line == 3


def test_parse_error_carries_file_name() -> None:
    with pytest.raises(ParseError) as excinfo:
        parse("@@@", file="prog.fsm")
    assert excinfo.value.loc.file == "prog.fsm"


# ---------------------------------------------------------------------------
# Property-based test
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 1: Parse round-trip is identity
#
# Validates: Requirements 5.2
#
# The grammar admits exactly one parse per program, so building an AST,
# pretty-printing it back to FSM_DSL source, and parsing the result yields an
# AST equivalent to the original. We compare the AST obtained from the rendered
# model (``ast_a``) against the AST obtained by rendering and re-parsing that
# AST (``ast_b``): because the renderer is canonical and the parser is
# unambiguous, the second round-trip is the identity on structure.
#
# Comparison is on normalized structure (machine name, ports, states,
# transitions, output assignments, reset). Source positions (``Loc``)
# legitimately shift between renders -- e.g. the AST builder normalizes a guard
# such as ``sel == 1`` to the parenthesized form ``(sel == 1)``, moving later
# columns -- so locations are canonicalized away before the structural
# comparison.

# A single canonical location used to erase source-position differences so the
# comparison is purely structural.
_CANON_LOC = Loc(file="<canon>", line=0, column=0)


def _canon_value(v: Value) -> Value:
    return replace(v, loc=_CANON_LOC)


def _canon_assignment(a: OutputAssignment) -> OutputAssignment:
    return replace(a, value=_canon_value(a.value), loc=_CANON_LOC)


def _canon_expr(e):
    """Recursively replace every ``Loc`` in a guard expression tree.

    ``Condition.expr`` nodes carry source positions that shift when comments are
    added or the layout changes, so they must be canonicalized alongside the
    rest of the tree before a structural equality comparison.
    """
    if e is None:
        return None
    if isinstance(e, (Ident, IntLiteral, BitSelect)):
        return replace(e, loc=_CANON_LOC)
    if isinstance(e, Not):
        return replace(e, operand=_canon_expr(e.operand), loc=_CANON_LOC)
    if isinstance(e, (And, Or, Compare)):
        return replace(
            e, left=_canon_expr(e.left), right=_canon_expr(e.right), loc=_CANON_LOC
        )
    raise TypeError(f"not a guard expression node: {e!r}")


def _canon_condition(c: Condition | None) -> Condition | None:
    if c is None:
        return None
    return replace(c, loc=_CANON_LOC, expr=_canon_expr(c.expr))


def _canon_transition(t: Transition) -> Transition:
    return replace(t, condition=_canon_condition(t.condition), loc=_CANON_LOC)


def _canon_port(p: Port) -> Port:
    # PortType carries no Loc; only the Port node does.
    return replace(p, loc=_CANON_LOC)


def _canon_state(s: State) -> State:
    return replace(
        s,
        outputs=tuple(_canon_assignment(a) for a in s.outputs),
        transitions=tuple(_canon_transition(t) for t in s.transitions),
        loc=_CANON_LOC,
    )


def _canon_machine(m: Machine) -> Machine:
    return replace(
        m,
        inputs=tuple(_canon_port(p) for p in m.inputs),
        outputs=tuple(_canon_port(p) for p in m.outputs),
        states=tuple(_canon_state(s) for s in m.states),
        loc=_CANON_LOC,
    )


def _canon_program(p: Program) -> Program:
    """Return ``p`` with every node's ``Loc`` replaced by a canonical value."""
    return replace(p, machines=tuple(_canon_machine(m) for m in p.machines))


@settings(max_examples=200, deadline=None)
@given(valid_program())
def test_parse_round_trip_is_identity(program: Program) -> None:
    # The strategy must hand us a structurally valid program.
    assert_valid_program_invariants(program)

    # Render the model, parse + build the AST: this is the canonical AST.
    source_a = render_program(program)
    ast_a = build_ast(parse(source_a, file="<input>"), source_file="<input>")

    # Re-render that AST and parse + build again. The renderer is canonical and
    # the grammar admits exactly one parse, so this round-trip is the identity.
    source_b = render_program(ast_a)
    ast_b = build_ast(parse(source_b, file="<input>"), source_file="<input>")

    # Equivalent ASTs: identical structure once source positions are erased.
    assert _canon_program(ast_a) == _canon_program(ast_b)


# ---------------------------------------------------------------------------
# Property-based test
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 2: Comments do not affect tokenization
#
# Validates: Requirements 4.1, 4.2, 4.3
#
# For any valid FSM_DSL source, the token stream (and resulting AST) produced
# from the source is identical to the token stream produced from the same
# source with all `#`-to-end-of-line comments removed. We exercise this by
# decorating a rendered valid program with comments -- both inline (` # ...`
# appended to the end of a line) and standalone (`# ...` on their own line) --
# and asserting the AST is unchanged, up to `Loc` canonicalization (comments
# legitimately shift line/column positions).
#
# FSM_DSL v0.1 has no quoted/string tokens, so the "a `#` inside a quoted token
# remains a literal character" sub-clause of Req 4.2 is vacuous: there is no
# context in which `#` is anything other than a comment introducer, so it is
# not separately exercised here.

# Comment bodies are printable ASCII (codepoints 32..126), a range that already
# excludes the newline (10) and carriage-return (13) characters -- a comment
# must not contain a line break, since it runs only to the end of its line.
_comment_text = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    max_size=24,
)


def _strip_comments(source: str) -> str:
    """Remove every ``#``-to-end-of-line comment from ``source``.

    FSM_DSL has no quoted tokens, so the first ``#`` on any line always begins
    a comment and everything from it to the end of the line is dropped.
    """
    stripped_lines = []
    for line in source.split("\n"):
        hash_index = line.find("#")
        if hash_index != -1:
            line = line[:hash_index]
        stripped_lines.append(line)
    return "\n".join(stripped_lines)


@st.composite
def _commented_program(
    draw: st.DrawFn,
) -> tuple[Program, str, str]:
    """Draw a valid program plus an annotated copy of its rendered source.

    Returns ``(program, original_source, commented_source)`` where
    ``commented_source`` is ``original_source`` decorated with a mix of inline
    and standalone ``#`` comments at randomly chosen positions.
    """
    program = draw(valid_program())
    original = render_program(program)

    new_lines: list[str] = []
    for line in original.split("\n"):
        # Optionally insert a standalone comment line before this line.
        if draw(st.booleans()):
            new_lines.append("#" + draw(_comment_text))
        # Optionally append an inline comment to the end of this line.
        if draw(st.booleans()):
            new_lines.append(line + " #" + draw(_comment_text))
        else:
            new_lines.append(line)
    # Optionally append a trailing standalone comment line.
    if draw(st.booleans()):
        new_lines.append("#" + draw(_comment_text))

    commented = "\n".join(new_lines)
    return program, original, commented


@settings(max_examples=150, deadline=None)
@given(_commented_program())
def test_comments_do_not_affect_tokenization(
    data: tuple[Program, str, str],
) -> None:
    _program, original, commented = data

    ast_original = build_ast(parse(original, file="<input>"), source_file="<input>")
    ast_commented = build_ast(parse(commented, file="<input>"), source_file="<input>")

    # Adding comments does not change the resulting AST (Req 4.1, 4.3).
    assert _canon_program(ast_commented) == _canon_program(ast_original)

    # Mechanically removing the comments recovers the original token stream and
    # therefore the original AST (Req 4.2, 4.3).
    stripped = _strip_comments(commented)
    ast_stripped = build_ast(parse(stripped, file="<input>"), source_file="<input>")
    assert _canon_program(ast_stripped) == _canon_program(ast_original)


# ---------------------------------------------------------------------------
# Property-based test
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 3: Keywords are case-sensitive
#
# Validates: Requirements 4.4, 4.5
#
# The closed keyword set {machine, in, out, reset, state, when, else} is
# matched case-sensitively (Req 4.4). A token whose spelling matches a keyword
# but differs in letter case is NOT that keyword (Req 4.5): it lexes as a
# generic NAME and therefore fails to parse when it appears in a position where
# the grammar requires the keyword.
#
# We use a minimal program template containing EXACTLY ONE occurrence of each
# of the seven keywords, each in its own substitution slot. For a randomly
# chosen keyword, Hypothesis produces a case-variant that differs from the
# canonical lowercase spelling in at least one letter; that variant is injected
# into the keyword's slot (every other slot keeps its canonical keyword) and we
# assert that parsing the mutated source raises ``ParseError``.

# The seven reserved keywords (Req 4.4). All are pure ASCII letters, so any
# variant containing at least one uppercased character differs from the
# original spelling.
_KEYWORDS: tuple[str, ...] = (
    "machine",
    "in",
    "out",
    "reset",
    "state",
    "when",
    "else",
)

# A minimal, well-formed program with exactly one occurrence of each keyword,
# rendered from per-keyword substitution slots. Doubled braces are literal `{`
# / `}` for str.format; the named fields are the keyword spellings themselves.
_KEYWORD_TEMPLATE = (
    "{machine} m {{ "
    "{in} bit go "
    "{out} bit y "
    "{reset} = S0 "
    "{state} S0 {{ "
    "y = 0 "
    "{when} go -> S0 "
    "{else} -> S0 "
    "}} }}"
)


def _render_with_slot(mutated_keyword: str, replacement: str) -> str:
    """Render the template, substituting one keyword slot with ``replacement``.

    Every slot defaults to its canonical keyword spelling; only the slot for
    ``mutated_keyword`` receives ``replacement``.
    """
    slots = {kw: kw for kw in _KEYWORDS}
    slots[mutated_keyword] = replacement
    return _KEYWORD_TEMPLATE.format(**slots)


@st.composite
def _keyword_case_variant(draw: st.DrawFn) -> tuple[str, str]:
    """Pick a keyword and a case-variant that differs in >= 1 letter.

    Returns ``(keyword, variant)`` where ``variant`` has the same letters as
    ``keyword`` but at least one character upper-cased, so ``variant`` is never
    equal to the canonical lowercase spelling and is never another keyword.
    """
    keyword = draw(st.sampled_from(_KEYWORDS))
    # One flip flag per character; require at least one True so the result is
    # guaranteed to differ from the all-lowercase keyword.
    flips = draw(
        st.lists(
            st.booleans(),
            min_size=len(keyword),
            max_size=len(keyword),
        ).filter(any)
    )
    variant = "".join(c.upper() if f else c for c, f in zip(keyword, flips))
    assume(variant != keyword)
    return keyword, variant


def test_keyword_template_parses_when_unmutated() -> None:
    # Sanity check: with every slot at its canonical spelling, the template is
    # a well-formed program. This guarantees the property test below isolates
    # the effect of the case mutation rather than a malformed template.
    source = _KEYWORD_TEMPLATE.format(**{kw: kw for kw in _KEYWORDS})
    tree = parse(source)
    assert isinstance(tree, ParseTree)


@settings(max_examples=200, deadline=None)
@given(_keyword_case_variant())
def test_keywords_are_case_sensitive(data: tuple[str, str]) -> None:
    keyword, variant = data
    # The variant matches the keyword spelling but differs in letter case, so
    # it must not be treated as the keyword: parsing fails (Req 4.4, 4.5).
    source = _render_with_slot(keyword, variant)
    with pytest.raises(ParseError):
        parse(source)
