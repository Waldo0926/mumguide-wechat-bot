"""Sentence vectors for the chunk index, from a small local model. Optional: without the packages in
requirements-rag.txt, or with WXBOT_EMBED_MODEL=off, search is lexical only.

The model is the ONNX export of BAAI/bge-small-zh-v1.5 (about 90 MB, downloaded once from Hugging Face into
data/models), run with onnxruntime on the CPU: a short question takes milliseconds. No service, no key, no
cost. This is what fastembed does for the same model, without fastembed: it pins pillow below 13, which
has known vulnerabilities, for image models this bot never uses.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol

from . import config

log = logging.getLogger(__name__)

# Model name -> (Hugging Face repo with the ONNX export, file in it). Any other name is read as "repo:file".
ONNX = {"BAAI/bge-small-zh-v1.5": ("Qdrant/bge-small-zh-v1.5", "model_optimized.onnx")}
MAX_TOKENS = 512
# bge-*-zh is trained with this instruction in front of short queries (not passages).
BGE_ZH_QUERY = "为这个句子生成表示以用于检索相关文章："


class Embedder(Protocol):
    name: str

    def passages(self, texts: list[str]) -> Any:
        """float32 array, one unit-length row per text."""

    def query(self, text: str) -> Any:
        """float32 vector of unit length."""


def _unit(rows: Any) -> Any:
    import numpy as np
    rows = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(rows, axis=-1, keepdims=True)
    return rows / np.where(norms == 0, 1, norms)


class OnnxEmbedder:
    """BERT-style encoder: the [CLS] vector, normalised (how bge is meant to be pooled)."""

    def __init__(self, name: str, cache_dir: str):
        import onnxruntime
        from huggingface_hub import snapshot_download
        from tokenizers import Tokenizer
        repo, model_file = ONNX[name] if name in ONNX else name.split(":", 1)
        path = snapshot_download(repo, cache_dir=cache_dir, allow_patterns=[model_file, "tokenizer.json"])
        self.name = name
        self.tokenizer = Tokenizer.from_file(os.path.join(path, "tokenizer.json"))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        self.tokenizer.enable_padding()
        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = min(4, os.cpu_count() or 1)   # leave cores for the Hub on the same VPS
        self.session = onnxruntime.InferenceSession(os.path.join(path, model_file), opts,
                                                    providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.prefix = BGE_ZH_QUERY if "bge" in name.lower() and "zh" in name.lower() else ""

    def _encode(self, texts: list[str]) -> Any:
        import numpy as np
        enc = self.tokenizer.encode_batch(texts)
        feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
                "token_type_ids": np.array([e.type_ids for e in enc], dtype=np.int64)}
        out = self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0]
        return _unit(out[:, 0] if out.ndim == 3 else out)

    def passages(self, texts: list[str]) -> Any:
        import numpy as np
        return np.vstack([self._encode(texts[i:i + 16]) for i in range(0, len(texts), 16)])

    def query(self, text: str) -> Any:
        return self._encode([self.prefix + text])[0]


_cache: dict[str, Embedder | None] = {}


def load(name: str | None = None) -> Embedder | None:
    """The configured model, loaded once per process; None when vectors are off or unavailable."""
    name = config.EMBED_MODEL if name is None else name
    if not name or name.lower() == "off":
        return None
    if name not in _cache:
        try:
            config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
            # The services may write only to data/ (ProtectSystem=strict); the download cache goes there too.
            os.environ.setdefault("HF_HOME", str(config.MODELS_DIR / "hf"))
            _cache[name] = OnnxEmbedder(name, str(config.MODELS_DIR))
            log.info("embedder: %s", name)
        except ImportError:
            log.warning("onnxruntime/tokenizers are not installed (requirements-rag.txt): chunk search is lexical only")
            _cache[name] = None
        except Exception as exc:
            # A failed download must not stop mamo-sync; the next run tries again.
            log.warning("embedder %s could not load: %s", name, exc)
            return None
    return _cache[name]
