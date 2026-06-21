"""CLI entry point for the FSM_DSL transpiler.

Invoked as ``python -m transpiler.transpile INPUT.fsm`` (Req 15.3). This module
is the thin shell that wires the pipeline together:

    parse -> build_ast -> check -> generate

and is the *only* component permitted to touch ``sys.stdout``, ``sys.stderr``,
and process exit codes. Every lower stage communicates purely through return
values and raised :class:`~transpiler.errors.CompileError` instances.

Exit-code / stream contract (design "Error Handling" table):

* arity != 1            -> usage to stderr, empty stdout, return 2   (Req 15.6)
* file unreadable       -> file error to stderr, empty stdout, ret 1 (Req 15.7)
* parse failure         -> parse error+line to stderr, ret 1         (Req 15.8, 16.4)
* bad type / structure  -> error to stderr, empty stdout, ret 1      (Req 2.5, 2.6)
* safety violations     -> every diagnostic to stderr, ret 1         (Req 16.1-16.3)
* success               -> SystemVerilog to stdout, return 0         (Req 15.4, 16.5)

No partial output is ever emitted: the generated SystemVerilog is buffered in a
local variable and flushed to ``sys.stdout`` only after a fully successful run,
so any error path leaves stdout empty (Req 16.3).
"""

from __future__ import annotations

import sys

from transpiler.ast import build_ast
from transpiler.codegen import generate
from transpiler.errors import CompileError
from transpiler.parser import parse
from transpiler.safety import check

__all__ = ["main"]

_USAGE = "usage: python -m transpiler.transpile INPUT.fsm: exactly one input file required"


def main(argv: list[str]) -> int:
    """Run the transpiler pipeline and return the process exit code.

    Args:
        argv: The command-line arguments *without* the program name (i.e. like
            ``sys.argv[1:]``). Exactly one positional argument naming the input
            ``.fsm`` file is required.

    Returns:
        ``0`` on success (SystemVerilog written to stdout), ``2`` on argument
        arity errors, and ``1`` on any other failure (file, parse, type,
        structural, or safety). On any non-zero return nothing is written to
        stdout.
    """
    # (Req 15.6) Exactly one positional argument is required.
    if len(argv) != 1:
        print(_USAGE, file=sys.stderr)
        return 2

    path = argv[0]

    # (Req 15.7) Read the input file; a missing/unreadable file is a clean
    # error with no stdout.
    try:
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
    except OSError as exc:
        print(f"error: cannot read input file '{path}': {exc.strerror or exc}", file=sys.stderr)
        return 1

    # (Req 15.8, 16.4, 2.5, 2.6) Parse and build the typed model. Both stages
    # raise located CompileErrors; render them to stderr and write no stdout.
    try:
        tree = parse(source, file=path)
        program = build_ast(tree, source_file=path)
    except CompileError as err:
        print(err.render(), file=sys.stderr)
        return 1

    # (Req 16.1-16.3) Run all four safety checks to completion. Any violation
    # means we emit every diagnostic and write nothing to stdout.
    errors = check(program)
    if errors:
        for err in errors:
            print(err.render(), file=sys.stderr)
        return 1

    # (Req 15.4, 16.5) Success: build_ast guarantees exactly one machine.
    # Buffer the generated SystemVerilog locally and flush to stdout only now,
    # so no partial output is ever emitted (Req 16.3).
    output = generate(program.machines[0])
    sys.stdout.write(output)
    return 0


def _console_main() -> None:
    """Console-script entry point: ``fsm-transpile`` (see pyproject)."""
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    _console_main()
