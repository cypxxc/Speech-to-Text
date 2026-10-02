import os
import sys
import tempfile
import shutil
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db import init_db, create_job, get_job, get_segments, get_final_result
from worker import process_job_sync, start_transcription_job


class MockSegment:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


class MockInfo:
    def __init__(self, duration):
        self.duration = duration


class MockWhisperModel:
    def transcribe(self, *args, **kwargs):
        segments = [
            MockSegment(0.0, 2.5, " สวัสดีครับ"),
            MockSegment(2.5, 5.0, " วันนี้มาทดสอบระบบ"),
        ]
        return iter(segments), MockInfo(5.0)


@pytest.fixture
def temp_env():
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_jobs.db")
    storage_dir = os.path.join(temp_dir, "jobs_data")
    init_db(db_file, storage_dir)

    # Create a dummy audio file
    audio_path = os.path.join(temp_dir, "test.wav")
    with open(audio_path, "wb") as f:
        f.write(b"RIFFdummydataWAVEfmt ")

    yield db_file, storage_dir, audio_path
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_worker_sync_success(temp_env, monkeypatch):
    db_file, storage_dir, audio_path = temp_env
    job_id = "job-worker-1"
    create_job(job_id, "test.wav", 100, "general", True, 1, 0, db_path=db_file, storage_dir=storage_dir)

    mock_model = MockWhisperModel()

    process_job_sync(
        job_id=job_id,
        audio_file_path=audio_path,
        audio_type="general",
        vad_filter=True,
        beam_size=1,
        chunk_duration=0,
        db_path=db_file,
        storage_dir=storage_dir,
        model_instance=mock_model,
        mock_duration=5.0
    )

    job = get_job(job_id, db_path=db_file, storage_dir=storage_dir)
    assert job["status"] == "completed"
    assert job["progress"] == 100.0

    segments = get_segments(job_id, storage_dir=storage_dir)
    assert len(segments) == 2
    assert segments[0]["text"] == "สวัสดีครับ"
    assert segments[1]["text"] == "วันนี้มาทดสอบระบบ"

    final_res = get_final_result(job_id, storage_dir=storage_dir)
    assert final_res is not None
    assert "สวัสดีครับ วันนี้มาทดสอบระบบ" in final_res["text"]


def test_worker_sync_failure(temp_env):
    db_file, storage_dir, audio_path = temp_env
    job_id = "job-worker-fail"
    create_job(job_id, "test.wav", 100, "general", True, 1, 0, db_path=db_file, storage_dir=storage_dir)

    bad_model = MagicMock()
    bad_model.transcribe.side_effect = RuntimeError("GPU out of memory or decoding error")

    process_job_sync(
        job_id=job_id,
        audio_file_path=audio_path,
        audio_type="general",
        vad_filter=True,
        beam_size=1,
        chunk_duration=0,
        db_path=db_file,
        storage_dir=storage_dir,
        model_instance=bad_model,
        mock_duration=5.0
    )

    job = get_job(job_id, db_path=db_file, storage_dir=storage_dir)
    assert job["status"] == "failed"
    assert "GPU out of memory" in job["error_message"]
