"""Apply storage settings to this process, without changing system settings."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def configure_storage() -> dict[str, str]:
    paths = {
        "CF_PROJECT_ROOT": ROOT,
        "OLLAMA_MODELS": ROOT / "models" / "ollama",
        "HF_HOME": ROOT / "cache" / "huggingface",
        "HF_HUB_CACHE": ROOT / "cache" / "huggingface" / "hub",
        "HUGGINGFACE_HUB_CACHE": ROOT / "cache" / "huggingface" / "hub",
        "PIP_CACHE_DIR": ROOT / "cache" / "pip",
        "UV_CACHE_DIR": ROOT / "cache" / "uv",
        "UV_PYTHON_INSTALL_DIR": ROOT / ".tools" / "python",
        "TORCH_HOME": ROOT / "cache" / "torch",
        "CUDA_CACHE_PATH": ROOT / "cache" / "cuda",
        "MODELSCOPE_CACHE": ROOT / "cache" / "modelscope",
        "TEMP": ROOT / "cache" / "tmp",
        "TMP": ROOT / "cache" / "tmp",
    }
    for key, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    os.environ["UV_PYTHON_NO_REGISTRY"] = "1"
    os.environ["UV_NO_MODIFY_PATH"] = "1"
    os.environ["PYTHONNOUSERSITE"] = "1"
    return {key: str(path) for key, path in paths.items()}
