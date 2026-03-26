# vsg_core/subtitles/ocr/annotator.py
"""
Image annotator for VLM-based OCR.

Draws numbered region boxes on subtitle images for models that need
visual markers to map text to positions (e.g., Qwen3.5).
Also provides crop utility for models that process regions individually.
"""

import cv2
import numpy as np

from .region_detector import Region

# Distinct colors for region boxes (BGR for OpenCV)
REGION_COLORS = [
    (0, 255, 0),  # Green
    (255, 0, 0),  # Blue
    (0, 0, 255),  # Red
    (255, 255, 0),  # Cyan
    (0, 255, 255),  # Yellow
    (255, 0, 255),  # Magenta
]


def annotate_image(
    image: np.ndarray,
    regions: list[Region],
    padding: int = 4,
    label_size: float = 0.6,
) -> np.ndarray:
    """
    Draw numbered boxes around detected regions on the image.

    Args:
        image: RGB or RGBA image (RGBA will be composited on black)
        regions: List of Region objects with coordinates
        padding: Pixels of padding around each region box
        label_size: Font scale for region number labels

    Returns:
        RGB image with boxes and numbers drawn
    """
    # Ensure RGB
    if image.ndim == 3 and image.shape[2] == 4:
        # RGBA -> composite on black then work in RGB
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        rgb = (image[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    elif image.ndim == 3:
        rgb = image.copy()
    else:
        rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

    annotated = rgb.copy()

    for region in regions:
        color = REGION_COLORS[(region.region_id - 1) % len(REGION_COLORS)]

        # Draw box with padding
        x1 = max(0, region.x1 - padding)
        y1 = max(0, region.y1 - padding)
        x2 = min(annotated.shape[1], region.x2 + padding)
        y2 = min(annotated.shape[0], region.y2 + padding)

        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

        # Draw region number label above the box
        label = str(region.region_id)
        (tw, th), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, label_size, 2
        )

        # Position label above box, or inside if no room above
        label_y = y1 - 5 if y1 > th + 10 else y1 + th + 5
        label_x = x1

        # Background for label
        cv2.rectangle(
            annotated,
            (label_x, label_y - th - 4),
            (label_x + tw + 4, label_y + 4),
            color,
            -1,
        )
        cv2.putText(
            annotated,
            label,
            (label_x + 2, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            label_size,
            (0, 0, 0),
            2,
        )

    return annotated


def crop_region(
    image: np.ndarray,
    region: Region,
    padding: int = 2,
) -> np.ndarray:
    """
    Crop a region from the image with optional padding.

    Args:
        image: Source image (any format)
        region: Region to crop
        padding: Pixels of padding around the crop

    Returns:
        Cropped image
    """
    h, w = image.shape[:2]
    x1 = max(0, region.x1 - padding)
    y1 = max(0, region.y1 - padding)
    x2 = min(w, region.x2 + padding)
    y2 = min(h, region.y2 + padding)
    return image[y1:y2, x1:x2].copy()


def rgba_to_rgb_on_black(rgba: np.ndarray) -> np.ndarray:
    """Composite RGBA image onto black background, returning RGB."""
    alpha = rgba[:, :, 3:4].astype(np.float32) / 255.0
    rgb = (rgba[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return rgb
