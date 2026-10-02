import os
import sys
import shutil
import tempfile
import uuid
import logging
import json
import asyncio
from typing import List, AsyncGenerator
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import StreamingResponse
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

def format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

@app.post("/api/transcribe_stream")
async def transcribe_stream(
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

    # Save uploaded file
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
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"ไฟล์มีขนาดใหญ่เกินกำหนด (จำกัดไม่เกิน {limit_gb:.0f} GB)"
                )
            buffer.write(chunk)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield format_sse("progress", {
                "stage": "loading_model",
                "progress": 5,
                "message": "กำลังเตรียมและโหลดโมเดล AI (Faster-Whisper)..."
            })
            await asyncio.sleep(0.01)

            loop = asyncio.get_event_loop()
            whisper_instance = await loop.run_in_executor(None, get_model)

            is_music = audio_type.lower() == "music"
            use_vad = False if is_music else vad_filter
            vad_params = dict(min_silence_duration_ms=500, speech_pad_ms=400) if use_vad else None
            no_speech_thresh = None if is_music else 0.6
            comp_ratio = 2.8 if is_music else 2.4
            prompt = "เนื้อเพลงภาษาไทย คำร้องทำนอง บทเพลง" if is_music else None

            segment_list = []
            collected_text = []

            if chunk_duration > 0:
                yield format_sse("progress", {
                    "stage": "decoding_audio",
                    "progress": 10,
                    "message": "กำลังอ่านและถอดรหัสไฟล์เสียง (Audio Decoding)..."
                })
                await asyncio.sleep(0.01)

                waveform = await loop.run_in_executor(
                    None, lambda: decode_audio(temp_file_path, sampling_rate=16000)
                )
                total_samples = len(waveform)
                total_duration = total_samples / 16000.0
                num_chunks = int(np.ceil(total_duration / chunk_duration)) if total_duration > chunk_duration else 1

                yield format_sse("progress", {
                    "stage": "processing",
                    "progress": 15,
                    "total_chunks": num_chunks,
                    "current_chunk": 0,
                    "total_duration": round(total_duration, 2),
                    "message": f"เตรียมถอดเสียง {num_chunks} ช่วง (ความยาวรวม {total_duration/60:.1f} นาที)..."
                })
                await asyncio.sleep(0.01)

                if total_duration > chunk_duration:
                    for idx in range(num_chunks):
                        start_sec = idx * chunk_duration
                        end_sec = min((idx + 1) * chunk_duration, total_duration)
                        start_sample = int(start_sec * 16000)
                        end_sample = min(int(end_sec * 16000), total_samples)

                        if (end_sample - start_sample) < 16000 * 0.3:
                            continue

                        chunk_audio = waveform[start_sample:end_sample]
                        # Progress ranges from 15% to 95%
                        current_pct = int(15 + ((idx + 1) / num_chunks) * 80)
                        yield format_sse("progress", {
                            "stage": "processing",
                            "progress": current_pct,
                            "current_chunk": idx + 1,
                            "total_chunks": num_chunks,
                            "start_sec": round(start_sec, 1),
                            "end_sec": round(end_sec, 1),
                            "message": f"กำลังถอดเสียงท่อนที่ {idx + 1}/{num_chunks} ({start_sec:.0f}s - {end_sec:.0f}s)..."
                        })
                        await asyncio.sleep(0.01)

                        def run_chunk(audio_data):
                            chunks_gen, _ = whisper_instance.transcribe(
                                audio_data,
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
                            return list(chunks_gen)

                        chunk_segs = await loop.run_in_executor(None, run_chunk, chunk_audio)

                        for seg in chunk_segs:
                            text_strip = seg.text.strip()
                            abs_start = round(start_sec + seg.start, 2)
                            abs_end = round(start_sec + seg.end, 2)
                            segment_item = {
                                "start": abs_start,
                                "end": abs_end,
                                "text": text_strip
                            }
                            segment_list.append(segment_item)
                            if text_strip:
                                collected_text.append(text_strip)

                            # Stream newly found segment
                            yield format_sse("segment", segment_item)
                            await asyncio.sleep(0.005)
                else:
                    def run_single():
                        gen, _ = whisper_instance.transcribe(
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
                        return list(gen)

                    segs = await loop.run_in_executor(None, run_single)
                    for seg in segs:
                        text_strip = seg.text.strip()
                        segment_item = {
                            "start": round(seg.start, 2),
                            "end": round(seg.end, 2),
                            "text": text_strip
                        }
                        segment_list.append(segment_item)
                        if text_strip:
                            collected_text.append(text_strip)
                        yield format_sse("segment", segment_item)
            else:
                yield format_sse("progress", {
                    "stage": "processing",
                    "progress": 20,
                    "message": "กำลังถอดเสียงทั้งไฟล์ต่อเนื่อง..."
                })
                await asyncio.sleep(0.01)

                def run_full():
                    gen, _ = whisper_instance.transcribe(
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
                    # Note: Faster-Whisper generator yields segments as audio is decoded
                    items = []
                    for seg in gen:
                        items.append({
                            "start": round(seg.start, 2),
                            "end": round(seg.end, 2),
                            "text": seg.text.strip()
                        })
                    return items

                items = await loop.run_in_executor(None, run_full)
                for seg in items:
                    segment_list.append(seg)
                    if seg["text"]:
                        collected_text.append(seg["text"])
                    yield format_sse("segment", seg)

            full_text = " ".join(collected_text)
            yield format_sse("complete", {
                "text": full_text,
                "segments": segment_list
            })

        except Exception as err:
            logging.exception("Error in transcribe_stream")
            yield format_sse("error", {"detail": str(err)})
        finally:
            try:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as cleanup_err:
                print(f"Warning during cleanup: {cleanup_err}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

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

