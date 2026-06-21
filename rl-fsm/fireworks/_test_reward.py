import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fireworks"))
import reward

ans = (ROOT / "runs" / "qwen2.5-coder-7b-dsl" / "heldout" / "task_0000.txt").read_text(encoding="utf-8")
golden = (ROOT / "tasks" / "generated" / "held_out" / "task_0000" / "golden.sv").read_text(encoding="utf-8")
msgs = [{"role": "user", "content": "write the FSM"}, {"role": "assistant", "content": ans}]

res = reward.evaluate(messages=msgs, ground_truth=golden)
score = getattr(res, "score", res)
reason = getattr(res, "reason", "")
print("REWARD-KIT SCORE:", score)
print("REASON:", reason)
