"""
NPU-first inference engine for cairn-ai.

Auto-selects the best available hardware: NPU > GPU > CPU.
Uses ONNX Runtime as the unified abstraction layer across
Intel, AMD, Qualcomm, and Apple NPUs.

Install: pip install cairn-ai[npu]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Execution provider priority: NPU-first, then GPU, then CPU.
# ONNX Runtime uses the first available provider in the list.
_PROVIDER_PRIORITY = [
    # NPU providers
    "QNNExecutionProvider",        # Qualcomm Hexagon NPU
    "CoreMLExecutionProvider",     # Apple Neural Engine
    "OpenVINOExecutionProvider",   # Intel Meteor Lake NPU
    "DmlExecutionProvider",        # AMD XDNA / DirectML (Windows)
    "VitisAIExecutionProvider",    # AMD XDNA (Linux)
    # GPU fallback
    "CUDAExecutionProvider",       # NVIDIA GPU
    "ROCMExecutionProvider",       # AMD GPU (Linux)
    # CPU fallback (always available)
    "CPUExecutionProvider",
]


def _get_ort():
    """Lazy import of onnxruntime."""
    try:
        import onnxruntime as ort
        return ort
    except ImportError:
        raise ImportError(
            "onnxruntime is required for inference. "
            "Install with: pip install cairn-ai[npu]"
        )


def available_providers() -> list[str]:
    """Return ONNX Runtime execution providers available on this system."""
    ort = _get_ort()
    return ort.get_available_providers()


def select_providers() -> list[str]:
    """Select the best execution providers in priority order."""
    have = set(available_providers())
    selected = [p for p in _PROVIDER_PRIORITY if p in have]
    if not selected:
        selected = ["CPUExecutionProvider"]
    return selected


def describe_hardware() -> dict[str, Any]:
    """Describe available inference hardware."""
    providers = select_providers()
    primary = providers[0]

    label_map = {
        "QNNExecutionProvider": "Qualcomm NPU (Hexagon)",
        "CoreMLExecutionProvider": "Apple Neural Engine",
        "OpenVINOExecutionProvider": "Intel NPU (OpenVINO)",
        "DmlExecutionProvider": "AMD/Intel NPU (DirectML)",
        "VitisAIExecutionProvider": "AMD NPU (Vitis AI)",
        "CUDAExecutionProvider": "NVIDIA GPU (CUDA)",
        "ROCMExecutionProvider": "AMD GPU (ROCm)",
        "CPUExecutionProvider": "CPU",
    }

    return {
        "primary": label_map.get(primary, primary),
        "primary_provider": primary,
        "is_npu": primary in (
            "QNNExecutionProvider", "CoreMLExecutionProvider",
            "OpenVINOExecutionProvider", "DmlExecutionProvider",
            "VitisAIExecutionProvider",
        ),
        "is_gpu": primary in ("CUDAExecutionProvider", "ROCMExecutionProvider"),
        "all_providers": providers,
    }


class InferenceSession:
    """Thin wrapper around onnxruntime.InferenceSession with auto hardware selection."""

    def __init__(self, model_path: str | Path, providers: list[str] | None = None):
        ort = _get_ort()
        self.providers = providers or select_providers()
        self.model_path = str(model_path)

        logger.info(
            "Loading ONNX model %s on %s",
            self.model_path, self.providers[0],
        )

        self.session = ort.InferenceSession(
            self.model_path,
            providers=self.providers,
        )

        self._input_names = [i.name for i in self.session.get_inputs()]
        self._output_names = [o.name for o in self.session.get_outputs()]

    @property
    def active_provider(self) -> str:
        """The provider actually selected by ONNX Runtime."""
        return self.session.get_providers()[0]

    def run(self, inputs: dict[str, Any]) -> list[Any]:
        """Run inference with named inputs."""
        return self.session.run(self._output_names, inputs)

    def __repr__(self) -> str:
        return (
            f"InferenceSession(model={Path(self.model_path).name}, "
            f"provider={self.active_provider})"
        )


class EmbeddingModel:
    """
    NPU-accelerated embedding model for cairn's vector search.

    Uses a quantized ONNX model (e.g. all-MiniLM-L6-v2) to generate
    embeddings locally on the best available hardware.
    """

    def __init__(self, model_dir: str | Path):
        self.model_dir = Path(model_dir)
        self._session: InferenceSession | None = None
        self._tokenizer = None

    def _ensure_loaded(self):
        if self._session is not None:
            return

        model_path = self.model_dir / "model.onnx"
        if not model_path.exists():
            quantized = self.model_dir / "model_quantized.onnx"
            if quantized.exists():
                model_path = quantized
            else:
                raise FileNotFoundError(
                    f"No ONNX model found in {self.model_dir}. "
                    f"Expected model.onnx or model_quantized.onnx"
                )

        self._session = InferenceSession(model_path)

        tokenizer_path = self.model_dir / "tokenizer.json"
        if tokenizer_path.exists():
            try:
                from tokenizers import Tokenizer
                self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
            except ImportError:
                logger.warning(
                    "tokenizers package not installed. "
                    "Install with: pip install tokenizers"
                )

    def _tokenize(self, texts: list[str]) -> dict[str, Any]:
        """Tokenize input texts."""
        import numpy as np

        if self._tokenizer is None:
            raise RuntimeError("No tokenizer loaded")

        self._tokenizer.enable_padding(
            pad_id=0, pad_token="[PAD]", length=128
        )
        self._tokenizer.enable_truncation(max_length=128)

        encoded = self._tokenizer.encode_batch(texts)

        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array(
            [e.attention_mask for e in encoded], dtype=np.int64
        )
        token_type_ids = np.zeros_like(input_ids)

        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids,
        }

    def embed(self, texts: list[str]) -> Any:
        """Generate embeddings for a list of texts.

        Returns numpy array of shape (len(texts), embedding_dim).
        """
        import numpy as np

        self._ensure_loaded()
        tokens = self._tokenize(texts)
        outputs = self._session.run(tokens)

        # Most sentence embedding models output token embeddings;
        # we mean-pool over the attention mask to get sentence embeddings.
        token_embeddings = outputs[0]  # (batch, seq_len, hidden)
        mask = tokens["attention_mask"]

        mask_expanded = np.expand_dims(mask, axis=-1).astype(np.float32)
        summed = np.sum(token_embeddings * mask_expanded, axis=1)
        counts = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
        embeddings = summed / counts

        # L2 normalize
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.clip(norms, a_min=1e-9, a_max=None)
        return embeddings / norms

    def embed_one(self, text: str) -> Any:
        """Generate embedding for a single text. Returns 1D numpy array."""
        return self.embed([text])[0]


class LocalLLM:
    """
    Interface to a local LLM running via Ollama.

    Speaks the OpenAI-compatible API that Ollama provides,
    so cairn can swap between local and cloud models with
    zero code changes — just a config switch.

    No data leaves this machine.
    """

    def __init__(
        self,
        model: str = "qwen2.5:7b",
        base_url: str = "http://localhost:11434",
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, payload: dict, timeout: int = 120) -> dict:
        """POST to the Ollama API."""
        import json
        import urllib.request
        import urllib.error

        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot reach Ollama at {self.base_url}. "
                f"Is it running? Error: {e}"
            )

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 500,
        temperature: float = 0.7,
    ) -> str:
        """Send a chat completion request. Returns the response text."""
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        result = self._post("/v1/chat/completions", payload)
        choices = result.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "")

    def ask(self, prompt: str, system: str = "", **kwargs) -> str:
        """Simple single-turn query."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, **kwargs)

    def list_models(self) -> list[str]:
        """List models available in Ollama."""
        import json
        import urllib.request

        url = f"{self.base_url}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def is_available(self) -> bool:
        """Check if Ollama is reachable and has this model."""
        return self.model in self.list_models()

    def __repr__(self) -> str:
        return f"LocalLLM(model={self.model}, url={self.base_url})"
