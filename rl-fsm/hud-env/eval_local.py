"""Local eval (rollouts only, no weight update): report pass@1 and mean reward.

Rolls out a split through the local env (Verilator) against a gateway model and
prints aggregate metrics. Used to baseline a model and pick training difficulty.

    python eval_local.py --split eval --mode dsl --n 20 --model fsm-rl
    python eval_local.py --split train --mode dsl --n 40 --model Qwen/Qwen3-8B
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from env import fsm_task  # noqa: E402
from hud.agents import create_agent  # noqa: E402
from hud.eval import Job, LocalRuntime, Taskset  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="eval")          # train | eval
    ap.add_argument("--mode", default="dsl")            # dsl | verilog
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--model", default="fsm-rl")
    ap.add_argument("--group", type=int, default=1)     # >1 for pass@k style
    ap.add_argument("--max-concurrent", type=int, default=8)
    args = ap.parse_args()

    base = ROOT / "task_data" / args.split
    names = sorted(d.name for d in base.glob("task_*") if d.is_dir())[:args.n]
    tasks = []
    for d in names:
        t = fsm_task(task_dir=f"{args.split}/{d}", mode=args.mode)
        t.slug = f"{args.split}-{d}-{args.mode}"
        tasks.append(t)
    ts = Taskset(f"eval-{args.split}-{args.mode}", tasks)

    agent = create_agent(args.model,
                         completion_kwargs={"temperature": 0.0,
                                            "extra_body": {"return_token_ids": True}})
    job = await Job.start(f"eval-{args.model}", group=args.group)
    await ts.run(agent, runtime=LocalRuntime(str(ROOT / "env.py"), env="fsm-dsl-rl-v1"),
                 job=job, group=args.group, max_concurrent=args.max_concurrent)

    rewards = [r.reward for r in job.runs]
    n = len(rewards)
    mean = sum(rewards) / n if n else 0.0
    passed = sum(1 for r in rewards if r >= 0.999)      # full reward = compiles+lint+behaves
    behav = sum(1 for r in rewards if r >= 0.7)         # behavior cosim passed
    print(f"model={args.model} split={args.split} mode={args.mode} n={n}")
    print(f"  mean_reward = {mean:.3f}")
    print(f"  pass@1 (reward==1.0)      = {passed}/{n} = {passed/n:.2f}" if n else "")
    print(f"  behavior-correct (>=0.7)  = {behav}/{n} = {behav/n:.2f}" if n else "")
    print(f"  reward histogram: " + ", ".join(f"{x:.2f}" for x in sorted(rewards)))


if __name__ == "__main__":
    asyncio.run(main())
