# tests/test_flac_conversion.py
"""Eligibility and skip-logic tests for the FLAC ConversionStep.

The conversion itself (ffmpeg encode + MD5 verify) requires real media and
is validated against sample files; these tests pin down the pure gating
logic that decides *whether* a track is converted at all.
"""

from vsg_core.orchestrator.steps.conversion_step import (
    correction_skip_reason,
    eligibility_skip_reason,
)


def _stream(
    codec_name: str = "pcm_s24le",
    profile: str | None = None,
    channels: int = 6,
    **extra,
) -> dict:
    stream = {"codec_name": codec_name, "channels": channels, **extra}
    if profile is not None:
        stream["profile"] = profile
    return stream


class TestEligibility:
    def test_pcm_is_eligible(self):
        assert eligibility_skip_reason("A_PCM/INT/LIT", _stream()) is None

    def test_ms_acm_extracted_wav_is_eligible(self):
        assert eligibility_skip_reason("A_MS/ACM", _stream("pcm_s16le")) is None

    def test_plain_truehd_is_eligible(self):
        assert eligibility_skip_reason("A_TRUEHD", _stream("truehd")) is None

    def test_truehd_atmos_is_skipped(self):
        reason = eligibility_skip_reason(
            "A_TRUEHD", _stream("truehd", profile="Dolby TrueHD + Dolby Atmos")
        )
        assert reason is not None and "object-based" in reason

    def test_dts_hd_ma_is_eligible(self):
        assert (
            eligibility_skip_reason("A_DTS", _stream("dts", profile="DTS-HD MA"))
            is None
        )

    def test_dts_x_is_skipped(self):
        reason = eligibility_skip_reason(
            "A_DTS", _stream("dts", profile="DTS-HD MA + DTS:X")
        )
        assert reason is not None and "object-based" in reason

    def test_lossy_dts_profiles_are_skipped(self):
        for profile in ("DTS", "DTS-ES", "DTS 96/24", "DTS-HD HRA", "DTS Express"):
            reason = eligibility_skip_reason("A_DTS", _stream("dts", profile=profile))
            assert reason is not None and "not lossless" in reason, profile

    def test_dts_without_profile_is_skipped(self):
        assert eligibility_skip_reason("A_DTS", _stream("dts")) is not None

    def test_lossy_codecs_are_skipped(self):
        for codec_id in ("A_AC3", "A_EAC3", "A_AAC", "A_OPUS", "A_VORBIS"):
            reason = eligibility_skip_reason(codec_id, _stream())
            assert reason is not None and "not lossless" in reason, codec_id

    def test_already_flac_is_skipped(self):
        reason = eligibility_skip_reason("A_FLAC", _stream("flac"))
        assert reason == "already FLAC"

    def test_missing_probe_is_skipped(self):
        assert eligibility_skip_reason("A_PCM/INT/LIT", None) is not None

    def test_more_than_eight_channels_is_skipped(self):
        reason = eligibility_skip_reason("A_PCM/INT/LIT", _stream(channels=10))
        assert reason is not None and "channels" in reason

    def test_non_pcm_data_under_pcm_codec_id_is_skipped(self):
        assert eligibility_skip_reason("A_PCM/INT/LIT", _stream("ac3")) is not None


class TestCorrectionSkip:
    def test_no_flags_no_skip(self):
        assert correction_skip_reason("Source 2", True, {}, {}, {}) is None

    def test_stepping_flag_blocks_same_source(self):
        flags = {"Source 2_1": {"subs_only": False}}
        reason = correction_skip_reason("Source 2", True, flags, {}, {})
        assert reason is not None and "stepping" in reason

    def test_stepping_flag_does_not_block_other_source(self):
        flags = {"Source 2_1": {"subs_only": False}}
        assert correction_skip_reason("Source 3", True, flags, {}, {}) is None

    def test_subs_only_stepping_does_not_block_audio(self):
        flags = {"Source 2_1": {"subs_only": True}}
        assert correction_skip_reason("Source 2", True, flags, {}, {}) is None

    def test_disabled_stepping_does_not_block(self):
        flags = {"Source 2_1": {"subs_only": False}}
        assert correction_skip_reason("Source 2", False, flags, {}, {}) is None

    def test_pal_drift_blocks(self):
        reason = correction_skip_reason("Source 2", True, {}, {"Source 2_1": {}}, {})
        assert reason is not None and "PAL" in reason

    def test_linear_drift_blocks(self):
        reason = correction_skip_reason("Source 2", True, {}, {}, {"Source 2_1": {}})
        assert reason is not None and "linear" in reason
