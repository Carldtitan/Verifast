"""Step 6 — GRPO trainer on a Modal GPU (TRL), checkpointing to the Volume.

Two valid wirings; pick one:

  (A) HUD-driven rollouts (matches the diagram): HUD runs group=N rollouts against the
      vLLM endpoint, grades with the cosim reward, and computes advantages with
      hud.eval.group_relative(). This script consumes (prompt, completion, advantage)
      and applies the GRPO update, saving checkpoints to /weights.

  (B) TRL-native GRPO: TRL's GRPOTrainer does the sampling itself and calls a reward
      function directly (our grader). Simpler to stand up; HUD is then used for the
      held-out eval + curve rather than inside the inner loop.

This file scaffolds (B) — fewest moving parts for a 24h build — with the cosim grader
as the reward function. Swap to (A) to showcase HUD's group_relative() in the loop.

Run:  modal run train.py
NOTE: spends GPU credits. Launch only after the baseline signal check is green.
"""

import modal

MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"
GPU = "A100-80GB"

app = modal.App("rl-fsm-train")
weights = modal.Volume.from_name("rl-fsm-weights", create_if_missing=True)

image = (
    modal.Image.debian_slim()
    .pip_install("trl>=0.12", "transformers>=4.46", "datasets", "accelerate",
                 "peft", "vllm==0.6.6")
    # the cosim reward needs the OSS CAD Suite (verilator) inside the image:
    .run_commands(
        "apt-get update && apt-get install -y curl xz-utils build-essential",
        "mkdir -p /opt/oss && curl -L -o /tmp/oss.tgz "
        "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2026-06-20/"
        "oss-cad-suite-linux-x64-20260620.tgz && tar -xzf /tmp/oss.tgz -C /opt/oss",
    )
    .add_local_dir("../hud_env", "/root/hud_env")     # grader.py
    .add_local_dir("../tasks", "/root/tasks")          # generated tasks
)


@app.function(image=image, gpu=GPU, volumes={"/weights": weights},
              secrets=[modal.Secret.from_name("huggingface")], timeout=60 * 60 * 6)
def train(steps: int = 300, group: int = 16, ckpt_every: int = 25):
    import os, sys
    os.environ["PATH"] = "/opt/oss/oss-cad-suite/bin:" + os.environ["PATH"]
    sys.path.insert(0, "/root/hud_env")

    from pathlib import Path
    from datasets import Dataset
    from trl import GRPOConfig, GRPOTrainer
    from grader import grade  # the calibrated cosim reward

    # Load synthetic training tasks: prompt -> (golden kept for reward lookup).
    train_dir = Path("/root/tasks/generated/train")
    rows = []
    goldens = {}
    for d in sorted(train_dir.glob("task_*")):
        p = (d / "prompt.txt").read_text()
        goldens[p] = (d / "golden.sv").read_text()
        rows.append({"prompt": p})
    ds = Dataset.from_list(rows)

    def reward_fn(prompts, completions, **kw):
        out = []
        for prompt, comp in zip(prompts, completions):
            try:
                out.append(grade(comp, goldens[prompt])["reward"])
            except Exception:
                out.append(0.0)
        return out

    cfg = GRPOConfig(
        output_dir="/weights/latest",
        num_generations=group,
        max_steps=steps,
        save_steps=ckpt_every,
        per_device_train_batch_size=group,
        logging_steps=1,
        report_to="wandb",
        use_vllm=True,                # fast rollout generation
    )
    trainer = GRPOTrainer(model=MODEL, reward_funcs=reward_fn, args=cfg, train_dataset=ds)
    trainer.train()
    trainer.save_model("/weights/latest")
    weights.commit()
