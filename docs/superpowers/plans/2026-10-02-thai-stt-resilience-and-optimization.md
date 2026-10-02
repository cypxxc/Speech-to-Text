# Thai STT Resilience, Background Jobs, and Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a disaster-resilient background transcription system with local SQLite persistence, real-time progress & streaming text, CPU speed optimization (Fast Mode beam_size=1), interactive audio-text synchronization, and multiple export formats (TXT, SRT, VTT, JSON).

**Architecture:** Replace synchronous HTTP blocking with asynchronous worker thread and SQLite job tracking. Save audio and progressive segments in `backend/data/jobs/{job_id}/`. Frontend saves active `job_id` to `localStorage` to automatically resume polling and viewing progress even if the browser is closed or refreshed.

**Tech Stack:** Python (FastAPI, SQLite3, Faster-Whisper, PyAV), Next.js 15 (React 19, Tailwind CSS, TypeScript).

## Global Constraints

- Python: Python 3.14 (64-bit) Windows.
- Backward compatibility: Retain `/api/transcribe` while adding `/api/jobs` suite.
- Device fallback: CPU mode with `int8` quantization.
- No new external databases: Use Python's built-in `sqlite3` and local file storage.
- All code comments and documentation preserved.

---

### Task 1: Backend Job Database & Storage Layer (`backend/db.py`)

**Files:**
- Create: `backend/db.py`
- Test: `backend/tests/test_db.py`

**Interfaces:**
- Produces:
  - `init_db(db_path: str = "data/jobs.db") -> None`
  - `create_job(job_id: str, filename: str, filesize: int, audio_type: str, vad_filter: bool, beam_size: int, chunk_duration: int) -> dict`
  - `update_job_status(job_id: str, status: str, progress: float = None, current_time: float = None, duration: float = None, error_message: str = None) -> None`
  - `get_job(job_id: str) -> dict | None`
  - `list_jobs(limit: int = 50) -> list[dict]`
  - `append_segment(job_id: str, segment: dict) -> None`
  - `get_segments(job_id: str) -> list[dict]`
  - `save_final_result(job_id: str, full_text: str, segments: list[dict]) -> None`

- [x] **Step 1: Write test for db initialization and CRUD operations**

```python
# backend/tests/test_db.py
import os
import shutil
import tempfile
import pytest
from db import init_db, create_job, update_job_status, get_job, list_jobs, append_segment, get_segments

@pytest.fixture
def temp_env():
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_jobs.db")
    storage_dir = os.path.join(temp_dir, "jobs_data")
    yield db_file, storage_dir
    shutil.rmtree(temp_dir, ignore_errors=True)

def test_db_crud(temp_env):
    db_file, storage_dir = temp_env
    init_db(db_file, storage_dir)
    job = create_job("job-123", "meeting.mp3", 1024, "general", True, 1, 0, db_file, storage_dir)
    assert job["id"] == "job-123"
    assert job["status"] == "queued"

    update_job_status("job-123", "processing", progress=50.0, current_time=60.0, duration=120.0, db_path=db_file)
    fetched = get_job("job-123", db_path=db_file, storage_dir=storage_dir)
    assert fetched["status"] == "processing"
    assert fetched["progress"] == 50.0

    append_segment("job-123", {"start": 0.0, "end": 2.5, "text": "สวัสดีครับ"}, storage_dir=storage_dir)
    segments = get_segments("job-123", storage_dir=storage_dir)
    assert len(segments) == 1
    assert segments[0]["text"] == "สวัสดีครับ"
```

- [x] **Step 2: Run test to verify it fails**

Run: `.\backend\venv\Scripts\pytest backend/tests/test_db.py`
Expected: FAIL (cannot import `db`)

- [x] **Step 3: Implement `backend/db.py`**

Implement SQLite initialization, connection context manager, table creation, job CRUD, and progressive file storage (`segments.jsonl` and `result.json`).

- [x] **Step 4: Run test to verify it passes**

Run: `.\backend\venv\Scripts\pytest backend/tests/test_db.py`
Expected: PASS

---

### Task 2: Subtitle & Text Exporter Module (`backend/exporter.py`)

**Files:**
- Create: `backend/exporter.py`
- Test: `backend/tests/test_exporter.py`

**Interfaces:**
- Produces:
  - `format_timestamp_srt(seconds: float) -> str` (e.g. `00:01:23,450`)
  - `format_timestamp_vtt(seconds: float) -> str` (e.g. `00:01:23.450`)
  - `export_srt(segments: list[dict]) -> str`
  - `export_vtt(segments: list[dict]) -> str`
  - `export_txt(text: str, segments: list[dict] = None, include_timestamps: bool = False) -> str`
  - `export_json(job_meta: dict, text: str, segments: list[dict]) -> str`

- [x] **Step 1: Write test for exporter functions**

```python
# backend/tests/test_exporter.py
from exporter import format_timestamp_srt, format_timestamp_vtt, export_srt, export_vtt, export_txt

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
```

- [x] **Step 2: Run test to verify it fails**

Run: `.\backend\venv\Scripts\pytest backend/tests/test_exporter.py`
Expected: FAIL

- [x] **Step 3: Implement `backend/exporter.py`**

Implement timestamp formatting with hours, minutes, seconds, milliseconds, and format generators for SRT, VTT, TXT, and JSON.

- [x] **Step 4: Run test to verify it passes**

Run: `.\backend\venv\Scripts\pytest backend/tests/test_exporter.py`
Expected: PASS

---

### Task 3: Background Worker Thread & Audio Decoding (`backend/worker.py`)

**Files:**
- Create: `backend/worker.py`
- Test: `backend/tests/test_worker.py`

**Interfaces:**
- Consumes: `backend.db`, `backend.main.get_model`
- Produces:
  - `start_transcription_job(job_id: str, audio_file_path: str, audio_type: str, vad_filter: bool, beam_size: int, chunk_duration: int, db_path: str = None, storage_dir: str = None) -> None`

- [x] **Step 1: Write test for worker queue/job processing**

```python
# backend/tests/test_worker.py
import os
import tempfile
import pytest
from db import init_db, create_job, get_job
from worker import process_job_sync

def test_worker_processing_dummy_audio(monkeypatch, tmp_path):
    db_file = str(tmp_path / "test.db")
    storage = str(tmp_path / "storage")
    init_db(db_file, storage)
    
    # Create fake audio path
    audio_path = tmp_path / "test.wav"
    audio_path.write_bytes(b"dummy")

    job = create_job("job-test", "test.wav", 10, "general", True, 1, 0, db_file, storage)
    assert job["status"] == "queued"
```

- [x] **Step 2: Implement `backend/worker.py`**

Implement `transcribe_worker(job_id, audio_path, ...)`:
- Determine audio duration using `PyAV` or audio loader.
- Stream transcription segments using `model.transcribe(..., beam_size=beam_size)`.
- Update `progress` and `current_time` in SQLite after each segment or chunk.
- Call `append_segment()` to append to `segments.jsonl` immediately.
- On completion: set `status='completed'`, save final `result.json`.
- On exception: set `status='failed'`, store `error_message`.
- Clean error handling with logging.

- [x] **Step 3: Run worker tests**

Run: `.\backend\venv\Scripts\pytest backend/tests/test_worker.py`
Expected: PASS

---

### Task 4: API Integration in `backend/main.py`

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Endpoints:
  - `POST /api/jobs`: accepts file upload and parameters, starts background thread, returns `{ "job_id": str, "status": "queued" }`.
  - `GET /api/jobs/{job_id}/progress`: returns `{ "job_id", "status", "progress", "elapsed_seconds", "estimated_remaining_seconds", "latest_segments", "segment_count" }`.
  - `GET /api/jobs/{job_id}`: returns complete job info.
  - `GET /api/jobs`: returns list of all jobs.
  - `GET /api/jobs/{job_id}/audio`: streams audio with Range header support for seeking.
  - `GET /api/jobs/{job_id}/export?format={txt|srt|vtt|json}`: returns file attachment.
  - Maintain legacy `POST /api/transcribe` for compatibility.

- [x] **Step 1: Write API tests with FastAPI TestClient**

```python
# backend/tests/test_api.py
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_jobs_list():
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```

- [x] **Step 2: Update `backend/main.py`**

Add startup event to initialize `backend/data/` and `init_db()`.
Add all new endpoints with proper error handling and Pydantic response models.

- [x] **Step 3: Run API tests**

Run: `.\backend\venv\Scripts\pytest backend/tests/test_api.py`
Expected: PASS

---

### Task 5: Frontend UI Redesign (`app/ThaiSTTApp.tsx`)

**Files:**
- Modify: `app/ThaiSTTApp.tsx`
- Modify: `app/globals.css` (if needed for styling active karaoke highlight or progress bars)

**Features to implement in UI:**
1. **Disaster Recovery & LocalStorage:**
   - On upload: store `active_job_id` in `localStorage.setItem("thai_stt_active_job", jobId)`.
   - On page mount (`useEffect`): check `localStorage` for `active_job_id`. If present, immediately resume polling `/api/jobs/{job_id}/progress`.
   - If job is completed, load full transcript and audio into player.
2. **Real-time Progress Indicator:**
   - Percentage bar (0-100%).
   - Elapsed time counter (mm:ss) and ETA remaining (mm:ss).
   - "Live Transcript" stream box that displays recognized segments as they arrive in real-time.
3. **Speed Optimization Control:**
   - Fast Mode toggle (`beam_size=1` by default for speedy CPU processing, with tooltip explaining 2x-3x speedup).
   - Precision Mode option (`beam_size=5`).
4. **Interactive Audio-Text Sync:**
   - Attach audio ref to HTML `<audio>` or `<video>` player.
   - Clicking on any segment card calls `audioRef.current.currentTime = segment.start; audioRef.current.play()`.
   - Add `onTimeUpdate` listener to audio player to detect current time and highlight active segment with smooth scrolling.
5. **Export Dropdown Menu:**
   - Dropdown with options:
     - ดาวน์โหลดข้อความ (.txt)
     - ดาวน์โหลดข้อความพร้อมเวลา (.txt)
     - ดาวน์โหลดซับไตเติล (.srt)
     - ดาวน์โหลด WebVTT (.vtt)
     - ดาวน์โหลด JSON (.json)
   - Uses `/api/jobs/{job_id}/export?format=...` directly.
6. **Job History Modal / Panel:**
   - A button in header "ประวัติการถอดเสียง (History)" that opens a drawer or modal showing past jobs.
   - User can click any past job to reload and listen/export anytime.

- [x] **Step 1: Implement the UI components and state logic in `app/ThaiSTTApp.tsx`**
- [x] **Step 2: Verify TypeScript and Next.js build**

Run: `npm run build`
Expected: Build succeeds with 0 errors.

---

### Task 6: End-to-End Verification & Disaster Recovery Test

**Files:**
- Integration test script or manual verification test.

- [x] **Step 1: Test creating a job with test audio**
  Post a test audio file to `/api/jobs`, verify `job_id` returned with status `queued`.
- [x] **Step 2: Verify background processing and progress polling**
  Poll `/api/jobs/{id}/progress` until status is `completed`.
- [x] **Step 3: Verify tab-closing simulation (Disaster Recovery)**
  Start a job, close connection, wait 3 seconds, call `GET /api/jobs/{id}` and verify it completed and saved without issue.
- [x] **Step 4: Verify export formats**
  Call `/api/jobs/{id}/export?format=srt`, `/api/jobs/{id}/export?format=vtt`, `/api/jobs/{id}/export?format=txt`, `/api/jobs/{id}/export?format=json`.
- [x] **Step 5: Verify web app UI in browser**
  Check `http://localhost:3000` responds and renders cleanly with all new controls and history.

