# vsg_core/subtitles/ocr/vlm_backends/paddleocr_vl_torch.py
"""
PaddleOCR-VL 1.5 backend — official transformers runtime (torch, ROCm-safe).

Runs the model through transformers' built-in ``paddleocr_vl`` support with
the checkpoint's own image preprocessing — the reference pipeline the model
was trained with. Validated against the llama.cpp path on real discs
(Lupin/Fuma VobSub 736 subs, Beheneko PGS 724 subs): reads strictly better on
VobSub at native resolution and byte-identical on PGS at matched resolution.

Two registered variants share this implementation:
    paddleocr-vl-native  — frames fed as decoded (Spotting at source res)
    paddleocr-vl-2x      — small frames (both dims < 1500px) LANCZOS-upscaled
                           2x per the official Spotting recipe; reads the
                           hardest small-glyph cases (multi-dot ellipses) at
                           ~3x the inference cost. Frames >= 1500px (PGS) are
                           never upscaled, so both variants behave identically
                           for HD content.

ROCm pitfalls this file encodes (do not "simplify" them away):
    - dtype MUST be fp16. bf16 wedges ``.to("cuda")`` in an unkillable HIP
      spin on this model's vision tower (MIOpen bf16 conv gaps; upstream
      PaddleX #5095 forces fp32 for the same reason). fp16 is lossless here:
      every bf16 weight value converts exactly.
    - generate() MUST pass use_cache=True. The checkpoint's generation_config
      ships use_cache=False, which re-runs the full ~1.3k-token sequence per
      output token (~15x slower).
    - The resolution caps MUST be set via ``image_processor.size`` with
      shortest_edge/longest_edge keys. The documented ``max_pixels`` kwarg is
      silently dropped by transformers 5.x — verify via pixel patch counts if
      touching this.
"""

import logging
import os
import re
from typing import Any

import numpy as np
import torch
from PIL import Image

from ..region_detector import Region
from . import (
    VLMBackend,
    VLMRegionResult,
    _apply_torch_gpu_limits,
    get_model_dir,
    register_vlm_backend,
)
from .paddleocr_vl import _parse_spotting_output

logger = logging.getLogger(__name__)

os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")

# Pixel budgets for the processor's smart_resize (values are total pixels).
# Defaults ship with the checkpoint; the spotting cap is the official override
# for the Spotting task and exists here ONLY to keep a 2x-upscaled small frame
# from being shrunk back under the default cap. Large frames (PGS) always use
# the default — validated as byte-identical to llama.cpp output at equal speed,
# while the spotting cap on PGS is ~1.5x slower for no accuracy gain.
_MIN_PIXELS = 112_896  # 384*294 ships as shortest_edge in preprocessor_config
_DEFAULT_MAX_PIXELS = 1280 * 28 * 28  # 1_003_520
_SPOTTING_MAX_PIXELS = 2048 * 28 * 28  # 1_605_632

# Official Spotting recipe: 2x-upscale only when BOTH dims are under this.
_UPSCALE_THRESHOLD_PX = 1500


class _PaddleOCRVLTorchBase(VLMBackend):
    """Shared implementation; variants differ only in the 2x upscale flag."""

    uses_annotated = False  # Full-frame Spotting, same contract as the GGUF backend
    upscale_2x = False

    def __init__(self, **kwargs):
        self.model_dir = get_model_dir(self.name)
        # Any: transformers' from_pretrained return stubs don't model
        # .to()/.generate() on this class family (same limitation qwen35
        # works around) — the runtime types are the HF model/processor.
        self.model: Any = None
        self.processor: Any = None

    def load(self) -> None:
        from transformers import AutoModelForImageTextToText, AutoProcessor

        _apply_torch_gpu_limits()

        model_path = str(self.model_dir)
        logger.info(f"Loading PaddleOCR-VL 1.5 (transformers) from {model_path}")

        # fp16, not bf16 — bf16 wedges the ROCm copy path for this model.
        # CPU-first + low_cpu_mem_usage per the PyTorch loading checklist.
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_path,
            dtype=torch.float16,
            low_cpu_mem_usage=True,
            attn_implementation="sdpa",
            device_map="cpu",
        )
        self.model = self.model.to("cuda").eval()

        self.processor = AutoProcessor.from_pretrained(model_path)

        vram = torch.cuda.memory_allocated() / 1024**3
        logger.info(
            f"PaddleOCR-VL 1.5 (transformers) loaded"
            f"{' [2x mode]' if self.upscale_2x else ''}. VRAM: {vram:.2f}GB"
        )

    def _generate(self, image: Image.Image, prompt: str, max_pixels: int) -> str:
        """One chat-completion round trip; returns the raw decoded text."""
        assert self.model is not None and self.processor is not None, (
            "Model not loaded. Call load() first."
        )
        # size dict is the only override path transformers actually honors.
        self.processor.image_processor.size = {
            "shortest_edge": _MIN_PIXELS,
            "longest_edge": max_pixels,
        }
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        inputs = self.processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to("cuda")
        inputs.pop("token_type_ids", None)
        with torch.inference_mode():
            out = self.model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
                use_cache=True,  # generation_config ships False — 15x slower
            )
        raw = self.processor.decode(
            out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=False
        )
        # skip_special_tokens=False is required to keep the LOC position
        # tokens, but it also keeps the EOS marker — strip it here so it
        # can't leak into subtitle text (LOC parsing only strips <|...|>).
        return raw.replace("</s>", "").strip()

    @staticmethod
    def _to_rgb(image: np.ndarray) -> np.ndarray:
        if image.ndim == 3 and image.shape[2] == 4:
            from ..annotator import rgba_to_rgb_on_black

            return rgba_to_rgb_on_black(image)
        return image

    def spotting_direct(self, image: np.ndarray) -> list[dict]:
        """Run Spotting on a full frame; returns [{'text', 'bbox'}, ...].

        Same contract as the GGUF backend: bboxes in ORIGINAL frame pixel
        coordinates regardless of any internal upscale (LOC tokens are
        normalized 0-1000, so parsing against the original dims is exact).
        """
        rgb = self._to_rgb(image)
        oh, ow = rgb.shape[:2]

        pil = Image.fromarray(rgb)
        max_pixels = _DEFAULT_MAX_PIXELS
        if (
            self.upscale_2x
            and ow < _UPSCALE_THRESHOLD_PX
            and oh < _UPSCALE_THRESHOLD_PX
        ):
            # Official recipe: LANCZOS 2x + the spotting pixel cap (without the
            # raised cap the processor would immediately downscale the upscaled
            # frame back under the default budget, undoing the work).
            pil = pil.resize((ow * 2, oh * 2), Image.Resampling.LANCZOS)
            max_pixels = _SPOTTING_MAX_PIXELS

        raw = self._generate(pil, "Spotting:", max_pixels)
        return _parse_spotting_output(raw, ow, oh)

    def ocr_single(self, image: np.ndarray) -> str:
        """OCR a single image, text only (paddle_empty recovery path)."""
        rgb = self._to_rgb(image)
        raw = self._generate(Image.fromarray(rgb), "OCR:", _DEFAULT_MAX_PIXELS)
        # OCR: mode emits no LOC tokens, but strip any specials defensively.
        return re.sub(r"<\|[^>]*\|>|</s>", "", raw).strip()

    def ocr(
        self,
        image: np.ndarray,
        regions: list[Region],
        raw_image: np.ndarray | None = None,
    ) -> list[VLMRegionResult]:
        raise NotImplementedError(
            f"{self.name} is a Spotting backend — the pipeline uses "
            "spotting_direct(); the region-based ocr() path is legacy-only."
        )

    def unload(self) -> None:
        if self.model is not None:
            del self.model
            self.model = None
        self.processor = None
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("PaddleOCR-VL 1.5 (transformers) unloaded")


@register_vlm_backend("paddleocr-vl-native")
class PaddleOCRVLTorchNative(_PaddleOCRVLTorchBase):
    """Official runtime, frames as decoded. The recommended default."""

    upscale_2x = False


@register_vlm_backend("paddleocr-vl-2x")
class PaddleOCRVLTorch2x(_PaddleOCRVLTorchBase):
    """Official runtime + 2x Spotting upscale for small (DVD) frames."""

    upscale_2x = True
