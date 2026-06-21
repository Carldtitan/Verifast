"""Baseline run: host Qwen2.5-Coder-7B on Modal and generate one answer per held-out
prompt. Grading happens locally (WSL has verilator) — Modal is used ONLY for inference.

Run:
    modal run baseline.py --tasks-dir "<abs path to tasks/generated/held_out>"

It writes each model answer to <task_dir>/baseline_answer.txt, which we then grade
locally with hud_env/grader.py.

Cost: one A100 for a few minutes (model download + 20 generations). Small.
"""

import modal

MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"

app = modal.App("rl-fsm-baseline")
# Cache the downloaded model across runs so we don't re-download 15GB every time.
hf_cache = modal.Volume.from_name("hf-cache", create_if_missing=True)

image = modal.Image.debian_slim().pip_install(
    "vllm==0.6.6", "transformers==4.47.1", "tokenizers==0.21.0",
)


@app.function(image=image, gpu="A100-40GB", volumes={"/root/.cache/huggingface": hf_cache},
              timeout=60 * 30)
def generate(prompts: list[str]) -> list[str]:
    """Load the model once and generate one completion per prompt (chat format)."""
    from vllm import LLM, SamplingParams

    llm = LLM(model=MODEL, max_model_len=4096, gpu_memory_utilization=0.92)
    sp = SamplingParams(temperature=0.2, max_tokens=1200)
    sys_msg = ("You are an expert hardware engineer. Write only synthesizable "
               "SystemVerilog. Output the module inside a ```systemverilog code block.")
    convos = [[{"role": "system", "content": sys_msg},
               {"role": "user", "content": p}] for p in prompts]
    outputs = llm.chat(convos, sp)
    return [o.outputs[0].text for o in outputs]


@app.local_entrypoint()
def main(tasks_dir: str):
    """Read held-out prompts locally, run them on Modal, save answers next to each task."""
    from pathlib import Path

    root = Path(tasks_dir)
    task_dirs = sorted(d for d in root.glob("task_*") if d.is_dir())
    prompts = [(d / "prompt.txt").read_text(encoding="utf-8") for d in task_dirs]
    print(f"sending {len(prompts)} prompts to Modal-hosted Qwen...")

    answers = generate.remote(prompts)

    for d, ans in zip(task_dirs, answers):
        (d / "baseline_answer.txt").write_text(ans, encoding="utf-8")
    print(f"wrote {len(answers)} answers (baseline_answer.txt) into {root}")
