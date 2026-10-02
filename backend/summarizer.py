"""
Meeting Summarizer module.
Supports offline extractive summarization and optional LLM generative summarization.
"""

import os
import re
from typing import List, Dict, Any, Optional


def extract_key_phrases(text: str) -> List[str]:
    """Extract frequent and significant keywords from Thai text."""
    # Common Thai stop words to skip
    stop_words = {
        "ที่", "และ", "ใน", "การ", "ความ", "เป็น", "มี", "ได้", "ให้", "จะ", "ก็",
        "ว่า", "ของ", "กับ", "นี้", "ไม่", "แต่", "โดย", "จาก", "หรือ", "เพื่อ",
        "ไป", "มา", "แล้ว", "ต้อง", "คน", "เรา", "ครับ", "ค่ะ", "นะคะ", "เลย", "นะ",
        "อีก", "ทาง", "ด้วย", "อยู่", "นั้น", "พวก", "กัน", "อย่าง", "ทำ", "ซึ่ง",
        "ทำไม", "อะไร", "ตรง", "ใคร", "ไหน", "บ้าง", "ท่าน", "ทุก"
    }

    # Extract words (Thai + English)
    words = re.findall(r"[A-Za-z0-9_]+|[\u0E00-\u0E7F]{3,}", text)
    freq: Dict[str, int] = {}
    for w in words:
        w_clean = w.strip()
        if len(w_clean) > 2 and w_clean not in stop_words:
            freq[w_clean] = freq.get(w_clean, 0) + 1

    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, count in sorted_words[:12]]


def generate_local_summary(
    filename: str,
    duration_sec: float,
    text: str,
    segments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Generates a structured meeting summary using intelligent text extraction."""
    duration_min = round(duration_sec / 60, 1) if duration_sec > 0 else 0.0
    key_phrases = extract_key_phrases(text)

    # Keywords that indicate actions, decisions, and important points in Thai meetings
    action_keywords = [
        "รบกวน", "ขอให้", "มอบหมาย", "กำหนด", "ส่ง", "สรุป", "ติดตาม", "ต้องทำ",
        "แบบทดสอบ", "รายงาน", "เสร็จสิ้น", "ส่งงาน", "เอกสาร", "ประสาน", "นัดหมาย",
        "อนุมัติ", "เห็นชอบ", "มติ", "เตรียม", "ดำเนินการ"
    ]
    topic_keywords = [
        "นโยบาย", "ระบบ", "โครงการ", "เรื่องที่", "วาระที่", "มาตรการ",
        "แนวทาง", "ปัญหา", "วัตถุประสงค์", "เป้าหมาย", "ความมั่นคง", "แผนงาน"
    ]

    action_items = []
    key_points = []
    seen_texts = set()

    for seg in segments:
        s_text = seg.get("text", "").strip()
        if len(s_text) < 10 or s_text in seen_texts:
            continue

        # Check for action items
        for ak in action_keywords:
            if ak in s_text:
                action_items.append(f"[{format_timestamp(seg.get('start', 0))}] {s_text}")
                seen_texts.add(s_text)
                break

        # Check for key topic points
        if s_text not in seen_texts:
            for tk in topic_keywords:
                if tk in s_text:
                    key_points.append(f"[{format_timestamp(seg.get('start', 0))}] {s_text}")
                    seen_texts.add(s_text)
                    break

    # Limit items for concise executive overview
    action_items = action_items[:8]
    key_points = key_points[:10]

    # Create readable executive summary paragraph
    first_meaningful_segments = [s.get("text", "").strip() for s in segments[:10] if len(s.get("text", "").strip()) > 15]
    intro_context = " ".join(first_meaningful_segments[:3]) if first_meaningful_segments else "การประชุมสัมมนาและบรรยายทั่วไป"

    summary_content = {
        "filename": filename,
        "duration_minutes": duration_min,
        "total_segments": len(segments),
        "key_phrases": key_phrases,
        "overview": f"การประชุมความยาวประมาณ {duration_min} นาที เริ่มต้นด้วยประเด็น: {intro_context}",
        "key_points": key_points if key_points else ["ไม่มีประเด็นสำคัญที่ตรวจจับได้เป็นพิเศษ"],
        "action_items": action_items if action_items else ["ไม่มีการระบุมอบหมายงานที่ชัดเจน"],
    }
    return summary_content


def format_timestamp(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"
