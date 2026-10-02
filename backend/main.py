import os
import sys
import shutil
import tempfile
import uuid
import logging
import datetime
from typing import List, Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Query
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np
import av

# Fix PyAV compatibility where 'metadata_errors' parameter was removed in av >= 14
_orig_av_open = av.open
def _compat_av_open(*args, **kwargs):
    kwargs.pop("metadata_errors", None)
    return _orig_av_open(*args, **kwargs)
av.open = _compat_av_open

from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio

import db
import worker
import exporter
import corrector
import summarizer

# Initialize SQLite database schema and storage directories
db.init_db()

# Ensure stdout and stderr handle Thai / UTF-8 characters without 'charmap' errors on Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(title="Thai Speech-to-Text API")

# Enable CORS for local frontend ports (e.g. Next.js on 3000, Vite on 5173, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Determine device and compute_type based on CUDA availability
try:
    import torch
    is_cuda = torch.cuda.is_available()
except ImportError:
    is_cuda = False

device = "cuda" if is_cuda else "cpu"
compute_type = "float16" if is_cuda else "int8"

# Determine CPU threads (i5-11500B has 6 physical cores / 12 logical threads)
cpu_threads = max(4, min(os.cpu_count() or 6, 8))

_model_cache: dict[str, WhisperModel] = {}

def get_model(model_name: str = "large-v3-turbo") -> WhisperModel:
    global _model_cache
    if model_name not in _model_cache:
        print(f"Initializing WhisperModel ('{model_name}') on device='{device}' with compute_type='{compute_type}', cpu_threads={cpu_threads}...")
        _model_cache[model_name] = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            num_workers=2,
        )
        print(f"WhisperModel '{model_name}' initialized successfully.")
    return _model_cache[model_name]

@app.on_event("startup")
async def startup_event():
    db.init_db()
    # Recover any jobs that were interrupted if server was killed or crashed
    interrupted = db.recover_interrupted_jobs()
    if interrupted:
        logging.info(f"Disaster Recovery: Found and recovered {len(interrupted)} interrupted job(s) from previous run: {interrupted}")
    # Model will be loaded or ready on startup in background thread
    import threading
    threading.Thread(target=get_model, daemon=True).start()

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".mp4", ".webm", ".flac", ".aac"}
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB limit for local single-user usage

class Segment(BaseModel):
    start: float
    end: float
    text: str

class TranscriptionResponse(BaseModel):
    text: str
    segments: List[dict]

@app.get("/health")
def health_check():
    return {"status": "ok", "device": device, "compute_type": compute_type}

# ==========================================
# Resilient Asynchronous Job Suite
# ==========================================

@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    audio_type: str = Form("general"),
    vad_filter: bool = Form(True),
    beam_size: int = Form(1),
    chunk_duration: int = Form(0),
    model_name: str = Form("large-v3-turbo"),
    initial_prompt: Optional[str] = Form(None),
):
    filename = file.filename or "audio"
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{ext}'. Supported formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job_dir = os.path.join(db.DEFAULT_STORAGE_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    audio_path = os.path.join(job_dir, f"audio{ext}")

    written_size = 0
    chunk_size = 1024 * 1024  # 1MB chunks
    with open(audio_path, "wb") as buffer:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            written_size += len(chunk)
            if written_size > MAX_FILE_SIZE:
                if os.path.exists(audio_path):
                    os.remove(audio_path)
                limit_gb = MAX_FILE_SIZE / (1024 * 1024 * 1024)
                raise HTTPException(
                    status_code=413,
                    detail=f"ไฟล์มีขนาดใหญ่เกินกำหนด (จำกัดไม่เกิน {limit_gb:.0f} GB)"
                )
            buffer.write(chunk)

    created = db.create_job(
        job_id=job_id,
        filename=filename,
        filesize=written_size,
        audio_type=audio_type,
        vad_filter=vad_filter,
        beam_size=beam_size,
        chunk_duration=chunk_duration,
        model_name=model_name,
        initial_prompt=initial_prompt,
    )

    worker.start_transcription_job(
        job_id=job_id,
        audio_file_path=audio_path,
        audio_type=audio_type,
        vad_filter=vad_filter,
        beam_size=beam_size,
        chunk_duration=chunk_duration,
        model_name=model_name,
        initial_prompt=initial_prompt,
    )

    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs")
def list_jobs(limit: int = 50):
    return db.list_jobs(limit=limit)


@app.get("/api/jobs/{job_id}/progress")
def get_job_progress(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    segments = db.get_segments(job_id)
    
    elapsed = 0.0
    created_at_str = job.get("created_at")
    if created_at_str:
        try:
            dt = datetime.datetime.fromisoformat(created_at_str)
            now = datetime.datetime.now(datetime.timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            elapsed = max(0.0, (now - dt).total_seconds())
        except Exception:
            pass

    progress = float(job.get("progress", 0.0))
    eta = 0.0
    if 0.0 < progress < 100.0 and elapsed > 0.0:
        eta = max(0.0, (elapsed / progress) * (100.0 - progress))

    return {
        "job_id": job["id"],
        "status": job["status"],
        "progress": progress,
        "current_time": float(job.get("current_time", 0.0)),
        "duration": float(job.get("duration", 0.0)),
        "elapsed_seconds": round(elapsed, 1),
        "estimated_remaining_seconds": round(eta, 1),
        "latest_segments": segments[-10:] if len(segments) > 10 else segments,
        "segment_count": len(segments),
        "error_message": job.get("error_message"),
    }


@app.get("/api/jobs/{job_id}")
def get_job_detail(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = db.get_final_result(job_id)
    if not result:
        segments = db.get_segments(job_id)
        if segments:
            full_text = " ".join([s["text"] for s in segments if s.get("text")])
            result = {"text": full_text, "segments": segments}

    summary = db.get_summary(job_id)
    return {
        "job": job,
        "result": result,
        "summary": summary,
    }


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] in ("completed", "failed"):
        return {"job_id": job_id, "status": job["status"], "message": "Job already finished"}

    worker.cancel_job(job_id)
    db.update_job_status(job_id, "failed", error_message="ผู้ใช้ยกเลิกการถอดเสียง (Cancelled by user)")

    # Finalize any segments already transcribed so far
    segments = db.get_segments(job_id)
    if segments and not db.get_final_result(job_id):
        full_text = " ".join([s["text"] for s in segments if s.get("text")])
        db.save_final_result(job_id, full_text, segments)

    return {"job_id": job_id, "status": "failed", "message": "Job cancelled successfully"}


@app.post("/api/jobs/{job_id}/summarize")
def summarize_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = db.get_final_result(job_id)
    if not result:
        segments = db.get_segments(job_id)
        if segments:
            full_text = " ".join([s["text"] for s in segments if s.get("text")])
            result = {"text": full_text, "segments": segments}
        else:
            raise HTTPException(status_code=400, detail="Job has no transcribed text to summarize")

    text = result.get("text", "")
    segments = result.get("segments", [])
    duration = float(job.get("duration", 0.0))

    summary = summarizer.generate_local_summary(
        filename=job["filename"],
        duration_sec=duration,
        text=text,
        segments=segments,
    )
    db.save_summary(job_id, summary)
    return summary


@app.get("/api/jobs/{job_id}/summary")
def get_job_summary(job_id: str):
    summary = db.get_summary(job_id)
    if summary:
        return summary
    return summarize_job(job_id)


@app.get("/api/jobs/{job_id}/audio")
def get_job_audio(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = os.path.join(db.DEFAULT_STORAGE_DIR, job_id)
    if not os.path.isdir(job_dir):
        raise HTTPException(status_code=404, detail="Job storage not found")

    # Locate audio file
    for f in os.listdir(job_dir):
        if f.startswith("audio."):
            audio_path = os.path.join(job_dir, f)
            return FileResponse(path=audio_path, filename=job["filename"])

    raise HTTPException(status_code=404, detail="Audio file not found for this job")


@app.get("/api/jobs/{job_id}/export")
def export_job_result(
    job_id: str,
    format: str = Query("txt", pattern="^(txt|srt|vtt|json)$"),
    timestamps: bool = Query(False),
):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = db.get_final_result(job_id)
    if not result:
        segments = db.get_segments(job_id)
        if segments:
            full_text = " ".join([s["text"] for s in segments if s.get("text")])
            result = {"text": full_text, "segments": segments}
        else:
            raise HTTPException(status_code=400, detail="Job has no transcription results yet")

    text = result.get("text", "")
    segments = result.get("segments", [])

    base_name, _ = os.path.splitext(job["filename"])
    safe_base = "".join(c for c in base_name if c.isalnum() or c in ("-", "_", " ")).strip() or job_id

    if format == "srt":
        content = exporter.export_srt(segments)
        media_type = "text/plain; charset=utf-8"
        filename = f"{safe_base}.srt"
    elif format == "vtt":
        content = exporter.export_vtt(segments)
        media_type = "text/vtt; charset=utf-8"
        filename = f"{safe_base}.vtt"
    elif format == "json":
        content = exporter.export_json(job, text, segments)
        media_type = "application/json; charset=utf-8"
        filename = f"{safe_base}.json"
    else:  # txt
        content = exporter.export_txt(text, segments, include_timestamps=timestamps)
        media_type = "text/plain; charset=utf-8"
        suffix = "_timestamped" if timestamps else ""
        filename = f"{safe_base}{suffix}.txt"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==========================================
# Legacy Synchronous Transcription Endpoint
# ==========================================

@app.post("/api/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    audio_type: str = Form("general"),
    vad_filter: bool = Form(True),
    chunk_duration: int = Form(0),
):
    filename = file.filename or "audio"
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{ext}'. Supported formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    temp_dir = tempfile.mkdtemp()
    safe_name = f"audio_{uuid.uuid4().hex[:12]}{ext}"
    temp_file_path = os.path.join(temp_dir, safe_name)

    try:
        written_size = 0
        chunk_size = 1024 * 1024
        with open(temp_file_path, "wb") as buffer:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                written_size += len(chunk)
                if written_size > MAX_FILE_SIZE:
                    limit_gb = MAX_FILE_SIZE / (1024 * 1024 * 1024)
                    raise HTTPException(
                        status_code=413,
                        detail=f"ไฟล์มีขนาดใหญ่เกินกำหนด (จำกัดไม่เกิน {limit_gb:.0f} GB)"
                    )
                buffer.write(chunk)

        whisper_instance = get_model()

        is_music = audio_type.lower() == "music"
        use_vad = False if is_music else vad_filter

        vad_params = None
        if use_vad:
            vad_params = dict(
                min_silence_duration_ms=500,
                speech_pad_ms=400,
            )

        no_speech_thresh = None if is_music else 0.6
        comp_ratio = 2.8 if is_music else 2.4
        prompt = "เนื้อเพลงภาษาไทย คำร้องทำนอง บทเพลง" if is_music else None

        segment_list = []
        collected_text = []

        if chunk_duration > 0:
            waveform = decode_audio(temp_file_path, sampling_rate=16000)
            total_samples = len(waveform)
            total_duration = total_samples / 16000.0

            if total_duration > chunk_duration:
                num_chunks = int(np.ceil(total_duration / chunk_duration))
                for idx in range(num_chunks):
                    start_sec = idx * chunk_duration
                    end_sec = min((idx + 1) * chunk_duration, total_duration)
                    start_sample = int(start_sec * 16000)
                    end_sample = min(int(end_sec * 16000), total_samples)

                    if (end_sample - start_sample) < 16000 * 0.3:
                        continue

                    chunk_audio = waveform[start_sample:end_sample]
                    chunk_segments, _ = whisper_instance.transcribe(
                        chunk_audio,
                        language="th",
                        beam_size=5,
                        best_of=5,
                        vad_filter=use_vad,
                        vad_parameters=vad_params,
                        temperature=0.0,
                        condition_on_previous_text=False,
                        no_speech_threshold=no_speech_thresh,
                        compression_ratio_threshold=comp_ratio,
                        initial_prompt=prompt,
                    )

                    for seg in chunk_segments:
                        text_strip = seg.text.strip()
                        abs_start = round(start_sec + seg.start, 2)
                        abs_end = round(start_sec + seg.end, 2)
                        segment_list.append({
                            "start": abs_start,
                            "end": abs_end,
                            "text": text_strip
                        })
                        if text_strip:
                            collected_text.append(text_strip)
            else:
                segments_generator, info = whisper_instance.transcribe(
                    waveform,
                    language="th",
                    beam_size=5,
                    best_of=5,
                    vad_filter=use_vad,
                    vad_parameters=vad_params,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    no_speech_threshold=no_speech_thresh,
                    compression_ratio_threshold=comp_ratio,
                    initial_prompt=prompt,
                )
                for seg in segments_generator:
                    text_strip = seg.text.strip()
                    segment_list.append({
                        "start": round(seg.start, 2),
                        "end": round(seg.end, 2),
                        "text": text_strip
                    })
                    if text_strip:
                        collected_text.append(text_strip)
        else:
            segments_generator, info = whisper_instance.transcribe(
                temp_file_path,
                language="th",
                beam_size=5,
                best_of=5,
                vad_filter=use_vad,
                vad_parameters=vad_params,
                temperature=0.0,
                condition_on_previous_text=False,
                no_speech_threshold=no_speech_thresh,
                compression_ratio_threshold=comp_ratio,
                initial_prompt=prompt,
            )

            for seg in segments_generator:
                text_strip = seg.text.strip()
                segment_list.append({
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": text_strip
                })
                if text_strip:
                    collected_text.append(text_strip)

        full_text = " ".join(collected_text)
        return {
            "text": full_text,
            "segments": segment_list
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription error: {str(e)}")
    finally:
        try:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as cleanup_err:
            print(f"Warning during cleanup: {cleanup_err}")
