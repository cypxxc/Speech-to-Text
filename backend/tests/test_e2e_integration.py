import os
import sys
import io
import wave
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app
import db

client = TestClient(app)

def create_synthetic_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        # 0.5 second of silence
        data = b"\x00\x00" * 8000
        wav_file.writeframes(data)
    return buf.getvalue()

def test_full_e2e_workflow(monkeypatch):
    # 1. Create a dummy wav file
    wav_bytes = create_synthetic_wav()

    # Prevent real whisper transcription from running in background during test
    def mock_start_job(*args, **kwargs):
        pass
    monkeypatch.setattr("worker.start_transcription_job", mock_start_job)

    # 2. Upload file via POST /api/jobs
    resp = client.post(
        "/api/jobs",
        files={"file": ("test_recording.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={
            "audio_type": "music",
            "vad_filter": "false",
            "beam_size": "1",
            "chunk_duration": "60",
        },
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert "job_id" in res_data
    job_id = res_data["job_id"]
    assert res_data["status"] == "queued"

    # 3. Verify job in DB
    job = db.get_job(job_id)
    assert job is not None
    assert job["filename"] == "test_recording.wav"
    assert job["beam_size"] == 1
    assert job["chunk_duration"] == 60
    assert job["vad_filter"] is False

    # 4. Check initial progress endpoint
    prog_resp = client.get(f"/api/jobs/{job_id}/progress")
    assert prog_resp.status_code == 200
    prog_data = prog_resp.json()
    assert prog_data["job_id"] == job_id
    assert prog_data["status"] == "queued"
    assert prog_data["progress"] == 0.0

    # 5. Check audio streaming endpoint (disaster recovery / audio seek)
    audio_resp = client.get(f"/api/jobs/{job_id}/audio")
    assert audio_resp.status_code == 200
    assert len(audio_resp.content) == len(wav_bytes)

    # 6. Simulate worker progressing and appending segments
    db.update_job_status(job_id, "processing", progress=50.0, current_time=15.0, duration=30.0)
    db.append_segment(job_id, {"start": 0.0, "end": 5.0, "text": "ท่อนฮุกภาษาไทย"})
    db.append_segment(job_id, {"start": 5.0, "end": 10.0, "text": "เสียงดนตรีบรรเลง"})

    # Check progress mid-way
    prog_resp2 = client.get(f"/api/jobs/{job_id}/progress")
    assert prog_resp2.status_code == 200
    assert prog_resp2.json()["progress"] == 50.0
    assert len(prog_resp2.json()["latest_segments"]) == 2

    # 7. Complete the job
    db.save_final_result(
        job_id,
        "ท่อนฮุกภาษาไทย เสียงดนตรีบรรเลง",
        [
            {"start": 0.0, "end": 5.0, "text": "ท่อนฮุกภาษาไทย"},
            {"start": 5.0, "end": 10.0, "text": "เสียงดนตรีบรรเลง"},
        ],
    )
    db.update_job_status(job_id, "completed", progress=100.0, current_time=30.0, duration=30.0)

    # 8. Check job detail
    detail_resp = client.get(f"/api/jobs/{job_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["job"]["status"] == "completed"
    assert detail["result"]["text"] == "ท่อนฮุกภาษาไทย เสียงดนตรีบรรเลง"
    assert len(detail["result"]["segments"]) == 2

    # 9. Verify all export formats
    srt_resp = client.get(f"/api/jobs/{job_id}/export?format=srt")
    assert srt_resp.status_code == 200
    assert "00:00:00,000 --> 00:00:05,000" in srt_resp.text
    assert "ท่อนฮุกภาษาไทย" in srt_resp.text

    vtt_resp = client.get(f"/api/jobs/{job_id}/export?format=vtt")
    assert vtt_resp.status_code == 200
    assert "WEBVTT" in vtt_resp.text
    assert "00:00:05.000 --> 00:00:10.000" in vtt_resp.text

    txt_resp = client.get(f"/api/jobs/{job_id}/export?format=txt")
    assert txt_resp.status_code == 200
    assert txt_resp.text == "ท่อนฮุกภาษาไทย เสียงดนตรีบรรเลง"

    txt_ts_resp = client.get(f"/api/jobs/{job_id}/export?format=txt&timestamps=true")
    assert txt_ts_resp.status_code == 200
    assert "[00:00:00 - 00:00:05] ท่อนฮุกภาษาไทย" in txt_ts_resp.text

    json_resp = client.get(f"/api/jobs/{job_id}/export?format=json")
    assert json_resp.status_code == 200
    assert job_id in json_resp.text

    # 10. Check list history
    history_resp = client.get("/api/jobs?limit=10")
    assert history_resp.status_code == 200
    history = history_resp.json()
    assert any(j["id"] == job_id for j in history)
