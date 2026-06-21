"""FSM_DSL parse loader.

Loads ``grammar.lark`` (the FSM_DSL v0.1 grammar, Req 15.5) and exposes a
single :func:`parse` entry point that turns source text into a lark parse tree.

The grammar is loaded in ``lalr`` mode with the ``basic`` (non-contextual)
lexer so the seven keywords are reserved globally and parsing is unambiguous
(Req 5.2). Any grammar failure is converted into a located
:class:`~transpiler.errors.ParseError` carrying the failing line and column
(Req 4.3, 15.8, 16.4); the parse tree is returned on success.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

from lark import Lark
from lark.exceptions import UnexpectedCharacters, UnexpectedInput, UnexpectedToken

from .errors import ParseError

__all__ = ["parse", "ParseTree", "get_parser"]

# The return type of :func:`parse` is lark's parse tree. We expose a public
# alias matching the name the design uses ("ParseTree") without depending on a
# specific lark internal class object at import time.
from lark import Tree as ParseTree  # noqa: E402  (re-export under design name)


@lru_cache(maxsize=1)
def get_parser() -> Lark:
    """Build (once) and return the FSM_DSL lark parser.

    The grammar text is loaded from the packaged ``grammar.lark`` resource so
    the loader works regardless of the current working directory or whether the
    package is installed or run from a source checkout.
    """
    grammar_text = (
        resources.files("transpiler").joinpath("grammar.lark").read_text(encoding="utf-8")
    )
    return Lark(
        grammar_text,
        parser="lalr",
        lexer="basic",
        start="start",
        propagate_positions=True,
    )


def parse(source: str, file: str = "<input>") -> ParseTree:
    """Parse FSM_DSL ``source`` into a lark parse tree.

    Args:
        source: The FSM_DSL program text.
        file: Name used in diagnostics (flows into :class:`ParseError`).

    Returns:
        The lark parse tree for the program.

    Raises:
        ParseError: If the source does not parse against the FSM_DSL grammar.
            The error carries the 1-based line and column of the failure
            (Req 15.8, 16.4).
    """
    parser = get_parser()
    try:
        return parser.parse(source)
    except (UnexpectedToken, UnexpectedCharacters) as exc:
        # Both carry 1-based ``line``/``column`` attributes pointing at the
        # offending token or character.
        raise ParseError(
            line=getattr(exc, "line", 1) or 1,
            column=getattr(exc, "column", 1) or 1,
            message=_describe(exc),
            file=file,
        ) from exc
    except UnexpectedInput as exc:
        # Any other lark input failure (e.g. unexpected EOF) still exposes a
        # line/column via the common base class.
        raise ParseError(
            line=getattr(exc, "line", 1) or 1,
            column=getattr(exc, "column", 1) or 1,
            message=_describe(exc),
            file=file,
        ) from exc


def _describe(exc: UnexpectedInput) -> str:
    """Produce a concise, single-line parse-error message from a lark error."""
    if isinstance(exc, UnexpectedToken):
        token = getattr(exc, "token", None)
        token_text = repr(str(token)) if token is not None else "<unknown>"
        expected = getattr(exc, "expected", None)
        if expected:
            return (
                f"parse error: unexpected token {token_text}, "
                f"expected one of {sorted(expected)}"
            )
        return f"parse error: unexpected token {token_text}"
    if isinstance(exc, UnexpectedCharacters):
        char = getattr(exc, "char", None)
        if char is not None:
            return f"parse error: unexpected character {char!r}"
        return "parse error: unexpected character"
    return "parse error: unexpected input"
