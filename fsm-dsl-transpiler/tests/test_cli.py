"""Unit tests for the CLI entry point (task 8.1).

Covers :func:`transpiler.transpile.main` and its stdout/stderr/exit-code
contract (design "Error Handling" table):

* success path: a valid program writes a module to stdout and exits 0
  (Req 15.4, 16.5);
* argument arity: zero or two args -> usage to stderr, empty stdout, exit 2
  (Req 15.6);
* unreadable file -> file error to stderr, empty stdout, exit 1 (Req 15.7);
* safety violation -> rule-named error to stderr, empty stdout, exit 1
  (Req 16.2, 16.3);
* parse failure -> error with a line number to stderr, empty stdout, exit 1
  (Req 15.8, 16.4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from transpiler.transpile import main

# A complete, safe FSM_DSL program: every output assigned in every state, every
# state ends in `else`, all targets and the reset target resolve.
_VALID = """\
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

# Parses fine but violates total-outputs: state S1 never assigns `y`.
_SAFETY_VIOLATION = """\
machine bad {
    in bit a
    out bit y
    reset = S0

    state S0 {
        y = 0
        else -> S1
    }
    state S1 {
        else -> S0
    }
}
"""

# A grammatically broken program (missing the machine body braces / bad token).
_PARSE_ERROR = """\
machine oops {
    in bit a
    out bit y
    reset = S0
    state S0 {
        y = 0
        when a ?? S0
        else -> S0
    }
}
"""


def _write(tmp_path: Path, name: str, content: str) -> str:
    """Write ``content`` to ``tmp_path/name`` and return its path string."""
    file = tmp_path / name
    file.write_text(content, encoding="utf-8")
    return str(file)


def test_success_writes_module_to_stdout_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "seq3.fsm", _VALID)

    code = main([path])

    captured = capsys.readouterr()
    assert code == 0
    assert "module seq3 (" in captured.out
    assert captured.out.rstrip().endswith("endmodule")
    # A clean run writes nothing to stderr.
    assert captured.err == ""


def test_zero_args_is_usage_error_with_empty_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main([])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "exactly one input file required" in captured.err


def test_two_args_is_usage_error_with_empty_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _write(tmp_path, "a.fsm", _VALID)
    b = _write(tmp_path, "b.fsm", _VALID)

    code = main([a, b])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "exactly one input file required" in captured.err


def test_missing_file_exits_one_with_empty_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = str(tmp_path / "does_not_exist.fsm")

    code = main([missing])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "cannot read input file" in captured.err


def test_safety_violation_exits_one_with_rule_named_error_and_empty_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "bad.fsm", _SAFETY_VIOLATION)

    code = main([path])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    # The diagnostic names the offending state and unassigned output (Req 16.2).
    assert "does not assign output 'y'" in captured.err
    assert "state S1" in captured.err


def test_parse_error_exits_one_with_line_number_and_empty_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "oops.fsm", _PARSE_ERROR)

    code = main([path])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    # Rendered as FILE:LINE:COL: <message> -> the path and a line number appear.
    assert path in captured.err
    assert "parse error" in captured.err
    # The offending `??` token is on line 7 of the source.
    assert f"{path}:7:" in captured.err


# ---------------------------------------------------------------------------
# Property-based test for the stdout/exit contract (task 8.2).
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 14: Any rejected program produces empty
# stdout and a non-zero exit
#
# Property 14 (design): For any input that fails parsing or any safety check,
# the Transpiler writes NOTHING to stdout and exits non-zero; for any input that
# parses and passes all four safety checks, it writes SystemVerilog to stdout
# and exits 0.
#
# Validates: Requirements 15.4, 15.8, 16.2, 16.3, 16.5

import contextlib
import io
import os
import tempfile

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.strategies import invalid_program, render_program, valid_program


def _run_main_on_source(source: str) -> tuple[int, str, str]:
    """Write ``source`` to a temp .fsm file, run ``main``, capture streams.

    Returns ``(exit_code, stdout, stderr)``. Uses :mod:`tempfile` directly
    (rather than the ``tmp_path`` fixture) because Hypothesis discourages
    function-scoped fixtures under ``@given``; stdout/stderr are captured by
    redirecting them to in-memory buffers.
    """
    fd, path = tempfile.mkstemp(suffix=".fsm")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(source)
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            code = main([path])
        return code, out_buf.getvalue(), err_buf.getvalue()
    finally:
        os.unlink(path)


# Malformed sources that must fail at the parse stage (Req 15.8). These cover
# pure garbage, near-miss syntax, and an empty file -- none parse to a machine.
_MALFORMED_SOURCES = [
    "",
    "   \n\t\n",
    "this is not fsm dsl at all",
    "machine",
    "machine {",
    "machine m {",  # unterminated body
    "machine m { reset = S0 }",  # state block never opened/closed correctly
    "machine 123 { }",  # invalid machine name
    "state S0 { }",  # no enclosing machine
    "machine m {\n    in bit a\n    out bit y\n    reset = S0\n"
    "    state S0 {\n        y = 0\n        when a ?? S0\n        else -> S0\n    }\n}\n",
]


@given(valid_program())
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_accepted_program_writes_module_and_exits_zero(program) -> None:
    """Accepted half: a program passing all checks emits SV and exits 0."""
    source = render_program(program)

    code, out, _err = _run_main_on_source(source)

    assert code == 0, f"expected exit 0 for an accepted program, got {code}"
    assert out != "", "an accepted program must write SystemVerilog to stdout"
    assert "module " in out, "stdout must contain a generated module"


@given(invalid_program())
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_rejected_program_has_empty_stdout_and_nonzero_exit(case) -> None:
    """Rejected half: any safety/structurally invalid program -> empty stdout, exit != 0."""
    program, _kind = case
    source = render_program(program)

    code, out, _err = _run_main_on_source(source)

    assert code != 0, "a rejected program must terminate with a non-zero exit"
    assert out == "", "a rejected program must write nothing to stdout"


@given(st.sampled_from(sorted(_MALFORMED_SOURCES)))
@settings(max_examples=len(_MALFORMED_SOURCES), deadline=None)
def test_parse_failures_have_empty_stdout_and_nonzero_exit(source: str) -> None:
    """Rejected half (parse errors): malformed source -> empty stdout, exit != 0."""
    code, out, _err = _run_main_on_source(source)

    assert code != 0, "a parse failure must terminate with a non-zero exit"
    assert out == "", "a parse failure must write nothing to stdout"


# ---------------------------------------------------------------------------
# Property-based test for parse-failure line reporting (task 8.3).
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 15: Parse-failure diagnostics carry a
# line number
#
# Property 15 (design): For any input that fails to parse against the FSM_DSL
# grammar, the error written to standard error identifies the LINE NUMBER of
# the failure.
#
# Validates: Requirements 15.8, 16.4

from transpiler.errors import ParseError
from transpiler.parser import parse


def _run_main_capture(source: str) -> tuple[int, str, str, str]:
    """Like :func:`_run_main_on_source` but also returns the temp file path.

    The path is needed to assert it appears in the rendered diagnostic
    (``FILE:LINE:COL: <message>``). The file is removed before returning, so the
    path is only used for substring assertions against captured stderr.
    """
    fd, path = tempfile.mkstemp(suffix=".fsm")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(source)
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            code = main([path])
        return code, out_buf.getvalue(), err_buf.getvalue(), path
    finally:
        os.unlink(path)


@given(program=valid_program(), data=st.data())
@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_parse_failure_reports_the_injected_line(program, data) -> None:
    """Injecting a garbage token on a KNOWN line is reported at that line.

    We render a valid program (which parses cleanly), then splice a stray
    illegal token (``@@@``) onto its own newline at a chosen index. Because the
    token sits alone on its line, the failure's reported line is deterministic:
    it is the 1-based index of the injected line. We assert this at both the
    parser level (``ParseError.loc.line``) and the CLI level (the rendered
    ``FILE:LINE:COL`` diagnostic on stderr).
    """
    source = render_program(program)
    lines = source.split("\n")
    # Insert the garbage token on its own line at a position chosen across the
    # whole source (including before the first line and after the last).
    idx = data.draw(st.integers(min_value=0, max_value=len(lines)))
    bad_source = "\n".join(lines[:idx] + ["@@@"] + lines[idx:])
    injected_line = idx + 1  # 1-based line that now holds the stray token.

    # Parser level: the failure points exactly at the injected line.
    with pytest.raises(ParseError) as excinfo:
        parse(bad_source)
    err = excinfo.value
    assert err.loc.line == injected_line, (
        f"expected parse error on line {injected_line}, got {err.loc.line}"
    )
    # The rendered diagnostic embeds that line as FILE:LINE:COL:.
    assert f":{injected_line}:" in err.render()

    # CLI level: same failure, written to stderr with the file path and line.
    code, out, err_text, path = _run_main_capture(bad_source)
    assert code == 1, "a parse failure must exit non-zero"
    assert out == "", "a parse failure must write nothing to stdout"
    assert path in err_text, "the diagnostic must name the input file"
    assert f":{injected_line}:" in err_text, (
        "the diagnostic must identify the line number of the failure"
    )


# Sources that genuinely fail at the PARSE stage (raise ParseError). Unlike
# ``_MALFORMED_SOURCES`` -- which also holds inputs that parse but fail a later
# stage (e.g. the empty file, which is `start: machine*` with zero machines and
# is rejected by the AST builder, not the parser) -- every entry here is a true
# grammar failure, the scope of Property 15.
_PARSE_FAILING_SOURCES = [
    "this is not fsm dsl at all",  # leading NAME where `machine` is required
    "machine",  # EOF where a machine name is required
    "machine {",  # `{` where a machine name is required
    "machine m {",  # unterminated body (EOF before `}`)
    "machine 123 { }",  # INT where a machine name is required
    "state S0 { }",  # `state` at top level (only `machine` is admitted)
    "machine m {\n    @@@\n}\n",  # stray illegal token on line 2
    "machine oops {\n    in bit a\n    out bit y\n    reset = S0\n"
    "    state S0 {\n        y = 0\n        when a ?? S0\n        else -> S0\n    }\n}\n",
]


@given(st.sampled_from(sorted(_PARSE_FAILING_SOURCES)))
@settings(max_examples=len(_PARSE_FAILING_SOURCES), deadline=None)
def test_malformed_sources_always_carry_a_line_number(source: str) -> None:
    """Every genuine parse failure yields a diagnostic bearing a line number.

    These cover pure garbage, near-miss syntax, an unterminated body, and a
    stray illegal token. We do not predict the exact line for each (it varies),
    only that a valid 1-based line is present and is embedded in the rendered
    diagnostic and in the CLI's stderr output.
    """
    # Parser level: a ParseError with a real (>= 1) line, embedded in render().
    with pytest.raises(ParseError) as excinfo:
        parse(source)
    err = excinfo.value
    assert err.loc.line >= 1, "a parse error must carry a 1-based line number"
    assert f":{err.loc.line}:" in err.render()

    # CLI level: the same line number reaches stderr alongside the file path.
    code, out, err_text, path = _run_main_capture(source)
    assert code == 1
    assert out == ""
    assert path in err_text
    assert f":{err.loc.line}:" in err_text


# ---------------------------------------------------------------------------
# Property-based test for CLI argument arity (task 8.4).
# ---------------------------------------------------------------------------
# Feature: fsm-dsl-transpiler, Property 16: CLI argument arity is enforced
#
# Property 16 (design): For any invocation whose positional argument count is
# not exactly one, the Transpiler writes a usage error to standard error,
# writes nothing to standard output, and exits non-zero (the implementation
# returns 2 for arity errors).
#
# Validates: Requirements 15.6


def _run_main_with_argv(argv: list[str]) -> tuple[int, str, str]:
    """Call ``main(argv)`` directly, capturing stdout/stderr to buffers.

    No temp file is created: arity is validated before any file is read, so the
    arbitrary string contents of ``argv`` never reach the filesystem.
    """
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        code = main(argv)
    return code, out_buf.getvalue(), err_buf.getvalue()


@given(st.lists(st.text(), min_size=0, max_size=5).filter(lambda xs: len(xs) != 1))
@settings(max_examples=200, deadline=None)
def test_wrong_arity_is_usage_error_with_empty_stdout(argv: list[str]) -> None:
    """Any argv whose length != 1 -> usage to stderr, empty stdout, exit != 0.

    Covers the empty list (zero positionals) and multi-argument invocations
    (length 2..5) with arbitrary string contents. The implementation returns 2
    for arity errors, which we assert exactly while also enforcing the weaker
    non-zero contract from the property.
    """
    code, out, err = _run_main_with_argv(argv)

    assert code != 0, f"arity {len(argv)} must exit non-zero, got {code}"
    assert code == 2, f"arity errors return 2 per the implementation, got {code}"
    assert out == "", "an arity error must write nothing to stdout"
    assert "exactly one input file required" in err, (
        "an arity error must write the usage message to stderr"
    )
