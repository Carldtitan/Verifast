"""Generate all result charts (PNG) into rl-fsm/charts/.

Data is the verified output of the actual runs (HUD checkpoint tree, held-out evals,
baseline results.json, and the DSL-vs-Verilog held-out evals). Run:
    python charts.py
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent / "charts"
OUT.mkdir(exist_ok=True)

NAVY, BLUE, GREEN, RED, GREY = "#1f2a44", "#2e6fdb", "#2ca25f", "#d6453d", "#9aa0aa"


def save(fig, name):
    fig.tight_layout()
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote", p)


# ---------------------------------------------------------------- Chart 1
# HUD managed-trainer reward per optimizer step (the 49-checkpoint tree).
hud_reward = [0.000,1.000,0.917,0.875,0.947,0.672,0.825,1.000,0.825,1.000,
              1.000,0.825,0.934,0.794,0.869,0.978,0.816,0.969,1.000,1.000,
              0.706,0.825,1.000,0.803,1.000,1.000,0.825,0.978,0.781,1.000,
              0.969,0.825,1.000,1.000,1.000,0.803,0.794,0.978,0.891,1.000,
              1.000,0.825,0.978,0.781,1.000,1.000,1.000,1.000,0.956]
steps = list(range(1, len(hud_reward) + 1))
fig, ax = plt.subplots(figsize=(11, 4.5))
ax.plot(steps, hud_reward, "-o", color=BLUE, ms=4, lw=1.6)
ax.axvspan(0.5, 4.5, color=GREY, alpha=0.18)
ax.axvspan(4.5, 34.5, color=GREEN, alpha=0.10)
ax.axvspan(34.5, 49.5, color=BLUE, alpha=0.10)
ax.text(2.5, 0.04, "smoke\n(1-4)", ha="center", fontsize=8, color=NAVY)
ax.text(19.5, 0.04, "Run 1  (temp 0.7, train split)", ha="center", fontsize=9, color=NAVY)
ax.text(42, 0.04, "Run 2  (temp 1.1)", ha="center", fontsize=9, color=NAVY)
ax.set_xlabel("HUD optimizer step (checkpoint)")
ax.set_ylabel("Mean group reward")
ax.set_title("HUD managed GRPO — training reward per step (Qwen3-8B → fsm-rl)")
ax.set_ylim(-0.03, 1.05); ax.grid(alpha=0.3)
save(fig, "1_hud_training_reward.png")


# ---------------------------------------------------------------- Chart 2
# Held-out pass@1 vs training step — Run 1 (flat) vs Run 2 (rises). THE money chart.
r1_x = [0, 5, 10, 15, 20, 25, 30]
r1_y = [0.75, 0.70, 0.75, 0.75, 0.75, 0.75, 0.75]
r2_x = [0, 5, 10, 15]
r2_y = [0.75, 0.80, 0.95, 0.95]
fig, ax = plt.subplots(figsize=(9, 5.2))
ax.plot(r1_x, r1_y, "-o", color=GREY, lw=2, ms=7, label="Run 1 — rollout temp 0.7 (flat)")
ax.plot(r2_x, r2_y, "-o", color=GREEN, lw=2.4, ms=8, label="Run 2 — rollout temp 1.1 (learns)")
ax.axhline(0.75, color=RED, ls="--", lw=1, alpha=0.6)
ax.text(30, 0.755, "base 0.75", color=RED, fontsize=8, va="bottom", ha="right")
for x, y in zip(r2_x, r2_y):
    ax.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(0, 9),
                ha="center", fontsize=9, color=GREEN)
ax.set_xlabel("Training step"); ax.set_ylabel("Held-out pass@1 (n=20, greedy)")
ax.set_title("RL on HUD — held-out pass@1 vs steps (eval temp held at 0)")
ax.set_ylim(0.6, 1.0); ax.grid(alpha=0.3); ax.legend(loc="lower right")
save(fig, "2_heldout_passk_vs_steps.png")


# ---------------------------------------------------------------- Chart 3
# DSL vs Verilog baselines (Modal-hosted Qwen2.5-Coder-7B + Claude), 20 held-out.
labels = ["Qwen7B\nVerilog\n(0-shot)", "Qwen7B\nVerilog\n(3-shot)",
          "Qwen7B\nDSL\n(3-shot)", "Claude\nVerilog"]
functional = [0.15, 0.25, 0.85, 1.00]
clean = [0.00, 0.00, 0.85, 0.00]
x = range(len(labels)); w = 0.38
fig, ax = plt.subplots(figsize=(9, 5))
ax.bar([i - w/2 for i in x], functional, w, label="functional pass@1", color=BLUE)
ax.bar([i + w/2 for i in x], clean, w, label="lint-clean pass@1", color=GREEN)
for i, v in enumerate(functional):
    ax.text(i - w/2, v + 0.02, f"{v:.0%}", ha="center", fontsize=9)
for i, v in enumerate(clean):
    ax.text(i + w/2, v + 0.02, f"{v:.0%}", ha="center", fontsize=9)
ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=9)
ax.set_ylabel("pass@1 (20 held-out FSMs)"); ax.set_ylim(0, 1.1)
ax.set_title("Baselines: DSL vs Verilog action space (same specs)")
ax.legend(); ax.grid(axis="y", alpha=0.3)
save(fig, "3_baseline_dsl_vs_verilog.png")


# ---------------------------------------------------------------- Chart 4
# Base vs RL-trained Qwen3-8B on held-out (DSL arm).
labels = ["Base Qwen3-8B", "RL-trained fsm-rl"]
pass1 = [0.75, 0.95]; meanr = [0.825, 0.965]
x = range(len(labels)); w = 0.38
fig, ax = plt.subplots(figsize=(7.5, 5))
b1 = ax.bar([i - w/2 for i in x], pass1, w, label="pass@1", color=BLUE)
b2 = ax.bar([i + w/2 for i in x], meanr, w, label="mean reward", color=GREEN)
for i, v in enumerate(pass1):
    ax.text(i - w/2, v + 0.015, f"{v:.0%}", ha="center", fontsize=10)
for i, v in enumerate(meanr):
    ax.text(i + w/2, v + 0.015, f"{v:.2f}", ha="center", fontsize=10)
ax.annotate("", xy=(1 - w/2, 0.95), xytext=(0 - w/2, 0.75),
            arrowprops=dict(arrowstyle="->", color=RED, lw=2))
ax.text(0.5, 0.88, "+20 pp", color=RED, fontsize=12, ha="center", fontweight="bold")
ax.set_xticks(list(x)); ax.set_xticklabels(labels)
ax.set_ylabel("held-out DSL (n=20, greedy)"); ax.set_ylim(0, 1.1)
ax.set_title("RL on HUD lifted the model (held-out, greedy)")
ax.legend(loc="lower left"); ax.grid(axis="y", alpha=0.3)
save(fig, "4_base_vs_trained.png")


# ---------------------------------------------------------------- Chart 5
# The 2x2: same model, same tasks, DSL vs Verilog, base vs trained.
groups = ["DSL arm", "Verilog arm"]
base = [0.75, 0.00]; trained = [0.95, 0.00]
x = range(len(groups)); w = 0.38
fig, ax = plt.subplots(figsize=(8, 5))
ax.bar([i - w/2 for i in x], base, w, label="Base Qwen3-8B", color=GREY)
ax.bar([i + w/2 for i in x], trained, w, label="RL-trained fsm-rl", color=GREEN)
for i, v in enumerate(base):
    ax.text(i - w/2, v + 0.02, f"{v:.0%}", ha="center", fontsize=10)
for i, v in enumerate(trained):
    ax.text(i + w/2, v + 0.02, f"{v:.0%}", ha="center", fontsize=10)
ax.text(1, 0.18, "Verilog pass@1 = 0% for BOTH\n(behaviorally ~55-60% correct,\nbut never lint-clean — the footgun)",
        ha="center", fontsize=8.5, color=RED,
        bbox=dict(boxstyle="round", fc="#fff3f2", ec=RED, alpha=0.9))
ax.set_xticks(list(x)); ax.set_xticklabels(groups, fontsize=11)
ax.set_ylabel("pass@1 (20 held-out FSMs, greedy)"); ax.set_ylim(0, 1.1)
ax.set_title("Same model, same specs: DSL vs Verilog (Qwen3-8B)")
ax.legend(loc="upper right"); ax.grid(axis="y", alpha=0.3)
save(fig, "5_dsl_vs_verilog_trained.png")

print("\nAll charts written to", OUT)
