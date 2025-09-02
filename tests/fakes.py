# tests/fakes.py
from typing import List, Callable, Optional
import json
from datetime import datetime
from pathlib import Path

class FakeCommandRunner:
    """
    Stand-in for vsg_core.process.CommandRunner used by tests.
    - Captures all calls in self.calls
    - Returns minimal, deterministic outputs so no real tools or media are needed.
    """
    def __init__(self, config: dict, log_callback: Callable[[str], None]):
        self.config = config
        self.log = log_callback
        self.calls: List[List[str]] = []

    def _log_message(self, message: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.log(f'[{ts}] {message}')

    def run(self, cmd: List[str], tool_paths: dict) -> Optional[str]:
        self.calls.append(cmd)
        self._log_message('$ ' + ' '.join(str(c) for c in cmd))
        if not cmd:
            return None

        tool = cmd[0]

        # -------- mkvmerge --------
        if tool == 'mkvmerge':
            # Info query (-J)
            if '-J' in cmd:
                try:
                    fn = cmd[cmd.index('-J') + 1]
                except Exception:
                    fn = ''
                name = Path(str(fn)).name.lower()

                if name == 'ref.mkv':
                    data = {
                        "tracks": [
                            {"id": 0, "type": "video",
                             "properties": {
                                 "codec_id": "V_MPEG4/ISO/AVC",
                                 "language": "und",
                                 "track_name": "Ref Video"
                             }}
                        ],
                        "attachments": []
                    }
                elif name == 'sec.mkv':
                    data = {
                        "tracks": [
                            {"id": 0, "type": "audio",
                             "properties": {
                                 "codec_id": "A_AC3",
                                 "language": "eng",
                                 "track_name": "Sec AC3"
                             }}
                        ],
                        "attachments": []
                    }
                elif name == 'ter.mkv':
                    data = {
                        "tracks": [
                            {"id": 0, "type": "subtitles",
                             "properties": {
                                 "codec_id": "S_TEXT/UTF8",
                                 "language": "eng",
                                 "track_name": "Ter SRT"
                             }}
                        ],
                        "attachments": []
                    }
                else:
                    data = {"tracks": [], "attachments": []}
                return json.dumps(data)

            # Merge via options file -> pretend success
            if any(str(a).startswith('@') for a in cmd[1:]):
                return "OK"
            return ""

        # -------- mkvextract --------
        if tool == 'mkvextract':
            if 'chapters' in cmd:
                # Valid minimal chapters XML
                return """<?xml version="1.0" encoding="UTF-8"?>
<Chapters>
  <EditionEntry>
    <ChapterAtom>
      <ChapterTimeStart>00:00:00.000000000</ChapterTimeStart>
      <ChapterDisplay>
        <ChapterString>Intro</ChapterString>
        <ChapterLanguage>und</ChapterLanguage>
      </ChapterDisplay>
    </ChapterAtom>
    <ChapterAtom>
      <ChapterTimeStart>00:00:10.000000000</ChapterTimeStart>
      <ChapterDisplay>
        <ChapterString>Scene 2</ChapterString>
        <ChapterLanguage>und</ChapterLanguage>
      </ChapterDisplay>
    </ChapterAtom>
  </EditionEntry>
</Chapters>
"""
            # Track/attachment extraction -> succeed quietly
            if 'tracks' in cmd or 'attachments' in cmd:
                return ""

        # -------- ffprobe --------
        if tool == 'ffprobe':
            joined = ' '.join(cmd)
            # Duration probe
            if 'format=duration' in joined:
                return "60.0"
            # Keyframe probe for chapter snapping
            if 'packet=pts_time,flags' in joined:
                return json.dumps({
                    "packets": [
                        {"pts_time": "0.000",  "flags": "K"},
                        {"pts_time": "5.000",  "flags": ""},
                        {"pts_time": "10.000", "flags": "K"}
                    ]
                })

        # -------- ffmpeg --------
        if tool == 'ffmpeg':
            # Simulate SRT -> ASS conversion by creating the output file
            # Pattern: ffmpeg -y -i <in.srt> <out.ass>
            try:
                out_path = Path(cmd[-1])
                if out_path.suffix.lower() == '.ass':
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(
                        "[Script Info]\nScriptType: v4.00+\n"
                        "[V4+ Styles]\n"
                        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
                        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                        "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n"
                        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n",
                        encoding="utf-8"
                    )
            except Exception:
                pass
            return ""

        # -------- videodiff --------
        if tool == 'videodiff':
            # Return specific delays so tests can assert sync math:
            # SEC = +120 ms (use itsoffset so no sign flip)
            # TER = -80 ms (use ss so pipeline flips sign to negative)
            try:
                target = str(cmd[-1]).lower()
            except Exception:
                target = ""
            if target.endswith('sec.mkv'):
                return "[Result] itsoffset: 0.12000s   error: 0.50"
            if target.endswith('ter.mkv'):
                return "[Result] ss: 0.08000s   error: 0.50"
            return "[Result] itsoffset: 0.00000s   error: 0.50"

        # Default: succeed with empty stdout
        return ""
