import json
from typing import List, Dict, Any, Optional


def _split_seconds(seconds: float):
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours = total_ms // 3600000
    remainder = total_ms % 3600000
    minutes = remainder // 60000
    remainder = remainder % 60000
    secs = remainder // 1000
    ms = remainder % 1000
    return hours, minutes, secs, ms


def format_timestamp_srt(seconds: float) -> str:
    hours, minutes, secs, ms = _split_seconds(seconds)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    hours, minutes, secs, ms = _split_seconds(seconds)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def format_timestamp_hms(seconds: float) -> str:
    hours, minutes, secs, _ = _split_seconds(seconds)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def export_srt(segments: List[Dict[str, Any]]) -> str:
    lines = []
    for i, seg in enumerate(segments, start=1):
        start_ts = format_timestamp_srt(seg.get("start", 0.0))
        end_ts = format_timestamp_srt(seg.get("end", 0.0))
        text = str(seg.get("text", "")).strip()
        lines.append(f"{i}\n{start_ts} --> {end_ts}\n{text}\n")
    return "\n".join(lines).strip() + "\n" if lines else ""


def export_vtt(segments: List[Dict[str, Any]]) -> str:
    lines = ["WEBVTT\n"]
    for i, seg in enumerate(segments, start=1):
        start_ts = format_timestamp_vtt(seg.get("start", 0.0))
        end_ts = format_timestamp_vtt(seg.get("end", 0.0))
        text = str(seg.get("text", "")).strip()
        lines.append(f"{i}\n{start_ts} --> {end_ts}\n{text}\n")
    return "\n".join(lines).strip() + "\n"


def export_txt(
    text: str,
    segments: Optional[List[Dict[str, Any]]] = None,
    include_timestamps: bool = False,
) -> str:
    if include_timestamps and segments:
        lines = []
        for seg in segments:
            start_ts = format_timestamp_hms(seg.get("start", 0.0))
            end_ts = format_timestamp_hms(seg.get("end", 0.0))
            t = str(seg.get("text", "")).strip()
            lines.append(f"[{start_ts} - {end_ts}] {t}")
        return "\n".join(lines)
    return text.strip()


def export_json(job_meta: Dict[str, Any], text: str, segments: List[Dict[str, Any]]) -> str:
    payload = {
        "job": job_meta,
        "text": text,
        "segments": segments,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
