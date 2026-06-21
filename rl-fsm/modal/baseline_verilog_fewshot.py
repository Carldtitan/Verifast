"""Fair control: Qwen writes Verilog, but with the SAME 3 in-context examples the DSL
arm got — here the 3 golden SystemVerilog modules (clean, three-block Moore, sync reset).

This isolates the DSL effect from the "examples help" effect.

Run:
    modal run baseline_verilog_fewshot.py --tasks-dir "<abs held_out dir>"
"""
import modal

MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"
app = modal.App("rl-fsm-baseline-vfewshot")
hf_cache = modal.Volume.from_name("hf-cache", create_if_missing=True)
image = modal.Image.debian_slim().pip_install(
    "vllm==0.6.6", "transformers==4.47.1", "tokenizers==0.21.0",
)


@app.function(image=image, gpu="A100-40GB", volumes={"/root/.cache/huggingface": hf_cache},
              timeout=60 * 30)
def generate(prompts: list[str]) -> list[str]:
    from vllm import LLM, SamplingParams
    llm = LLM(model=MODEL, max_model_len=4096, gpu_memory_utilization=0.92)
    sp = SamplingParams(temperature=0.2, max_tokens=1200)
    sys_msg = ("You are an expert hardware engineer. Write only synthesizable "
               "SystemVerilog. Output the module inside a ```systemverilog code block.")
    convos = [[{"role": "system", "content": sys_msg},
               {"role": "user", "content": p}] for p in prompts]
    outputs = llm.chat(convos, sp)
    return [o.outputs[0].text for o in outputs]


_GUIDE = """SystemVerilog FSM style guide:
- Synchronous, active-high reset. Implicit ports: clk, rst (always declare them).
- Three-always-block Moore style: a combinational next-state block, a combinational
  output block, and an always_ff @(posedge clk) state register.
- Use an enum logic state type. Size every literal to its signal width. Assign every
  output in every state and give every case a default. Must be lint-clean under
  `verilator --lint-only -Wall` (no unused signals, no width warnings).

Examples:
"""


@app.local_entrypoint()
def main(tasks_dir: str):
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2] / "fsm-dsl-transpiler"
    examples = "\n\n".join(
        (repo / "golden" / f"{n}.sv").read_text(encoding="utf-8")
        for n in ("seq_detect_101", "traffic_light", "handshake")
    )
    guide = _GUIDE + examples

    root = Path(tasks_dir)
    task_dirs = sorted(d for d in root.glob("task_*") if d.is_dir())
    prompts = []
    for d in task_dirs:
        spec = (d / "prompt.txt").read_text(encoding="utf-8")
        prompts.append(
            f"{guide}\n\n---\nNow write a synthesizable SystemVerilog module for this "
            f"specification. Output ONLY a ```systemverilog code block.\n\n{spec}"
        )
    print(f"sending {len(prompts)} Verilog-fewshot prompts to Modal-hosted Qwen...")

    answers = generate.remote(prompts)

    out_dir = Path(__file__).resolve().parents[1] / "runs" / "qwen2.5-coder-7b-verilog-fewshot" / "heldout"
    out_dir.mkdir(parents=True, exist_ok=True)
    for d, ans in zip(task_dirs, answers):
        (out_dir / f"{d.name}.txt").write_text(ans, encoding="utf-8")
    print(f"wrote {len(answers)} answers to {out_dir}")
