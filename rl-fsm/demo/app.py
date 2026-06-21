"""Two-panel 'dual IDE' demo (Streamlit).

    export HUD_API_KEY=sk-hud-...
    streamlit run app.py

Left panel  : your FINE-TUNED model writing FSM-DSL (transpiled to SystemVerilog).
Right panel : a BASE (un-fine-tuned) model writing raw SystemVerilog.
Same spec to both. The Verilator verifier scores each; verbose metrics shown below.
"""
from __future__ import annotations

import os
import streamlit as st

import core

st.set_page_config(page_title="DSL vs Verilog — fine-tuned vs base", layout="wide")
st.title("FSM hardware: fine-tuned DSL  vs  base Verilog")
st.caption("Same spec → both models → Verilator verifier scores each output.")

with st.sidebar:
    st.header("Config")
    api_key = st.text_input("HUD API key", value=os.environ.get("HUD_API_KEY", ""),
                            type="password", help="Needed to call the models on HUD's gateway.")
    dsl_model = st.text_input("Fine-tuned model (DSL arm)", value=core.DSL_MODEL_DEFAULT)
    ver_model = st.text_input("Base model (Verilog arm)", value=core.VERILOG_MODEL_DEFAULT)
    temperature = st.slider("Temperature", 0.0, 1.5, 0.0, 0.1)
    tasks = core.list_tasks()
    task = st.selectbox("Task (spec)", tasks)
    go = st.button("▶ Run both", type="primary", use_container_width=True)

spec, golden = core.load_task(task)
st.subheader("Shared specification (sent verbatim to both models)")
st.code(spec, language="text")


def render(col, title, res: core.ArmResult):
    with col:
        st.markdown(f"### {title}")
        if res.passed:
            st.success(f"PASS — reward {res.reward:.3f}")
        else:
            st.error(f"FAIL — reward {res.reward:.3f}")
        p = res.parts or {}
        m1, m2, m3 = st.columns(3)
        m1.metric("compiles", f"{p.get('compile',0):.0f}")
        m2.metric("lint-clean", f"{p.get('lint',0):.0f}")
        m3.metric("behaviour", f"{p.get('behavior',0):.0f}")
        m4, m5, m6 = st.columns(3)
        m4.metric("completion tokens", res.completion_tokens)
        m5.metric("latency", f"{res.latency_s:.2f}s")
        m6.metric("speed", f"{res.tokens_per_s:.1f} tok/s")
        st.markdown("**Raw model output**")
        st.code(res.raw_output or "(empty)", language="text")
        st.markdown("**SystemVerilog (verified)**")
        st.code(res.code or "(no parseable code produced)", language="verilog")


if go:
    if not api_key:
        st.warning("Enter your HUD API key in the sidebar first.")
        st.stop()
    cli = core.client(api_key)
    left, right = st.columns(2)
    with st.spinner("Fine-tuned model writing DSL..."):
        dsl = core.run_arm(cli, "DSL", dsl_model, spec, golden, temperature=temperature)
    with st.spinner("Base model writing Verilog..."):
        ver = core.run_arm(cli, "Verilog", ver_model, spec, golden, temperature=temperature)
    render(left, f"🟢 Fine-tuned · DSL · `{dsl_model}`", dsl)
    render(right, f"⚪ Base · Verilog · `{ver_model}`", ver)
else:
    st.info("Set your key, pick a task, and hit **Run both** in the sidebar.")
