"""Step 5 — serve the policy model on Modal as an OpenAI-compatible endpoint.

vLLM serves Qwen2.5-Coder-7B. Weights/checkpoints live on a persistent Modal Volume
so a dropped session or expired key never loses progress — you resume from the Volume.

Deploy:   modal deploy serve.py
Endpoint: the printed URL exposes /v1/chat/completions (OpenAI-compatible), which HUD
          points at for rollouts and held-out eval.

NOTE: running this spends GPU credits. Do not launch until the free phase
(environment + tasks + baseline signal check) is green.
"""

import modal

MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"
GPU = "A100-40GB"            # 7B serves comfortably; bump to A100-80GB if needed

app = modal.App("rl-fsm-serve")

# Persistent storage for base weights + RL checkpoints (survives restarts).
weights = modal.Volume.from_name("rl-fsm-weights", create_if_missing=True)

image = (
    modal.Image.debian_slim()
    .pip_install("vllm==0.6.6", "huggingface_hub")
)


@app.function(
    image=image,
    gpu=GPU,
    volumes={"/weights": weights},
    secrets=[modal.Secret.from_name("huggingface")],  # HF token for the download
    timeout=60 * 60,
    scaledown_window=300,
)
@modal.web_server(port=8000, startup_timeout=600)
def serve():
    """Launch a vLLM OpenAI-compatible server.

    Loads the latest checkpoint from the Volume if one exists, else the base model.
    HUD calls this endpoint to generate candidate Verilog during rollouts/eval.
    """
    import os
    import subprocess

    ckpt = "/weights/latest"
    model_path = ckpt if os.path.isdir(ckpt) else MODEL
    subprocess.Popen([
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model", model_path,
        "--host", "0.0.0.0", "--port", "8000",
        "--max-model-len", "4096",
    ])
