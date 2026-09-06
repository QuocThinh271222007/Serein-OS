"""AI model/dataset storage conventions.

S4 does not invent a new, unified data root or assume a dedicated
volume exists (Section 45/46 — that is S7's job once a real deployment
target exists). Instead this module reports where each tool's *own*
existing convention already points: Hugging Face's ``HF_HOME``, and
Ollama's ``OLLAMA_MODELS`` — never relocating either. Every path is
normalized (the real home directory prefix replaced with ``~``) before
being stored, so a caller can never accidentally leak the actual
absolute home path/username through this struct (see the privacy
tests). Free-space checking uses the stdlib's ``shutil.disk_usage`` on
whichever configured path's nearest existing ancestor can be found —
a lightweight, safe, read-only filesystem stat, not a re-implementation
of S2's block-device probing (which reports raw device capacity, not
a specific path's free space).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path

from serein.ai.models import AIStorageInfo
from serein.development._util import default_home

#: Conservative default warning floor: a handful of quantized 7-8B
#: GGUF models already run 4-6 GiB each, so headroom below this is
#: worth surfacing - not a hard requirement for any specific workload.
_LOW_SPACE_WARNING_BYTES = 5 * 1024 * 1024 * 1024


def _normalize(path: Path, home: Path) -> str:
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return str(path)


def _nearest_existing_ancestor(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return None


def _free_bytes_at(path: Path) -> int | None:
    ancestor = _nearest_existing_ancestor(path)
    if ancestor is None:
        return None
    try:
        return shutil.disk_usage(ancestor).free
    except OSError:
        return None


def build_ai_storage_info(
    env: Mapping[str, str] | None = None, home: Path | None = None
) -> AIStorageInfo:
    env = env if env is not None else os.environ
    home = home if home is not None else default_home()

    hf_home_env = env.get("HF_HOME")
    hf_home_path = Path(hf_home_env) if hf_home_env else home / ".cache" / "huggingface"
    hf_home_is_default = hf_home_env is None

    ollama_models_env = env.get("OLLAMA_MODELS")
    ollama_models_path = (
        Path(ollama_models_env) if ollama_models_env else home / ".ollama" / "models"
    )
    ollama_models_is_default = ollama_models_env is None

    free_bytes = _free_bytes_at(hf_home_path)
    low_space = free_bytes is not None and free_bytes < _LOW_SPACE_WARNING_BYTES

    return AIStorageInfo(
        hf_home=_normalize(hf_home_path, home),
        hf_home_is_default=hf_home_is_default,
        ollama_models=_normalize(ollama_models_path, home),
        ollama_models_is_default=ollama_models_is_default,
        cache_free_bytes=free_bytes,
        low_space_warning=low_space,
    )
