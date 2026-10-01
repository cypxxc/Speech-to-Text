import os
import sys
import shutil
import tempfile
import uuid
import logging
from typing import List
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio

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

model: WhisperModel = None

def get_model():
    global model
    if model is None:
        print(f"Initializing WhisperModel ('large-v3-turbo') on device='{device}' with compute_type='{compute_type}', cpu_threads={cpu_threads}...")
        model = WhisperModel(
            "large-v3-turbo",
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            num_workers=2,
        )
        print("WhisperModel initialized successfully.")
    return model

@app.on_event("startup")
async def startup_event():
    # Model will be loaded or ready on startup
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

@app.post("/api/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    audio_type: str = Form("general"),  # "general" (speech/meeting) or "music" (songs with loud background music)
    vad_filter: bool = Form(True),
    chunk_duration: int = Form(0),  # 0 = continuous full-file, 60 = 60-second chunks
):
    filename = file.filename or "audio"
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{ext}'. Supported formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Save to a temporary file with safe ASCII name to prevent C-library encoding issues
    temp_dir = tempfile.mkdtemp()
    safe_name = f"audio_{uuid.uuid4().hex[:12]}{ext}"
    temp_file_path = os.path.join(temp_dir, safe_name)

    try:
        written_size = 0
        chunk_size = 1024 * 1024  # 1MB chunks
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

        # Audio type tuning:
        # Songs have background instrumentals that VAD often misclassifies as non-speech.
        # We disable strict VAD and set no_speech_threshold to None so lyrics are never skipped.
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

        print(f"Transcribing '{filename}' (audio_type={audio_type}, use_vad={use_vad}, chunk_duration={chunk_duration}s)...")

        if chunk_duration > 0:
            # Decode full audio into 16kHz float32 numpy array
            waveform = decode_audio(temp_file_path, sampling_rate=16000)
            total_samples = len(waveform)
            total_duration = total_samples / 16000.0
            print(f"Loaded audio: {total_duration:.2f} seconds ({total_duration/60:.2f} minutes)")

            if total_duration > chunk_duration:
                num_chunks = int(np.ceil(total_duration / chunk_duration))
                print(f"Splitting into {num_chunks} chunks of {chunk_duration}s...")

                for idx in range(num_chunks):
                    start_sec = idx * chunk_duration
                    end_sec = min((idx + 1) * chunk_duration, total_duration)
                    start_sample = int(start_sec * 16000)
                    end_sample = min(int(end_sec * 16000), total_samples)

                    # Skip tiny residual fragments (< 0.3s)
                    if (end_sample - start_sample) < 16000 * 0.3:
                        continue

                    chunk_audio = waveform[start_sample:end_sample]
                    print(f"  -> Processing Chunk {idx + 1}/{num_chunks} [{start_sec:.1f}s - {end_sec:.1f}s]...")

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
                # Audio is shorter than chunk_duration, transcribe all directly
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
            # Continuous full-file transcription
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
        # Proper temporary file and directory cleanup
        try:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as cleanup_err:
            print(f"Warning during cleanup: {cleanup_err}")
