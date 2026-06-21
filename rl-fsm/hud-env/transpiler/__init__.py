"""FSM_DSL transpiler package.

A frozen Python 3.12 transpiler for FSM_DSL v0.1: parses Moore-FSM source,
enforces compile-time safety rules, and emits lint-clean, latch-free,
synthesizable SystemVerilog in the canonical three-always-block style.

Only third-party runtime dependency: ``lark``. Everything else is the
Python 3.12 standard library.
"""

__version__ = "0.1.0"
