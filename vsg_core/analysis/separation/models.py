# vsg_core/analysis/separation/models.py
"""
Model metadata, quality database, and constants for audio source separation.
"""

from __future__ import annotations

import re

# Separation modes available in the UI
SEPARATION_MODES = {
    "none": None,
    "instrumental": "Instrumental",
    "vocals": "Vocals",
}

DEFAULT_MODEL = "default"

# Model quality database with SDR scores, rankings, and use-case recommendations
# Based on the audio-separator project recommendations and community testing
MODEL_QUALITY_DATABASE = {
    # BS-Roformer models - Best for vocals/instrumental separation
    "model_bs_roformer_ep_317_sdr_12.9755.ckpt": {
        "quality_tier": "S-Tier",
        "rank": 1,
        "sdr_vocals": 12.9,
        "sdr_instrumental": 17.0,
        "use_cases": ["Instrumental", "Vocals", "General Purpose"],
        "recommended": True,
        "description_override": "Highest quality vocals/instrumental separation. Best overall performance. SLOW: 2-5 min for 3-min audio.",
    },
    "model_bs_roformer_ep_368_sdr_12.9628.ckpt": {
        "quality_tier": "S-Tier",
        "rank": 2,
        "sdr_vocals": 12.9,
        "sdr_instrumental": 17.0,
        "use_cases": ["Instrumental", "Vocals", "General Purpose"],
        "recommended": True,
        "description_override": "Excellent vocals/instrumental separation. Very close to ep_317. SLOW: 2-5 min for 3-min audio.",
    },
    "deverb_bs_roformer_8_384dim_10depth.ckpt": {
        "quality_tier": "A-Tier",
        "rank": 10,
        "use_cases": ["Reverb Removal", "Cleanup"],
        "description_override": "Specialized model for removing reverb from audio.",
    },
    # MelBand Roformer models
    "mel_band_roformer_kim_ft_unwa.ckpt": {
        "quality_tier": "A-Tier",
        "rank": 5,
        "sdr_vocals": 12.4,
        "use_cases": ["Vocals"],
        "description_override": "Excellent vocals extraction with good instrumental preservation.",
    },
    "vocals_mel_band_roformer.ckpt": {
        "quality_tier": "A-Tier",
        "rank": 6,
        "sdr_vocals": 12.6,
        "use_cases": ["Vocals"],
        "description_override": "Strong vocals separation model.",
    },
    "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt": {
        "quality_tier": "A-Tier",
        "rank": 11,
        "sdr_vocals": 10.1,
        "use_cases": ["Karaoke", "Backing Vocals"],
        "description_override": "Specialized for karaoke - separates lead vocals from backing vocals.",
    },
    "model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt": {
        "quality_tier": "A-Tier",
        "rank": 4,
        "sdr_vocals": 11.4,
        "use_cases": ["Vocals", "Dialogue"],
        "description_override": "High-quality separation, good for dialogue extraction.",
    },
    "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt": {
        "quality_tier": "S-Tier",
        "rank": 9,
        "sdr_vocals": 27.9,
        "use_cases": ["Denoise", "Cleanup"],
        "description_override": "Exceptional denoise model with very high SDR.",
    },
    # MDX-Net models
    "MDX23C-8KFFT-InstVoc_HQ_2.ckpt": {
        "quality_tier": "A-Tier",
        "rank": 3,
        "use_cases": ["Instrumental", "General Purpose"],
        "recommended": True,
        "description_override": "High-quality MDX model for instrumental/vocals separation.",
    },
    "UVR-MDX-NET-Inst_HQ_4.onnx": {
        "quality_tier": "A-Tier",
        "rank": 7,
        "use_cases": ["Instrumental"],
        "description_override": "Reliable instrumental separation with good performance.",
    },
    "UVR_MDXNET_KARA_2.onnx": {
        "quality_tier": "B-Tier",
        "rank": 12,
        "use_cases": ["Karaoke"],
        "description_override": "Karaoke-specific model for backing track creation.",
    },
    # VR Architecture models - Fast but lower quality
    "Kim_Vocal_2.onnx": {
        "quality_tier": "B-Tier",
        "rank": 13,
        "use_cases": ["Vocals", "Fast Processing"],
        "description_override": "Fast vocals extraction, lower quality than Roformer models.",
    },
    "kuielab_a_vocals.onnx": {
        "quality_tier": "B-Tier",
        "rank": 14,
        "use_cases": ["Vocals", "Fast Processing"],
        "description_override": "Quick vocals separation, suitable for batch processing.",
    },
    "4_HP-Vocal-UVR.pth": {
        "quality_tier": "B-Tier",
        "rank": 15,
        "use_cases": ["Vocals", "Fast Processing"],
        "description_override": "Fast VR model for vocals extraction.",
    },
    "2_HP-UVR.pth": {
        "quality_tier": "B-Tier",
        "rank": 8,
        "use_cases": ["Instrumental", "Fast Processing"],
        "recommended": True,
        "description_override": "Fastest instrumental separation. FAST: ~20 sec for 3-min audio. Good speed/quality balance.",
    },
    "6_HP-Karaoke-UVR.pth": {
        "quality_tier": "B-Tier",
        "rank": 16,
        "use_cases": ["Karaoke", "Fast Processing"],
        "description_override": "Fast karaoke model for quick backing track creation.",
    },
    "kuielab_a_bass.onnx": {
        "quality_tier": "B-Tier",
        "rank": 17,
        "use_cases": ["Bass", "Multi-Instrument"],
        "description_override": "Specialized bass extraction model.",
    },
    "kuielab_a_drums.onnx": {
        "quality_tier": "B-Tier",
        "rank": 18,
        "use_cases": ["Drums", "Multi-Instrument"],
        "description_override": "Specialized drums extraction model.",
    },
    # Demucs models - Multi-stem separation
    "htdemucs": {
        "quality_tier": "A-Tier",
        "rank": 19,
        "use_cases": ["Multi-Instrument", "4-Stem", "General Purpose"],
        "recommended": True,
        "sdr_vocals": 7.0,  # Approximate, varies by stem
        "description_override": "Best all-around 4-stem separation (drums/bass/other/vocals). MEDIUM: ~30-60 sec for 3-min audio.",
    },
    "htdemucs_ft": {
        "quality_tier": "A-Tier",
        "rank": 20,
        "use_cases": ["Multi-Instrument", "4-Stem"],
        "sdr_vocals": 7.2,  # Approximate, fine-tuned version
        "description_override": "Fine-tuned version of htdemucs with slightly better performance. MEDIUM: ~30-60 sec for 3-min audio.",
    },
    "htdemucs_6s": {
        "quality_tier": "A-Tier",
        "rank": 21,
        "use_cases": ["Multi-Instrument", "6-Stem", "Advanced"],
        "sdr_vocals": 6.8,  # Approximate
        "description_override": "6-stem separation including drums/bass/other/vocals/guitar/piano. MEDIUM: ~30-60 sec for 3-min audio.",
    },
    "htdemucs.yaml": {
        "quality_tier": "A-Tier",
        "rank": 19,
        "use_cases": ["Multi-Instrument", "4-Stem", "General Purpose"],
        "recommended": True,
        "sdr_vocals": 7.0,
        "description_override": "Best all-around 4-stem separation (drums/bass/other/vocals). MEDIUM: ~30-60 sec for 3-min audio.",
    },
    "htdemucs_ft.yaml": {
        "quality_tier": "A-Tier",
        "rank": 20,
        "use_cases": ["Multi-Instrument", "4-Stem"],
        "sdr_vocals": 7.2,
        "description_override": "Fine-tuned version of htdemucs with slightly better performance. MEDIUM: ~30-60 sec for 3-min audio.",
    },
    "htdemucs_6s.yaml": {
        "quality_tier": "A-Tier",
        "rank": 21,
        "use_cases": ["Multi-Instrument", "6-Stem", "Advanced"],
        "sdr_vocals": 6.8,
        "description_override": "6-stem separation including drums/bass/other/vocals/guitar/piano. MEDIUM: ~30-60 sec for 3-min audio.",
    },
}

# Curated list of best-performing models for UI selection.
# These are intentionally limited to avoid overwhelming users with large lists.
CURATED_MODELS: list[dict[str, str]] = [
    {
        "name": "Demucs v4: htdemucs",
        "filename": "htdemucs",
        "description": "Best all-round 4-stem separation (drums/bass/other/vocals) with strong balance.",
    },
    {
        "name": "BS-Roformer Viperx 1297 (Highest Quality)",
        "filename": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        "description": "Top quality 2-stem (vocals SDR 12.9, instrumental SDR 17.0). Best overall performance.",
    },
    {
        "name": "BS-Roformer Viperx 1296",
        "filename": "model_bs_roformer_ep_368_sdr_12.9628.ckpt",
        "description": "High quality 2-stem (vocals SDR 12.9, instrumental SDR 17.0). Alternative to 1297.",
    },
    {
        "name": "MDX23C: InstVoc HQ",
        "filename": "model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt",
        "description": "High-quality 2-stem instrumental/vocals separation. Good for dialogue extraction.",
    },
    {
        "name": "MelBand Roformer Kim",
        "filename": "mel_band_roformer_kim_ft_unwa.ckpt",
        "description": "Reliable vocals extraction with good instrumental preservation (SDR 12.4).",
    },
]


def extract_sdr_from_filename(
    filename: str,
) -> tuple[float | None, float | None]:
    """
    Extract SDR scores from model filename if embedded.

    Many models have SDR scores in their filenames like:
    - model_bs_roformer_ep_317_sdr_12.9755.ckpt -> SDR 12.9755
    - mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt -> SDR 10.1956

    Returns:
        Tuple of (sdr_vocals, sdr_instrumental) if found, (None, None) otherwise.
    """
    # Look for "sdr_XX.XXXX" pattern in filename
    sdr_pattern = r"sdr[_-]?(\d+\.?\d*)"
    match = re.search(sdr_pattern, filename.lower())

    if match:
        sdr_value = float(match.group(1))
        # For 2-stem models, the SDR is typically vocals SDR
        # Instrumental SDR is usually higher (approximate as +4)
        return (sdr_value, sdr_value + 4.0)

    return (None, None)


def enrich_model_with_quality_data(model: dict) -> dict:
    """
    Enrich model metadata with quality database information.

    Adds:
    - Quality tier (S-Tier, A-Tier, B-Tier)
    - Ranking (1 = best)
    - Use case recommendations
    - SDR scores (from database or filename)
    - Better descriptions

    Args:
        model: Model dict with basic info

    Returns:
        Enhanced model dict with quality metadata
    """
    filename = model.get("filename", "")

    # Check if we have quality data for this model
    quality_data = MODEL_QUALITY_DATABASE.get(filename, {})

    # If we have quality data, merge it
    if quality_data:
        # Override SDR if provided in quality database
        if "sdr_vocals" in quality_data:
            model["sdr_vocals"] = quality_data["sdr_vocals"]
        if "sdr_instrumental" in quality_data:
            model["sdr_instrumental"] = quality_data["sdr_instrumental"]

        # Add quality metadata
        model["quality_tier"] = quality_data.get("quality_tier", "C-Tier")
        model["rank"] = quality_data.get("rank", 999)
        model["use_cases"] = quality_data.get("use_cases", [])
        model["recommended"] = quality_data.get("recommended", False)

        # Override description if provided
        if "description_override" in quality_data:
            model["description"] = quality_data["description_override"]

    # If no SDR data yet, try to extract from filename
    if not model.get("sdr_vocals"):
        sdr_vocals, sdr_instrumental = extract_sdr_from_filename(filename)
        if sdr_vocals:
            model["sdr_vocals"] = sdr_vocals
        if sdr_instrumental and not model.get("sdr_instrumental"):
            model["sdr_instrumental"] = sdr_instrumental

    # Set default quality tier if not set
    if "quality_tier" not in model:
        model["quality_tier"] = "C-Tier"
        model["rank"] = 999

    return model
