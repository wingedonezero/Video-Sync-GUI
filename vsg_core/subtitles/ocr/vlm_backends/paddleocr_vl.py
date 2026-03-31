# vsg_core/subtitles/ocr/vlm_backends/paddleocr_vl.py
"""
PaddleOCR-VL 1.5 backend — runs via llama.cpp GGUF for fast GPU inference.

Two modes:
    Spotting (default): Full-frame image with "Spotting:" prompt.
        Returns text + per-line bounding box coordinates (LOC tokens).
        Used by the main OCR pipeline for cross-validation.
        239ms/sub avg.

    Crop-OCR (crop_mode=True): Per-line crops with "OCR:" prompt.
        Splits regions into lines, crops each, sends individually.
        Faster (112ms/sub avg) but no bounding boxes.
        Used by the style editor preview.

Benchmarks (RX 7900 GRE, ROCm 7.2, llama.cpp):
    Spotting: 239ms/sub avg, 82s full episode, ~1.7GB VRAM
    Crop-OCR: 112ms/sub avg, 38s full episode, same VRAM
    Both: 0 misreads on 344 subtitles, 100% text match.

Critical notes:
    - Must use custom chat handler (subclass Llava16ChatHandler)
    - Must monkey-patch detokenize for LOC token decoding
    - LOC tokens are at IDs 100297-101300 in the GGUF vocabulary
    - Stderr suppression via os.dup2 prevents subprocess deadlocks
"""

import base64
import logging
import re
from io import BytesIO

import numpy as np
from PIL import Image

from ..annotator import crop_region, rgba_to_rgb_on_black
from ..region_detector import Region, split_region_into_lines
from . import VLMBackend, VLMRegionResult, get_model_dir, register_vlm_backend

logger = logging.getLogger(__name__)

# LOC token mapping: token_id -> "<|LOC_N|>" string
_LOC_TOKEN_BASE = 100297
_LOC_TOKEN_COUNT = 1001  # LOC_0 through LOC_1000
_LOC_SEP_TOKEN = 101300
_LOC_MAP: dict[int, str] = {}
for _i in range(_LOC_TOKEN_COUNT):
    _LOC_MAP[_LOC_TOKEN_BASE + _i] = f"<|LOC_{_i}|>"
_LOC_MAP[_LOC_SEP_TOKEN] = "<|LOC_SEP|>"

# PaddleOCR-VL chat template (matches chat_template.jinja from the model)
_CHAT_FORMAT = (
    "{% for message in messages %}"
    '{% if message.role == "user" %}'
    "User: "
    "{% if message.content is iterable %}"
    "{% for content in message.content %}"
    '{% if content.type == "image_url" %}'
    "{% if content.image_url is string %}{{ content.image_url }}{% endif %}"
    "{% if content.image_url is mapping %}{{ content.image_url.url }}{% endif %}"
    "{% endif %}"
    "{% endfor %}"
    "{% for content in message.content %}"
    '{% if content.type == "text" %}{{ content.text }}{% endif %}'
    "{% endfor %}"
    "{% endif %}"
    "{% if message.content is string %}{{ message.content }}{% endif %}"
    "\n"
    "{% endif %}"
    '{% if message.role == "assistant" %}'
    "Assistant:\n{{ message.content }}{{ eos_token }}"
    "{% endif %}"
    "{% endfor %}"
    "{% if add_generation_prompt %}Assistant:\n{% endif %}"
)


def _parse_spotting_output(text: str, frame_w: int, frame_h: int) -> list[dict]:
    """Parse Spotting output into lines with text and pixel bboxes.

    The model outputs lines like:
        text<|LOC_x1|><|LOC_y1|>...<|LOC_x4|><|LOC_y4|>
    where LOC values are normalized 0-1000.

    Returns list of dicts with 'text' and 'bbox' (x1,y1,x2,y2) keys.
    """
    results = []
    parts = text.strip().split("\n")
    for part in parts:
        if not part.strip():
            continue
        locs = re.findall(r"<\|LOC_(\d+)\|>", part)
        text_part = re.sub(r"<\|LOC_\d+\|>", "", part).strip()
        if not text_part:
            continue
        bbox = None
        if len(locs) >= 8:
            coords = [int(loc) for loc in locs[:8]]
            # 4-point quad → axis-aligned bbox
            x1 = int(min(coords[0], coords[6]) * frame_w / 1000)
            y1 = int(min(coords[1], coords[3]) * frame_h / 1000)
            x2 = int(max(coords[2], coords[4]) * frame_w / 1000)
            y2 = int(max(coords[5], coords[7]) * frame_h / 1000)
            bbox = (x1, y1, x2, y2)
        results.append({"text": text_part, "bbox": bbox})
    return results


def _image_to_data_uri(image: np.ndarray) -> str:
    """Convert numpy RGB image to base64 data URI for llama.cpp."""
    pil = Image.fromarray(image) if isinstance(image, np.ndarray) else image
    buf = BytesIO()
    pil.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


@register_vlm_backend("paddleocr-vl")
class PaddleOCRVL(VLMBackend):
    """PaddleOCR-VL 1.5 via llama.cpp GGUF — fast OCR with positions."""

    uses_annotated = False  # Sends full-frame image, not crops or annotated

    def __init__(self, crop_mode: bool = False, **kwargs):
        self.model_dir = get_model_dir("paddleocr-vl")
        self.llm = None
        self.crop_mode = crop_mode

    def load(self) -> None:
        import os

        from llama_cpp import Llama
        from llama_cpp.llama_chat_format import Llava16ChatHandler

        model_path = str(self.model_dir / "PaddleOCR-VL-1.5.gguf")
        mmproj_path = str(self.model_dir / "PaddleOCR-VL-1.5-mmproj.gguf")

        logger.info(f"Loading PaddleOCR-VL 1.5 GGUF from {self.model_dir}")

        # Custom chat handler with correct PaddleOCR-VL template
        class _PaddleOCRVLHandler(Llava16ChatHandler):
            DEFAULT_SYSTEM_MESSAGE = None
            CHAT_FORMAT = _CHAT_FORMAT

        chat_handler = _PaddleOCRVLHandler(clip_model_path=mmproj_path, verbose=False)

        # Suppress llama.cpp C-level stderr (~10 lines per inference call).
        # When running in subprocess with stderr=PIPE, this fills the 64KB
        # pipe buffer after ~200 subs and deadlocks both processes.
        self._old_stderr_fd = os.dup(2)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull_fd, 2)
        os.close(devnull_fd)

        self.llm = Llama(
            model_path=model_path,
            chat_handler=chat_handler,
            n_ctx=4096,
            n_gpu_layers=-1,
            verbose=False,
        )

        # Monkey-patch detokenize to decode LOC tokens
        original_detokenize = self.llm.detokenize

        def _patched_detokenize(tokens, prev_tokens=None):
            result = b""
            for t in tokens:
                if t in _LOC_MAP:
                    result += _LOC_MAP[t].encode("utf-8")
                else:
                    result += original_detokenize([t])
            return result

        self.llm.detokenize = _patched_detokenize

        logger.info("PaddleOCR-VL 1.5 GGUF loaded")

    def ocr(
        self,
        image: np.ndarray,
        regions: list[Region],
        raw_image: np.ndarray | None = None,
    ) -> list[VLMRegionResult]:
        if self.llm is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        if self.crop_mode:
            return self._ocr_crop(image, regions, raw_image)
        return self._ocr_spotting(image, regions, raw_image)

    def _ocr_crop(
        self,
        image: np.ndarray,
        regions: list[Region],
        raw_image: np.ndarray | None = None,
    ) -> list[VLMRegionResult]:
        """Crop-based OCR: split regions into lines, OCR each line individually.

        Faster than Spotting (no bbox generation), produces same text + line breaks.
        Used by style editor preview.
        """
        source = raw_image if raw_image is not None else image
        results = []

        for region in regions:
            # Split region into individual text lines
            line_regions = split_region_into_lines(source, region)

            # OCR each line crop
            line_texts = []
            for line_region in line_regions:
                line_crop = crop_region(source, line_region, padding=2)

                # Ensure RGB for the model
                if line_crop.ndim == 3 and line_crop.shape[2] == 4:
                    line_crop = rgba_to_rgb_on_black(line_crop)

                data_uri = _image_to_data_uri(line_crop)

                result = self.llm.create_chat_completion(
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": data_uri}},
                                {"type": "text", "text": "OCR:"},
                            ],
                        }
                    ],
                    max_tokens=256,
                    temperature=0,
                )

                text = result["choices"][0]["message"]["content"].strip()
                if text:
                    line_texts.append(text)

            results.append(
                VLMRegionResult(
                    region_id=region.region_id,
                    text="\n".join(line_texts),
                    raw_output="\n".join(line_texts),
                )
            )

        return results

    def ocr_single(self, image: np.ndarray) -> str:
        """OCR a single image, return text only (no bboxes).

        Used for paddle_empty recovery — pixel verification found content
        but Spotting returned no lines. Send full image with "OCR:" prompt.

        Args:
            image: RGBA or RGB image (full frame or crop)

        Returns:
            OCR text, or empty string if nothing detected.
        """
        if self.llm is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        if image.ndim == 3 and image.shape[2] == 4:
            source = rgba_to_rgb_on_black(image)
        else:
            source = image

        data_uri = _image_to_data_uri(source)

        result = self.llm.create_chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": "OCR:"},
                    ],
                }
            ],
            max_tokens=256,
            temperature=0,
        )

        return result["choices"][0]["message"]["content"].strip()

    def spotting_direct(
        self,
        image: np.ndarray,
    ) -> list[dict]:
        """Run Spotting on a full-frame image, return raw lines with bboxes.

        Returns list of dicts with 'text' and 'bbox' (x1,y1,x2,y2) keys.
        This is the source-of-truth detection — no pixel regions needed.
        """
        if self.llm is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        # Ensure RGB
        if image.ndim == 3 and image.shape[2] == 4:
            source = rgba_to_rgb_on_black(image)
        else:
            source = image

        frame_h, frame_w = source.shape[:2]
        data_uri = _image_to_data_uri(source)

        result = self.llm.create_chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": "Spotting:"},
                    ],
                }
            ],
            max_tokens=512,
            temperature=0,
        )

        raw_output = result["choices"][0]["message"]["content"].strip()
        return _parse_spotting_output(raw_output, frame_w, frame_h)

    def _ocr_spotting(
        self,
        image: np.ndarray,
        regions: list[Region],
        raw_image: np.ndarray | None = None,
    ) -> list[VLMRegionResult]:
        """Spotting mode: full-frame image, returns text + per-line bboxes.

        Used by the main OCR pipeline for cross-validation with pixel regions.
        """
        source = raw_image if raw_image is not None else image
        frame_h, frame_w = source.shape[:2]

        data_uri = _image_to_data_uri(source)

        result = self.llm.create_chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": "Spotting:"},
                    ],
                }
            ],
            max_tokens=512,
            temperature=0,
        )

        raw_output = result["choices"][0]["message"]["content"].strip()

        # Parse VL output into lines with bboxes
        vl_lines = _parse_spotting_output(raw_output, frame_w, frame_h)

        # Map VL lines to pixel-detected regions by Y-center overlap
        results = []
        used_vl = set()

        for region in regions:
            region_cy = (region.y1 + region.y2) / 2
            margin = max(15, region.height * 0.5)

            # Find all VL lines whose Y center falls within this region
            matched_texts = []
            matched_bboxes = []
            for vl_idx, vl in enumerate(vl_lines):
                if vl_idx in used_vl:
                    continue
                if vl["bbox"]:
                    vl_cy = (vl["bbox"][1] + vl["bbox"][3]) / 2
                    if region.y1 - margin <= vl_cy <= region.y2 + margin:
                        matched_texts.append(vl["text"])
                        matched_bboxes.append(vl["bbox"])
                        used_vl.add(vl_idx)
                # No bbox — try text match by position in output order
                # This handles edge cases where LOC tokens weren't generated
                elif not any(v["bbox"] for v in vl_lines):
                    # No bboxes at all — fall back to sequential mapping
                    matched_texts.append(vl["text"])
                    used_vl.add(vl_idx)
                    break

            # Join matched lines with newline (ASS writer converts to \N)
            text = "\n".join(matched_texts) if matched_texts else ""

            # Use the first matched bbox for cross-validation
            vl_bbox = matched_bboxes[0] if matched_bboxes else None

            results.append(
                VLMRegionResult(
                    region_id=region.region_id,
                    text=text,
                    raw_output=raw_output,
                    vl_bbox=vl_bbox,
                )
            )

        return results

    def unload(self) -> None:
        if self.llm is not None:
            del self.llm
            self.llm = None
        # Restore stderr
        if hasattr(self, "_old_stderr_fd") and self._old_stderr_fd is not None:
            import os

            os.dup2(self._old_stderr_fd, 2)
            os.close(self._old_stderr_fd)
            self._old_stderr_fd = None
        logger.info("PaddleOCR-VL 1.5 GGUF unloaded")
