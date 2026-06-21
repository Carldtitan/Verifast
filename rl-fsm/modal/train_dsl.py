"""GRPO training for the DSL arm on ONE Modal A100-80GB. Reward = transpile+cosim grader.

Single-GPU recipe (the one that actually works for 7B):
  * vLLM **co-located** (vllm_mode="colocate") -> fast KV-cache generation, same GPU as training
  * LoRA + bf16 + gradient checkpointing -> training fits alongside vLLM
  * vllm_gpu_memory_utilization=0.3 -> vLLM gets ~24GB, training gets the rest
Checkpoints to a Modal Volume every step (resumable).

Smoke:  modal run train_dsl.py --steps 3 --n-tasks 8 --group 4
Full:   modal run train_dsl.py --steps 60 --n-tasks 200 --group 8
"""
import modal

MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"
app = modal.App("rl-fsm-train-dsl")
weights = modal.Volume.from_name("rl-fsm-weights", create_if_missing=True)
hf_cache = modal.Volume.from_name("hf-cache", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("trl==0.18.0", "vllm==0.8.5", "transformers==4.51.3", "peft",
                 "accelerate", "datasets", "tokenizers")
    .run_commands(
        "apt-get update && apt-get install -y curl xz-utils build-essential",
        "mkdir -p /opt/oss && curl -L -o /tmp/oss.tgz "
        "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2026-06-20/"
        "oss-cad-suite-linux-x64-20260620.tgz && tar -xzf /tmp/oss.tgz -C /opt/oss && rm /tmp/oss.tgz",
        "pip install lark",
    )
    .add_local_dir("../hud_env", "/root/hud_env")
    .add_local_dir("../tasks", "/root/tasks")
    .add_local_dir("../../fsm-dsl-transpiler", "/root/fsm-dsl-transpiler")
)

GUIDE_HEAD = (
    "FSM-DSL quick reference:\n"
    "- machine NAME { ... }  (clk/rst implicit)\n"
    "- in TYPE name / out TYPE name  (TYPE = bit or bit[H:L])\n"
    "- reset = STATE\n"
    "- state NAME { output assignments; then transitions }\n"
    "- output: name = INT\n"
    "- transition: when COND -> STATE (priority), then mandatory else -> STATE\n"
    "- COND: bare x, x==k, x!=k, x[i], with && || ! ()\n"
    "Rules: assign every output in every state; every state ends with else -> STATE.\n\nExamples:\n"
)


@app.function(image=image, gpu="A100-80GB", volumes={"/weights": weights,
              "/root/.cache/huggingface": hf_cache}, timeout=60 * 60 * 4)
def train(steps: int = 3, n_tasks: int = 8, group: int = 4):
    import os, re, sys
    os.environ["PATH"] = "/opt/oss/oss-cad-suite/bin:" + os.environ["PATH"]
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    # single-process distributed env (vLLM colocate / TRL expect these; normally set by accelerate launch)
    os.environ.setdefault("RANK", "0")
    os.environ.setdefault("LOCAL_RANK", "0")
    os.environ.setdefault("WORLD_SIZE", "1")
    os.environ.setdefault("MASTER_ADDR", "127.0.0.1")
    os.environ.setdefault("MASTER_PORT", "29500")
    sys.path.insert(0, "/root/hud_env")
    sys.path.insert(0, "/root/fsm-dsl-transpiler")
    from pathlib import Path
    from datasets import Dataset
    from trl import GRPOConfig, GRPOTrainer
    from transformers import TrainerCallback
    from peft import LoraConfig
    from grader import grade
    from transpiler.parser import parse
    from transpiler.ast import build_ast
    from transpiler.safety import check
    from transpiler.codegen import generate as gen_sv

    fence = re.compile(r"```(?:fsm|dsl)?\s*(.*?)```", re.DOTALL)
    ex = "\n\n".join((Path("/root/fsm-dsl-transpiler/examples") / f"{n}.fsm").read_text()
                     for n in ("seq_detect_101", "traffic_light", "handshake"))
    guide = GUIDE_HEAD + ex

    def transpile(src):
        try:
            p = build_ast(parse(src, file="<g>"), source_file="<g>")
            return None if check(p) else gen_sv(p.machines[0])
        except Exception:
            return None

    tdir = Path("/root/tasks/generated/train")
    rows = []
    for d in sorted(tdir.glob("task_*"))[:n_tasks]:
        spec = (d / "prompt.txt").read_text()
        prompt = (f"{guide}\n\n---\nNow write an FSM-DSL program for this specification.\n"
                  f"Output ONLY a ```fsm code block.\n\n{spec}")
        rows.append({"prompt": prompt, "golden": (d / "golden.sv").read_text()})
    ds = Dataset.from_list(rows)

    def reward_fn(prompts, completions, golden, **kw):
        out = []
        for comp, gold in zip(completions, golden):
            m = fence.search(comp or "")
            sv = transpile((m.group(1) if m else comp or "").strip())
            out.append(0.0 if sv is None else float(grade(sv, gold)["reward"]))
        return out

    cfg = GRPOConfig(
        output_dir="/weights/dsl_latest",
        num_generations=group,
        per_device_train_batch_size=group,
        gradient_accumulation_steps=1,
        max_steps=steps,
        save_steps=10,
        save_total_limit=2,
        logging_steps=1,
        max_prompt_length=1024,
        max_completion_length=512,
        temperature=0.8,
        learning_rate=1e-5,
        report_to="none",
        bf16=True,
        gradient_checkpointing=True,
        beta=0.0,
        # --- the single-GPU magic: vLLM co-located with the trainer ---
        use_vllm=True,
        vllm_mode="colocate",
        vllm_gpu_memory_utilization=0.5,
        model_init_kwargs={"torch_dtype": "bfloat16"},
    )
    lora = LoraConfig(r=16, lora_alpha=32, task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj"])

    # Durability: persist the Volume on every checkpoint so a crash/long run never loses
    # progress (Modal Volume changes need an explicit commit to survive).
    class VolumeCommitCallback(TrainerCallback):
        def on_save(self, args, state, control, **kw):
            try:
                weights.commit()
                print(f"[ckpt] committed volume at step {state.global_step}")
            except Exception as e:  # noqa: BLE001
                print(f"[ckpt] commit failed: {e}")

    trainer = GRPOTrainer(model=MODEL, reward_funcs=reward_fn, args=cfg,
                          train_dataset=ds, peft_config=lora,
                          callbacks=[VolumeCommitCallback()])
    trainer.train()
    trainer.save_model("/weights/dsl_latest")
    weights.commit()
    print("TRAIN_OK steps=", steps)
