"""DSL arm: Qwen writes FSM-DSL (in-context), not Verilog.

The model gets a short DSL guide + the 3 examples, then the task, and outputs a `.fsm`
program. We save the raw .fsm answers; grading (transpile -> cosim) happens locally.

Run:
    modal run baseline_dsl.py --tasks-dir "<abs held_out dir>"
"""
import modal

MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"
app = modal.App("rl-fsm-baseline-dsl")
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
    sys_msg = ("You are an expert at the FSM-DSL hardware language. Write ONLY a valid "
               "FSM-DSL program inside a ```fsm code block. Do not write Verilog.")
    convos = [[{"role": "system", "content": sys_msg},
               {"role": "user", "content": p}] for p in prompts]
    outputs = llm.chat(convos, sp)
    return [o.outputs[0].text for o in outputs]


_GUIDE = """FSM-DSL quick reference:
- machine NAME { ... }            one state machine (clk and rst are implicit, never declared)
- in TYPE name / out TYPE name    ports; TYPE is `bit` or `bit[H:L]`
- reset = STATE                   the power-on state
- state NAME { ... }              a state: first the output assignments, then the transitions
- output assignment:  name = INT  set a Moore output for this state
- transition:  when COND -> STATE (priority, top to bottom), then a MANDATORY  else -> STATE
- COND over inputs: bare `x`, `x == k`, `x != k`, `x[i]`, combined with && || ! and ( )
Hard rules: every declared output MUST be assigned in EVERY state; every state MUST end with
`else -> STATE`. Comments start with #.

Examples:
"""


@app.local_entrypoint()
def main(tasks_dir: str):
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2] / "fsm-dsl-transpiler"
    examples = "\n\n".join(
        (repo / "examples" / f"{n}.fsm").read_text(encoding="utf-8")
        for n in ("seq_detect_101", "traffic_light", "handshake")
    )
    guide = _GUIDE + examples

    root = Path(tasks_dir)
    task_dirs = sorted(d for d in root.glob("task_*") if d.is_dir())
    prompts = []
    for d in task_dirs:
        spec = (d / "prompt.txt").read_text(encoding="utf-8")
        prompts.append(
            f"{guide}\n\n---\nNow write an FSM-DSL program for this specification.\n"
            f"Output ONLY a ```fsm code block.\n\n{spec}"
        )
    print(f"sending {len(prompts)} DSL prompts to Modal-hosted Qwen...")

    answers = generate.remote(prompts)

    out_dir = Path(__file__).resolve().parents[1] / "runs" / "qwen2.5-coder-7b-dsl" / "heldout"
    out_dir.mkdir(parents=True, exist_ok=True)
    for d, ans in zip(task_dirs, answers):
        (out_dir / f"{d.name}.txt").write_text(ans, encoding="utf-8")
    print(f"wrote {len(answers)} DSL answers to {out_dir}")
