"""Compile-error hierarchy and source locations for the FSM_DSL transpiler.

Every diagnostic produced by any pipeline stage (parser, AST builder,
Safety_Checker) is a :class:`CompileError`. Each error carries a :class:`Loc`
so messages can name the offending element and point at its source location.

``Loc`` is defined here as the canonical source-location type; ``ast.py``
re-exports it for use on AST nodes.

The rendered form is always ``FILE:LINE:COL: <message>`` (Req 16.2, 16.4).
Only the CLI writes these to ``sys.stderr``; lower stages raise or return them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Loc",
    "CompileError",
    "ParseError",
    "TypeError_",
    "SafetyError",
    "SAFETY_RULES",
]

# The closed set of safety-rule identifiers (Req 16.2). A SafetyError must name
# exactly one of these so diagnostics can be attributed to a specific rule.
SAFETY_RULES: frozenset[str] = frozenset(
    {
        "total_outputs",
        "total_transitions",
        "single_driver",
        "name_resolution",
    }
)


@dataclass(frozen=True)
class Loc:
    """A source location: the file, 1-based line, and 1-based column.

    This is the canonical location type for the whole transpiler. AST nodes
    attach a ``Loc`` for error reporting, and every :class:`CompileError`
    carries one so it can render ``FILE:LINE:COL: <message>``.
    """

    file: str
    line: int
    column: int


class CompileError(Exception):
    """Base class for every compile-time error.

    Carries the offending :class:`Loc` and a human-readable message. The
    :meth:`render` method produces the canonical ``FILE:LINE:COL: <message>``
    form used on the standard error stream (Req 16.2, 16.4).
    """

    loc: Loc
    message: str

    def __init__(self, loc: Loc, message: str) -> None:
        self.loc = loc
        self.message = message
        super().__init__(self.render())

    def render(self) -> str:
        """Return the diagnostic as ``FILE:LINE:COL: <message>``."""
        return f"{self.loc.file}:{self.loc.line}:{self.loc.column}: {self.message}"

    def __str__(self) -> str:  # pragma: no cover - thin delegation
        return self.render()


class ParseError(CompileError):
    """Raised when the source text cannot be parsed as FSM_DSL.

    The grammar reports the failing line (and column when available); the
    diagnostic must identify the line number of the failure (Req 15.8, 16.4).
    """

    def __init__(
        self,
        line: int,
        column: int,
        message: str,
        file: str = "<input>",
    ) -> None:
        super().__init__(Loc(file=file, line=line, column=column), message)


class TypeError_(CompileError):
    """Raised for an invalid or unknown port type (Req 2.5, 2.6).

    Named with a trailing underscore so it never shadows the built-in
    ``TypeError``.
    """


class SafetyError(CompileError):
    """A violation of one of the four compile-time safety rules.

    ``rule`` names which check produced the diagnostic and must be one of
    :data:`SAFETY_RULES`:
    ``total_outputs`` | ``total_transitions`` | ``single_driver`` |
    ``name_resolution``.
    """

    rule: str

    def __init__(self, rule: str, loc: Loc, message: str) -> None:
        if rule not in SAFETY_RULES:
            raise ValueError(
                f"unknown safety rule {rule!r}; expected one of "
                f"{sorted(SAFETY_RULES)}"
            )
        self.rule = rule
        super().__init__(loc, message)
