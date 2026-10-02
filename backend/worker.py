import os
import sys
import logging
import threading
import numpy as np
from typing import Optional, Any
import av

# Fix PyAV compatibility where 'metadata_errors' parameter was removed in av >= 14
_orig_av_open = av.open
def _compat_av_open(*args, **kwargs):
    kwargs.pop("metadata_errors", None)
    return _orig_av_open(*args, **kwargs)
av.open = _compat_av_open

from db import update_job_status, append_segment, save_final_result, get_segments

logger = logging.getLogger("stt_worker")

_cancelled_jobs = set()


def cancel_job(job_id: str) -> None:
    _cancelled_jobs.add(job_id)


def is_job_cancelled(job_id: str) -> bool:
    return job_id in _cancelled_jobs


def _cleanup_cancelled_job(job_id: str, storage_dir: Optional[str] = None, db_path: Optional[str] = None):
    _cancelled_jobs.discard(job_id)
    segments = get_segments(job_id, storage_dir=storage_dir)
    if segments:
        full_text = " ".join([s["text"] for s in segments if s.get("text")])
        save_final_result(job_id, full_text, segments, storage_dir=storage_dir)
    update_job_status(job_id, "failed", error_message="ผู้ใช้ยกเลิกการถอดเสียง (Cancelled by user)", db_path=db_path)


def get_default_model():
    from main import get_model
    return get_model()


def probe_audio_duration(file_path: str) -> float:
    try:
        with av.open(file_path) as container:
            if container.duration:
                return float(container.duration / av.TIME_BASE)
    except Exception as e:
        logger.warning(f"Could not probe audio duration using PyAV: {e}")
    return 0.0


def process_job_sync(
    job_id: str,
    audio_file_path: str,
    audio_type: str = "general",
    vad_filter: bool = True,
    beam_size: int = 1,
    chunk_duration: int = 0,
    db_path: Optional[str] = None,
    storage_dir: Optional[str] = None,
    model_instance: Optional[Any] = None,
    mock_duration: Optional[float] = None,
) -> None:
    try:
        logger.info(f"Starting job {job_id} on {audio_file_path} (beam_size={beam_size}, chunk_duration={chunk_duration})")
        update_job_status(job_id, "processing", progress=0.0, current_time=0.0, db_path=db_path)

        whisper_instance = model_instance if model_instance is not None else get_default_model()

        # Audio type tuning
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

        # Determine duration
        total_duration = mock_duration if mock_duration is not None else probe_audio_duration(audio_file_path)
        if total_duration > 0:
            update_job_status(job_id, "processing", duration=total_duration, db_path=db_path)

        if chunk_duration > 0:
            from faster_whisper.audio import decode_audio

            waveform = decode_audio(audio_file_path, sampling_rate=16000)
            total_samples = len(waveform)
            actual_duration = total_samples / 16000.0
            total_duration = actual_duration
            update_job_status(job_id, "processing", duration=total_duration, db_path=db_path)

            if total_duration > chunk_duration:
                num_chunks = int(np.ceil(total_duration / chunk_duration))
                for idx in range(num_chunks):
                    if is_job_cancelled(job_id):
                        logger.info(f"Job {job_id} cancelled during chunk processing.")
                        _cleanup_cancelled_job(job_id, storage_dir=storage_dir, db_path=db_path)
                        return

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
                        beam_size=beam_size,
                        best_of=beam_size,
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
                        append_segment(
                            job_id,
                            {"start": abs_start, "end": abs_end, "text": text_strip},
                            storage_dir=storage_dir,
                        )

                    progress = min(99.0, ((idx + 1) / num_chunks) * 100.0)
                    update_job_status(
                        job_id,
                        "processing",
                        progress=progress,
                        current_time=end_sec,
                        duration=total_duration,
                        db_path=db_path,
                    )
            else:
                segments_generator, _ = whisper_instance.transcribe(
                    waveform,
                    language="th",
                    beam_size=beam_size,
                    best_of=beam_size,
                    vad_filter=use_vad,
                    vad_parameters=vad_params,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    no_speech_threshold=no_speech_thresh,
                    compression_ratio_threshold=comp_ratio,
                    initial_prompt=prompt,
                )
                for seg in segments_generator:
                    if is_job_cancelled(job_id):
                        logger.info(f"Job {job_id} cancelled during waveform processing.")
                        _cleanup_cancelled_job(job_id, storage_dir=storage_dir, db_path=db_path)
                        return

                    text_strip = seg.text.strip()
                    append_segment(
                        job_id,
                        {"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text_strip},
                        storage_dir=storage_dir,
                    )
                    progress = min(99.0, (seg.end / total_duration) * 100.0) if total_duration > 0 else 0.0
                    update_job_status(
                        job_id,
                        "processing",
                        progress=progress,
                        current_time=seg.end,
                        duration=total_duration,
                        db_path=db_path,
                    )
        else:
            # Continuous full-file transcription
            segments_generator, info = whisper_instance.transcribe(
                audio_file_path,
                language="th",
                beam_size=beam_size,
                best_of=beam_size,
                vad_filter=use_vad,
                vad_parameters=vad_params,
                temperature=0.0,
                condition_on_previous_text=False,
                no_speech_threshold=no_speech_thresh,
                compression_ratio_threshold=comp_ratio,
                initial_prompt=prompt,
            )

            if total_duration <= 0.0 and getattr(info, "duration", None):
                total_duration = float(info.duration)
                update_job_status(job_id, "processing", duration=total_duration, db_path=db_path)

            for seg in segments_generator:
                if is_job_cancelled(job_id):
                    logger.info(f"Job {job_id} cancelled during continuous stream processing.")
                    _cleanup_cancelled_job(job_id, storage_dir=storage_dir, db_path=db_path)
                    return

                text_strip = seg.text.strip()
                append_segment(
                    job_id,
                    {"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text_strip},
                    storage_dir=storage_dir,
                )
                progress = min(99.0, (seg.end / total_duration) * 100.0) if total_duration > 0 else 0.0
                update_job_status(
                    job_id,
                    "processing",
                    progress=progress,
                    current_time=seg.end,
                    duration=total_duration,
                    db_path=db_path,
                )

        # Finalize
        segments = get_segments(job_id, storage_dir=storage_dir)
        full_text = " ".join([s["text"] for s in segments if s.get("text")])
        save_final_result(job_id, full_text, segments, storage_dir=storage_dir)
        update_job_status(
            job_id,
            "completed",
            progress=100.0,
            current_time=total_duration,
            duration=total_duration,
            db_path=db_path,
        )
        logger.info(f"Job {job_id} completed successfully ({len(segments)} segments)")

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        update_job_status(job_id, "failed", error_message=str(e), db_path=db_path)


def start_transcription_job(
    job_id: str,
    audio_file_path: str,
    audio_type: str = "general",
    vad_filter: bool = True,
    beam_size: int = 1,
    chunk_duration: int = 0,
    db_path: Optional[str] = None,
    storage_dir: Optional[str] = None,
) -> threading.Thread:
    thread = threading.Thread(
        target=process_job_sync,
        kwargs={
            "job_id": job_id,
            "audio_file_path": audio_file_path,
            "audio_type": audio_type,
            "vad_filter": vad_filter,
            "beam_size": beam_size,
            "chunk_duration": chunk_duration,
            "db_path": db_path,
            "storage_dir": storage_dir,
        },
        name=f"Worker-{job_id}",
        daemon=True,
    )
    thread.start()
    return thread
