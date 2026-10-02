"""
Thai Speech-to-Text Post-processing Auto-Correction Module.
Fixes common acoustic misrecognitions and tech/meeting jargon.
"""

import re
from typing import List, Dict, Any

# Pattern-based corrections (Regex -> Correct Thai spelling)
# Substring and pattern corrections (longer/more specific terms first)
CORRECTION_PATTERNS = [
    # Compound Tech & Cloud
    ("เทคโนโลยีสาระสนเทศ", "เทคโนโลยีสารสนเทศ"),
    ("เทคโนโลยีสะละสนเทศ", "เทคโนโลยีสารสนเทศ"),
    ("ระเบียบวาระการประชุ่ม", "ระเบียบวาระการประชุม"),
    ("การประเมินผลลัพธ์", "การประเมินผลลัพธ์"),
    ("คราวเฟิร์ส", "Cloud First"),
    ("คราวเซิร์ฟเวอร์", "คลาวด์เซิร์ฟเวอร์"),
    ("คาวคอมพิวติ้ง", "คลาวด์คอมพิวติ้ง"),
    ("เทคโนโลยีคาว", "เทคโนโลยีคลาวด์"),
    ("ปริการคาว", "บริการคลาวด์"),
    ("บริการคาว", "บริการคลาวด์"),
    ("ระบบคาว", "ระบบคลาวด์"),
    ("ดาต้าเซ็นเต้อ", "Data Center"),
    ("แอปพลิเคชั่น", "แอปพลิเคชัน"),
    ("แบบทอดสอบ", "แบบทดสอบ"),
    ("ค่ะครับคุณค่ะ", "ขอบคุณค่ะ"),

    # Tech words
    ("สะละสนเทศ", "สารสนเทศ"),
    ("สาระสนเทศ", "สารสนเทศ"),
    ("เน็ตเวิร์ค", "เน็ตเวิร์ก"),
    ("เว็ปไซต์", "เว็บไซต์"),
    ("ออนไลร์", "ออนไลน์"),
    ("ไซเบ้อ", "ไซเบอร์"),

    # Common misrecognized Thai terms
    ("ภาครัน", "ภาครัฐ"),
    ("ภาคระฐ", "ภาครัฐ"),
    ("ขับเครื่อน", "ขับเคลื่อน"),
    ("ขับเคลือน", "ขับเคลื่อน"),
    ("ปัจจุบาล", "ปัจจุบัน"),
    ("รบควร", "รบกวน"),
    ("จัดกิบ", "จัดเก็บ"),
    ("จัดเก็ป", "จัดเก็บ"),

    # Particles & typo
    ("นะคะ่", "นะคะ"),
    ("นะค่ะ", "นะคะ"),
    ("คะรับ", "ครับ"),
]

# Compile patterns for performance
COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE), repl) for p, repl in CORRECTION_PATTERNS]


def correct_text(text: str) -> str:
    """Applies Thai acoustic auto-corrections to a string."""
    if not text:
        return text

    corrected = text
    for pattern, replacement in COMPILED_PATTERNS:
        corrected = pattern.sub(replacement, corrected)
    return corrected


def correct_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Applies corrections to a list of segments in-place or copies."""
    if not segments:
        return []

    updated = []
    for seg in segments:
        seg_copy = dict(seg)
        if "text" in seg_copy and seg_copy["text"]:
            seg_copy["text"] = correct_text(seg_copy["text"])
        updated.append(seg_copy)
    return updated
