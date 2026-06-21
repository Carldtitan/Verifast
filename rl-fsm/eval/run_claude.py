"""Run a hosted Anthropic Claude model over the held-out prompts (Verilog arm).

Claude is served by Anthropic — no GPU/Modal needed, just the API. Writes one answer
per task to runs/<model-tag>/heldout/task_XXXX.txt so each model's outputs are separate.

Usage (CLAUDE_API_KEY in env or in ../../.env):
    python run_claude.py --tasks-dir "<abs held_out dir>" --model claude-sonnet-4-5
"""
from __future__ import annotations
import argparse, os
from pathlib import Path

SYS = ("You are an expert hardware engineer. Write only synthesizable SystemVerilog. "
       "Output the module inside a ```systemverilog code block.")


def _load_key() -> str:
    key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    # fall back to the project .env (two levels up)
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("CLAUDE_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("CLAUDE_API_KEY not found in env or .env")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-dir", required=True)
    ap.add_argument("--model", default="claude-sonnet-4-5")
    ap.add_argument("--out-root", default=str(Path(__file__).resolve().parents[1] / "runs"))
    args = ap.parse_args()

    from anthropic import Anthropic
    client = Anthropic(api_key=_load_key())

    root = Path(args.tasks_dir)
    out_dir = Path(args.out_root) / args.model / "heldout"
    out_dir.mkdir(parents=True, exist_ok=True)

    task_dirs = sorted(d for d in root.glob("task_*") if d.is_dir())
    print(f"running {args.model} on {len(task_dirs)} held-out prompts...")
    for d in task_dirs:
        prompt = (d / "prompt.txt").read_text(encoding="utf-8")
        resp = client.messages.create(
            model=args.model,
            max_tokens=1500,
            system=SYS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        (out_dir / f"{d.name}.txt").write_text(text, encoding="utf-8")
        print(f"  {d.name} done")
    print(f"wrote answers to {out_dir}")


if __name__ == "__main__":
    main()
