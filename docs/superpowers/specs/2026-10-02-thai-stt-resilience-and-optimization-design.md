# Design Specification: Thai STT Resilience, Background Jobs, and Performance Optimization

**Date:** 2026-10-02  
**Status:** Approved  
**Author:** Antigravity & User  

---

## 1. Problem Statement & Goals

Currently, the Thai Speech-to-Text system uses a single synchronous HTTP POST request (`/api/transcribe`) that blocks until transcription is complete. For meeting recordings (e.g. 2 hours long), processing on CPU takes 15–35 minutes. If a user accidentally closes the browser tab, refreshes, or loses network connection, the HTTP request is aborted, the transcription progress is lost, and the user must start over from scratch. Furthermore, there is no real-time progress feedback, no export options other than plain text, and no audio-text synchronization for easy review.

### Goals:
1. **Background Job Persistence & Recovery:** Run transcription asynchronously in a worker thread. Persist job state and audio files on disk (SQLite + local storage directory). Allow users to close tabs, refresh, or disconnect without losing work. Auto-reconnect to running jobs on browser reopen.
2. **Real-time Progress & Text Streaming:** Provide a live progress bar with percentage (0–100%), elapsed time, ETA, and streaming preview of completed segments.
3. **Speed & Decoding Optimization:** Introduce "Fast Mode" (`beam_size=1`) which is 2x–3x faster on CPU with virtually identical speech accuracy, while retaining "High Precision Mode" (`beam_size=5`).
4. **Interactive Audio-Text Sync:** Clicking any transcribed segment jumps the media player to that exact timestamp, with active segment highlighting.
5. **Multiple Export Formats:** Support exporting to `.txt` (clean text or timestamped), `.srt` (subtitles), `.vtt`, and `.json`.
6. **Job History:** Maintain a list of previous transcription jobs so users can review, playback, and re-export past transcriptions.

---

## 2. Architecture & Data Flow

```mermaid
flowchart TD
    subgraph Frontend ["Next.js Frontend (Port 3000)"]
        UI["Upload & Player UI"]
        LS["localStorage (active_job_id)"]
        Poll["Progress Poller / SSE"]
        Hist["Job History Drawer/Modal"]
    end

    subgraph Backend ["FastAPI Backend (Port 8000)"]
        API["Job API Endpoints"]
        DB["SQLite Database (jobs.db)"]
        FS["File Storage (backend/data/jobs/{id})"]
        Worker["Background Worker Thread Pool"]
        Engine["Faster-Whisper (large-v3-turbo, int8, CPU)"]
    end

    UI -->|1. POST /api/jobs (Upload)| API
    API -->|2. Create record status='queued'| DB
    API -->|3. Save uploaded file| FS
    API -->|4. Return job_id immediately| UI
    UI -->|5. Save job_id| LS
    API -->|6. Enqueue task| Worker
    Worker -->|7. Update status='processing', progress%| DB
    Worker -->|8. Transcribe chunk/segments| Engine
    Engine -->|9. Segments streamed| Worker
    Worker -->|10. Append segments & save result.json| FS
    UI -->|11. GET /api/jobs/{id}/progress| Poll
    Poll -->|12. Read live status & segments| DB
    Worker -->|13. Update status='completed'| DB
    UI -->|14. GET /api/jobs/{id}/export?format=...| API
```

---

## 3. Database & Storage Schema

### 3.1 SQLite Database (`backend/data/jobs.db`)
Table: `jobs`
- `id` (TEXT, Primary Key, UUID)
- `filename` (TEXT)
- `filesize` (INTEGER)
- `duration` (REAL, in seconds, 0 if unknown initially)
- `audio_type` (TEXT: "general" | "music")
- `vad_filter` (BOOLEAN)
- `beam_size` (INTEGER: 1 or 5)
- `chunk_duration` (INTEGER: 0 or seconds)
- `status` (TEXT: "queued" | "processing" | "completed" | "failed")
- `progress` (REAL: 0.0 to 100.0)
- `current_time` (REAL: current processed audio timestamp in seconds)
- `error_message` (TEXT, nullable)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)
- `completed_at` (TIMESTAMP, nullable)

### 3.2 File System Structure
```
backend/
  data/
    jobs.db
    jobs/
      {job_id}/
        audio.<ext>        # Original uploaded audio
        segments.jsonl     # Progressively appended segments
        result.json        # Final full text and segments list
```

---

## 4. API Endpoints

### 4.1 `POST /api/jobs`
- **Payload:** `multipart/form-data` with `file`, `audio_type` ("general" | "music"), `vad_filter` (bool), `beam_size` (1 or 5), `chunk_duration` (int).
- **Response:** `{ "job_id": "...", "status": "queued", "filename": "..." }`
- **Behavior:** Saves file into `backend/data/jobs/{job_id}/`, inserts job into SQLite, starts background thread worker, returns HTTP 202 immediately.

### 4.2 `GET /api/jobs/{job_id}/progress`
- **Response:**
```json
{
  "job_id": "...",
  "status": "processing",
  "progress": 45.2,
  "elapsed_seconds": 124,
  "estimated_remaining_seconds": 150,
  "current_time": 540.5,
  "total_duration": 1200.0,
  "latest_segments": [
    {"start": 530.0, "end": 536.2, "text": "สวัสดีครับทุกท่าน"},
    {"start": 536.5, "end": 540.5, "text": "ขอเปิดการประชุมตามระเบียบวาระ"}
  ],
  "segment_count": 142
}
```

### 4.3 `GET /api/jobs/{job_id}`
- **Response:** Complete job details including full transcript and all segments when completed, or error info if failed.

### 4.4 `GET /api/jobs`
- **Response:** List of recent jobs (sorted by `created_at` DESC) with id, filename, status, created_at, duration.

### 4.5 `GET /api/jobs/{job_id}/audio`
- **Response:** Stream audio file with HTTP Range support for media player seeking.

### 4.6 `GET /api/jobs/{job_id}/export?format={txt|srt|vtt|json}`
- **Response:** File download attachment with appropriate MIME type and formatting:
  - `txt`: Plain text (optional `include_timestamps=true`).
  - `srt`: SubRip format (`00:01:20,000 --> 00:01:25,500`).
  - `vtt`: WebVTT format (`00:01:20.000 --> 00:01:25.500`).
  - `json`: Full JSON array of segments with start, end, text.

---

## 5. Frontend Enhancements (`app/ThaiSTTApp.tsx`)

### 5.1 Auto-Recovery & LocalStorage
- When a job is initiated, `current_job_id` is written to `localStorage`.
- On page load / refresh:
  1. Check `localStorage.getItem("thai_stt_active_job")`.
  2. If found, poll `GET /api/jobs/{job_id}/progress`.
  3. If still running or completed, restore state immediately.
  4. User never loses progress if connection is interrupted or tab is closed.

### 5.2 Live Progress UI
- Progress bar with percentage, elapsed time, and ETA.
- Live Segment Stream: newly recognized segments scroll smoothly into view.

### 5.3 Speed & Mode Controls
- Switch between **"โหมดเร็ว (Fast Mode)"** (`beam_size=1`) and **"โหมดความแม่นยำสูง (Precision Mode)"** (`beam_size=5`).

### 5.4 Audio & Text Synchronization
- When clicking on any segment card or line:
  - Media player seeks to `segment.start`.
  - Auto-play or continues playing.
- During playback, the currently active segment based on current audio time is highlighted with an active glowing border/background.

### 5.5 Export Dropdown Menu
- Single export menu with options:
  - ดาวน์โหลดข้อความ (.txt)
  - ดาวน์โหลดข้อความพร้อมเวลา (.txt with timestamps)
  - ดาวน์โหลดซับไตเติล (.srt)
  - ดาวน์โหลด WebVTT (.vtt)
  - ดาวน์โหลด JSON (.json)

### 5.6 Job History Drawer / Modal
- View past completed jobs, click to reload into player and view transcript.

---

## 6. Verification & Testing Strategy
1. **Unit & API Testing:**
   - Test `POST /api/jobs` with a sample wav.
   - Verify job status transitions: `queued` -> `processing` -> `completed`.
   - Test tab close simulation: Trigger job, disconnect client, wait, reconnect, verify completion.
   - Test export endpoint for all 4 formats (`txt`, `srt`, `vtt`, `json`).
2. **Audio Sync Testing:**
   - Test media player timestamp seeking upon clicking a segment.
3. **Speed Optimization Verification:**
   - Verify `beam_size=1` executes substantially faster on CPU.
