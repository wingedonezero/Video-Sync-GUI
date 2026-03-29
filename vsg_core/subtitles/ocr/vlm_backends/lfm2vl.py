# vsg_core/subtitles/ocr/vlm_backends/lfm2vl.py
"""
LFM2-VL backend — Liquid AI's fast VLM with SigLIP2 NaFlex vision encoder.

Crop-based: sends each region as a separate image.
SigLIP2 NaFlex adapts vision token count to image size — small crops
produce fewer tokens, making this very fast on subtitle images.

Benchmarks (RX 7900 GRE, ROCm 7.2):
    LFM2-VL-450M: 126ms/sub avg, 45s full episode, 0.85GB VRAM
"""

import logging

import numpy as np
import torch
from PIL import Image

from . import VLMBackend, VLMRegionResult, _apply_torch_gpu_limits, get_model_dir, register_vlm_backend
from ..annotator import crop_region
from ..region_detector import Region

logger = logging.getLogger(__name__)


class LFM2VLBase(VLMBackend):
    """Base class for LFM2-VL variants."""

    uses_annotated = False  # Crop-based

    def __init__(self, variant: str = "450M", **kwargs):
        self.variant = variant
        self.model_dir = get_model_dir(f"lfm2vl-{variant.lower()}")
        self.model = None
        self.processor = None

    def load(self) -> None:
        from transformers import AutoModelForImageTextToText, AutoProcessor

        _apply_torch_gpu_limits()

        model_path = str(self.model_dir)
        logger.info(f"Loading LFM2-VL-{self.variant} from {model_path}")

        self.processor = AutoProcessor.from_pretrained(model_path)
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_path,
            dtype=torch.float16,
            low_cpu_mem_usage=True,
            attn_implementation="sdpa",
            device_map="cpu",
        )
        self.model = self.model.to("cuda")
        self.model.eval()

        vram = torch.cuda.memory_allocated() / 1024**3
        logger.info(f"LFM2-VL-{self.variant} loaded. VRAM: {vram:.2f}GB")

    def ocr(
        self,
        image: np.ndarray,
        regions: list[Region],
        raw_image: np.ndarray | None = None,
    ) -> list[VLMRegionResult]:
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        source = raw_image if raw_image is not None else image
        results = []

        for region in regions:
            crop = crop_region(source, region, padding=4)
            pil = Image.fromarray(crop).convert("RGB")

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": pil},
                        {"type": "text", "text": "Read the text."},
                    ],
                }
            ]
            text_in = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.processor(
                text=[text_in], images=[pil], return_tensors="pt", padding=True
            ).to(self.model.device)

            torch.cuda.synchronize()

            with torch.inference_mode():
                out = self.model.generate(
                    **inputs, max_new_tokens=128, do_sample=False
                )

            torch.cuda.synchronize()

            decoded = self.processor.batch_decode(
                out[:, inputs["input_ids"].shape[1] :], skip_special_tokens=True
            )[0].strip()

            del inputs, out

            results.append(
                VLMRegionResult(
                    region_id=region.region_id,
                    text=decoded,
                    raw_output=decoded,
                )
            )

        return results

    def unload(self) -> None:
        if self.model is not None:
            del self.model
            self.model = None
        if self.processor is not None:
            del self.processor
            self.processor = None
        torch.cuda.empty_cache()
        logger.info(f"LFM2-VL-{self.variant} unloaded")


@register_vlm_backend("lfm2vl-450m")
class LFM2VL_450M(LFM2VLBase):
    def __init__(self, **kwargs):
        super().__init__(variant="450M", **kwargs)
