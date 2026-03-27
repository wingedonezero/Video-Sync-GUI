# vsg_core/subtitles/ocr/vlm_backends/qwen35.py
"""
Qwen3.5 VLM backend — archival quality OCR with annotated box approach.

Uses full-frame images with numbered region boxes drawn on them.
The model reads box numbers and reports text per region, providing
guaranteed region-to-text mapping.

Benchmarks (RX 7900 GRE, ROCm 7.2):
    Qwen3.5-4B: 828ms/sub avg, 286s full episode, 8.55GB VRAM
    Near-perfect accuracy across 344 subtitles.

Critical notes:
    - Must use enable_thinking=False in chat template (NOT generation_config)
    - Uses attn_implementation="sdpa" for ROCm (memory-efficient attention)
    - Must use CPU-first loading to avoid VRAM spikes
    - Hallucinate on crops — only use annotated full-frame approach
"""

import logging
import os
import re

import numpy as np
import torch
from PIL import Image

from . import VLMBackend, VLMRegionResult, get_model_dir, register_vlm_backend
from ..region_detector import Region

logger = logging.getLogger(__name__)

os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")

PROMPT = """Read the text in each numbered box in the image.
For each box, report the box number and the exact text inside it.
Format your response as:
1: [text in box 1]
2: [text in box 2]
If a box has multiple lines, keep them on one line separated by \\N.
Only output the numbered lines, nothing else."""


class Qwen35Base(VLMBackend):
    """Base class for Qwen3.5 variants."""

    uses_annotated = True  # Needs full frame with numbered boxes

    def __init__(self, model_size: str = "4B", **kwargs):
        self.model_size = model_size
        self.model_dir = get_model_dir(f"qwen35-{model_size.lower()}")
        self.model = None
        self.processor = None

    def load(self) -> None:
        from transformers import AutoModelForImageTextToText, AutoProcessor

        model_path = str(self.model_dir)
        logger.info(f"Loading Qwen3.5-{self.model_size} from {model_path}")

        # CPU-first loading to avoid VRAM spikes
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_path,
            dtype=torch.bfloat16,
            trust_remote_code=True,
            low_cpu_mem_usage=True,
            attn_implementation="sdpa",
            device_map="cpu",
        )
        self.model = self.model.to("cuda")
        self.model.eval()

        # Disable thinking for models that support it
        if hasattr(self.model, "generation_config"):
            self.model.generation_config.thinking = {"type": "disabled"}
            self.model.generation_config.max_new_tokens = 512
            self.model.generation_config.do_sample = False

        self.processor = AutoProcessor.from_pretrained(
            model_path, trust_remote_code=True
        )

        vram = torch.cuda.memory_allocated() / 1024**3
        logger.info(f"Qwen3.5-{self.model_size} loaded. VRAM: {vram:.2f}GB")

    def ocr(
        self,
        image: np.ndarray,
        regions: list[Region],
        raw_image: np.ndarray | None = None,
    ) -> list[VLMRegionResult]:
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        pil_img = Image.fromarray(image) if isinstance(image, np.ndarray) else image

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": pil_img},
                    {"type": "text", "text": PROMPT},
                ],
            }
        ]

        # enable_thinking=False in chat template is the correct way
        # to disable thinking (NOT generation_config.thinking)
        text_in = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        inputs = self.processor(
            text=[text_in], images=[pil_img], return_tensors="pt", padding=True
        ).to(self.model.device)

        gen_kwargs = {
            "max_new_tokens": 512,
            "do_sample": False,
        }

        # Sync before timing to ensure GPU is ready
        torch.cuda.synchronize()

        with torch.inference_mode():
            output = self.model.generate(**inputs, **gen_kwargs)

        # Sync after to ensure GPU work is complete
        torch.cuda.synchronize()

        decoded = self.processor.tokenizer.decode(
            output[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
        ).strip()

        del inputs, output

        return self._parse_output(decoded, regions)

    def unload(self) -> None:
        if self.model is not None:
            del self.model
            self.model = None
        if self.processor is not None:
            del self.processor
            self.processor = None
        torch.cuda.empty_cache()
        logger.info(f"Qwen3.5-{self.model_size} unloaded")

    @staticmethod
    def _parse_output(
        text: str, regions: list[Region]
    ) -> list[VLMRegionResult]:
        """
        Parse numbered output into region results.

        Handles multi-line continuations where the model outputs:
            1: First line of text,
            second line continues here.
            2: Next region text
        """
        results = []
        lines = text.strip().split("\n")

        # Build mapping from region_id to text
        region_texts: dict[int, str] = {}
        current_rid: int | None = None
        for line in lines:
            match = re.match(r"(\d+)\s*[.:]\s*(.+)", line.strip())
            if match:
                current_rid = int(match.group(1))
                txt = match.group(2).strip()
                region_texts[current_rid] = txt
            elif current_rid is not None and line.strip():
                # Continuation line — append to current region with \N
                region_texts[current_rid] += "\\N" + line.strip()

        # Map to regions
        for region in regions:
            txt = region_texts.get(region.region_id, "")
            results.append(
                VLMRegionResult(
                    region_id=region.region_id,
                    text=txt,
                    raw_output=text,
                )
            )

        return results


@register_vlm_backend("qwen35-4b")
class Qwen35_4B(Qwen35Base):
    def __init__(self, **kwargs):
        super().__init__(model_size="4B", **kwargs)
