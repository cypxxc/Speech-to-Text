import os
import sys
import json
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from exporter import (
    format_timestamp_srt,
    format_timestamp_vtt,
    export_srt,
    export_vtt,
    export_txt,
    export_json
)

def test_srt_formatting():
    assert format_timestamp_srt(65.5) == "00:01:05,500"
    segments = [{"start": 1.0, "end": 3.5, "text": "สวัสดีครับ"}]
    srt = export_srt(segments)
    assert "1\n00:00:01,000 --> 00:00:03,500\nสวัสดีครับ" in srt

def test_vtt_formatting():
    assert format_timestamp_vtt(65.5) == "00:01:05.500"
    segments = [{"start": 1.0, "end": 3.5, "text": "สวัสดีครับ"}]
    vtt = export_vtt(segments)
    assert "WEBVTT\n" in vtt
    assert "00:00:01.000 --> 00:00:03.500\nสวัสดีครับ" in vtt

def test_txt_with_timestamps():
    segments = [{"start": 0.0, "end": 2.0, "text": "ทดสอบ"}]
    txt = export_txt("ทดสอบ", segments, include_timestamps=True)
    assert "[00:00:00 - 00:00:02] ทดสอบ" in txt

    txt_plain = export_txt("ทดสอบ", segments, include_timestamps=False)
    assert txt_plain == "ทดสอบ"

def test_json_export():
    meta = {"id": "job-1", "filename": "audio.mp3"}
    segments = [{"start": 0.0, "end": 2.0, "text": "ทดสอบ"}]
    res = export_json(meta, "ทดสอบ", segments)
    parsed = json.loads(res)
    assert parsed["job"]["id"] == "job-1"
    assert parsed["text"] == "ทดสอบ"
    assert len(parsed["segments"]) == 1
