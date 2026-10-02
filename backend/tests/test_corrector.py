import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from corrector import correct_text, correct_segments
from summarizer import generate_local_summary


def test_correct_text():
    raw = "ทางภาครันมีนโยบายใช้งานปริการคาวและสะละสนเทศในปัจจุบาลเพื่อขับเครื่อนองค์กร"
    expected = "ทางภาครัฐมีนโยบายใช้งานบริการคลาวด์และสารสนเทศในปัจจุบันเพื่อขับเคลื่อนองค์กร"
    corrected = correct_text(raw)
    assert corrected == expected


def test_correct_segments():
    segs = [
        {"start": 0.0, "end": 2.0, "text": "รบควรทุกท่านทำแบบทอดสอบ"},
        {"start": 2.0, "end": 4.0, "text": "จัดกิบข้อมูลบนระบบคาว"},
    ]
    corrected = correct_segments(segs)
    assert corrected[0]["text"] == "รบกวนทุกท่านทำแบบทดสอบ"
    assert corrected[1]["text"] == "จัดเก็บข้อมูลบนระบบคลาวด์"


def test_generate_local_summary():
    text = "สวัสดีครับ ขอเปิดการประชุมเรื่องนโยบายคลาวด์ รบกวนทุกท่านส่งรายงานภายในวันศุกร์นี้"
    segs = [
        {"start": 0.0, "end": 5.0, "text": "สวัสดีครับ ขอเปิดการประชุมเรื่องนโยบายคลาวด์"},
        {"start": 5.0, "end": 10.0, "text": "รบกวนทุกท่านส่งรายงานภายในวันศุกร์นี้"},
    ]
    summary = generate_local_summary("meeting.mp4", 120.0, text, segs)
    assert summary["filename"] == "meeting.mp4"
    assert summary["duration_minutes"] == 2.0
    assert len(summary["action_items"]) > 0
    assert "ส่งรายงาน" in summary["action_items"][0]
