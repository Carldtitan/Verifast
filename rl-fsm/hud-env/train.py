"""HUD-native GRPO training loop for the FSM-DSL environment.

The whole loop lives on HUD: rollouts run against the deployed `fsm-dsl-rl-v1`
environment (Verilator reward), and HUD's managed trainer (Tinker-backed) applies
the GRPO update and promotes the new weights so the gateway serves them next step.

    fork once:  hud models fork Qwen/Qwen3-8B --name fsm-rl
    smoke:      python train.py --steps 2 --tasks-per-step 3 --group 4
    full:       python train.py --steps 40 --tasks-per-step 6 --group 8 --lr 1e-5

Each step = `tasks_per_step` tasks x `group` rollouts (one GRPO group per task).
GRPO needs reward spread within a group, so we train on the easy `train/` split
(the model passes some, fails some) and keep `eval/` held out for `hud eval`.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from env import fsm_task  # noqa: E402  (constructs eval Task rows on the deployed env)
from hud.agents import create_agent  # noqa: E402
from hud.eval import HostedRuntime, HUDRuntime, Job, LocalRuntime, Taskset  # noqa: E402
from hud.train import TrainingClient  # noqa: E402

MODEL = "fsm-rl"
TRAIN_SPLIT = "train"  # overridden by --train-split
EVAL_DIR = ROOT / "task_data" / "eval"


def _train_dir() -> Path:
    return ROOT / "task_data" / TRAIN_SPLIT


def _pool() -> list[str]:
    return sorted(d.name for d in _train_dir().glob("task_*") if d.is_dir())


async def _evaluate(eval_agent, runtime, n: int, group: int, max_concurrent: int) -> dict:
    """Roll out the held-out split (no weight update) and return aggregate metrics."""
    names = sorted(d.name for d in EVAL_DIR.glob("task_*") if d.is_dir())[:n]
    tasks = []
    for d in names:
        t = fsm_task(task_dir=f"eval/{d}", mode="dsl")
        t.slug = f"eval-{d}-dsl"
        tasks.append(t)
    ts = Taskset("fsm-eval", tasks)
    job = await Job.start(f"{MODEL}-eval", group=group)
    await ts.run(eval_agent, runtime=runtime, job=job, group=group, max_concurrent=max_concurrent)
    rewards = [r.reward for r in job.runs]
    m = len(rewards)
    return {
        "n": m,
        "mean": (sum(rewards) / m) if m else 0.0,
        "pass1": (sum(1 for r in rewards if r >= 0.999) / m) if m else 0.0,
        "behav": (sum(1 for r in rewards if r >= 0.7) / m) if m else 0.0,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=2)
    ap.add_argument("--tasks-per-step", type=int, default=3)
    ap.add_argument("--group", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--loss", type=str, default="importance_sampling")
    ap.add_argument("--max-concurrent", type=int, default=8)
    ap.add_argument("--runtime", choices=["local", "hosted", "tunnel"], default="local",
                    help="local: env in a child process here, agent samples gateway "
                         "(robust, inline tokens); hosted: whole rollout on HUD; "
                         "tunnel: local agent loop over a HUD websocket")
    ap.add_argument("--eval-every", type=int, default=5, help="eval held-out every K steps (0=off)")
    ap.add_argument("--eval-n", type=int, default=20)
    ap.add_argument("--train-split", default="train", help="task_data subdir to train on")
    ap.add_argument("--temp", type=float, default=1.0, help="rollout sampling temperature (exploration)")
    ap.add_argument("--eval-temp", type=float, default=0.0, help="held-out eval temperature (0=greedy)")
    args = ap.parse_args()

    global TRAIN_SPLIT
    TRAIN_SPLIT = args.train_split

    names = _pool()
    if not names:
        raise SystemExit(f"no train tasks under {TRAIN_DIR}")
    print(f"[init] {len(names)} train tasks; model={MODEL} "
          f"steps={args.steps} tasks/step={args.tasks_per_step} group={args.group} "
          f"split={TRAIN_SPLIT} temp={args.temp} eval_temp={args.eval_temp}")

    agent = create_agent(MODEL, completion_kwargs={
        "temperature": args.temp,
        "extra_body": {"return_token_ids": True}})
    eval_agent = create_agent(MODEL, completion_kwargs={
        "temperature": args.eval_temp,
        "extra_body": {"return_token_ids": True}})
    trainer = TrainingClient(MODEL)

    try:
        losses = await trainer.available_losses()
        print(f"[init] available losses: {losses}")
        loss_fn = args.loss if args.loss in losses else (losses[0] if losses else args.loss)
    except Exception as e:  # noqa: BLE001
        print(f"[init] available_losses failed ({e}); using {args.loss}")
        loss_fn = args.loss
    print(f"[init] loss_fn={loss_fn}")

    if args.runtime == "local":
        runtime = LocalRuntime(str(ROOT / "env.py"), env="fsm-dsl-rl-v1")
    elif args.runtime == "hosted":
        runtime = HostedRuntime()
    else:
        runtime = HUDRuntime()
    print(f"[init] runtime={type(runtime).__name__}")
    session = await Job.start(MODEL, group=args.group)
    cyc = itertools.cycle(names)

    async def run_eval(tag: str) -> None:
        if args.eval_every <= 0:
            return
        m = await _evaluate(eval_agent, runtime, args.eval_n, 1, args.max_concurrent)
        print(f"EVAL {tag} held_out n={m['n']} pass@1={m['pass1']:.3f} "
              f"behavior={m['behav']:.3f} mean={m['mean']:.3f}", flush=True)

    await run_eval("step0(base)")

    for step in range(1, args.steps + 1):
        chosen = [next(cyc) for _ in range(args.tasks_per_step)]
        tasks = []
        for d in chosen:
            t = fsm_task(task_dir=f"{TRAIN_SPLIT}/{d}", mode="dsl")
            t.slug = f"{TRAIN_SPLIT}-{d}-dsl"
            tasks.append(t)
        ts = Taskset(f"fsm-train-s{step}", tasks)

        try:
            t0 = time.time()
            start = len(session.runs)
            await ts.run(agent, runtime=runtime, job=session,
                         group=args.group, max_concurrent=args.max_concurrent)
            batch = session.runs[start:]
            rewards = [r.reward for r in batch]
            mean = sum(rewards) / len(rewards) if rewards else 0.0
            spread = (max(rewards) - min(rewards)) if rewards else 0.0
            roll_s = time.time() - t0

            if not batch:
                print(f"[step {step}] no runs produced; skipping update", flush=True)
                continue

            t1 = time.time()
            res = await trainer.step(batch, learning_rate=args.lr,
                                     loss_fn=loss_fn, group_size=args.group)
            ckpt = getattr(res, "checkpoint_id", None)
            stepno = getattr(res, "step", None)
            upd_s = time.time() - t1
            print(f"[step {step}] tasks={chosen} n={len(batch)} "
                  f"mean_reward={mean:.3f} spread={spread:.2f} "
                  f"roll={roll_s:.0f}s upd={upd_s:.0f}s step#={stepno} ckpt={ckpt}", flush=True)
        except Exception as e:  # noqa: BLE001  (overnight resilience: skip a bad step)
            print(f"[step {step}] ERROR ({e!r}); skipping to next step", flush=True)
            continue

        if args.eval_every > 0 and step % args.eval_every == 0:
            try:
                await run_eval(f"step{step}")
            except Exception as e:  # noqa: BLE001
                print(f"[eval step{step}] ERROR ({e!r})", flush=True)

    await run_eval("final")
    print("TRAIN_DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
