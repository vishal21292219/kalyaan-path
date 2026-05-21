"""Build animated word-by-word ASS subtitles (CapCut / Reels viral style).

ASS = Advanced SubStation Alpha format. ffmpeg's libass renderer supports
karaoke timing, per-word styling, fade animations, scale transitions.

Output is burned into the video via `ffmpeg -vf subtitles=...`

Style:
- One word at a time, dead center bottom
- Huge bold font (130px), white default with black stroke
- Yellow for emphasis question words (कौन, क्या, कैसे, क्यों)
- Red for high-impact reveal words (रहस्य, सच, अमर, श्राप, वरदान)
- Pop-in animation: scale 70% → 100% over 80ms
- Fade in/out for smoothness
"""
from __future__ import annotations

import re

# Emphasis word sets (Devanagari + Roman fallback)
HIGH_EMPHASIS = {
    "रहस्य", "सच", "अमर", "श्राप", "वरदान", "जादू", "चमत्कार", "खुलासा",
    "मौत", "जीवित", "ज़िंदा", "मारा", "खुद", "असली", "वास्तविक",
    "rahasya", "sach", "amar", "shrap", "vardaan", "khulasa", "asli",
}
MED_EMPHASIS = {
    "कौन", "क्या", "कब", "कैसे", "क्यों", "कहाँ", "कोई",
    "kaun", "kya", "kab", "kaise", "kyun", "kahan",
}


def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _style_for(word: str) -> str:
    """Decide style based on emphasis dictionaries."""
    w = word.strip(",.!?।॥;:\"'()[]")
    if w in HIGH_EMPHASIS:
        return "Red"
    if w in MED_EMPHASIS:
        return "Yellow"
    return "White"


def build_ass(
    boundaries: list[dict],
    width: int = 1080,
    height: int = 1920,
    font: str = "Devanagari Sangam MN",
    min_word_duration: float = 0.18,
) -> str:
    """Build ASS file content from word boundaries.

    boundaries: [{"text": str, "start": float, "end": float}, ...] in seconds.
    """
    # ASS colors are &HAABBGGRR (alpha-blue-green-red). Examples:
    #   White:  &H00FFFFFF
    #   Yellow: &H0000F2FF (warm yellow)
    #   Red:    &H001E1EFF (red — RR=FF, GG=1E, BB=1E)
    #   Black:  &H00000000
    # Outline is thick black stroke for readability on any background.

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2
Collisions: Normal
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: White,{font},120,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,8,2,2,60,60,520,1
Style: Yellow,{font},135,&H0000F2FF,&H0000F2FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,10,3,2,60,60,520,1
Style: Red,{font},140,&H001E1EFF,&H001E1EFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,10,3,2,60,60,520,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []
    for i, b in enumerate(boundaries):
        text = b["text"].strip()
        if not text:
            continue
        # Skip pure punctuation
        if re.fullmatch(r"[\.\,\?\!\।\॥;:\-]+", text):
            continue

        start = b["start"]
        end = b["end"]

        # Ensure each word is visible long enough to read
        if end - start < min_word_duration:
            end = start + min_word_duration

        # Don't overlap into next word (pad slight gap before next)
        if i + 1 < len(boundaries):
            next_start = boundaries[i + 1]["start"]
            if end > next_start:
                end = max(start + min_word_duration * 0.6, next_start - 0.02)

        style = _style_for(text)

        # Animation: pop-in scale 70→100 over first 80ms, smooth fade in/out
        # \fad(in_ms, out_ms) — quick fade for smoothness
        # \fscx, \fscy — scale percentage
        # \t(start_ms, end_ms, ...) — animate property over time
        ass_text = (
            f"{{\\fad(40,40)"
            f"\\fscx70\\fscy70"
            f"\\t(0,80,\\fscx100\\fscy100)"
            f"}}{text}"
        )
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{ass_text}"
        )

    return header + "\n".join(events) + "\n"


def write_ass_file(boundaries: list[dict], out_path, **kwargs) -> None:
    """Convenience: write ASS content to file."""
    content = build_ass(boundaries, **kwargs)
    from pathlib import Path
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
