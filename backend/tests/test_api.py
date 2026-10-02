import os
import sys
import io
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app
from db import init_db, create_job, update_job_status, append_segment, save_final_result

client = TestClient(app)

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_jobs_list_empty():
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

def test_job_not_found():
    resp = client.get("/api/jobs/nonexistent-job-id")
    assert resp.status_code == 404

def test_job_progress_and_export(tmp_path, monkeypatch):
    import uuid
    # Setup test job in db
    job_id = f"test-api-{uuid.uuid4().hex[:8]}"
    create_job(job_id, "meeting.mp3", 1024, "general", True, 1, 0)
    update_job_status(job_id, "processing", progress=50.0, current_time=30.0, duration=60.0)
    append_segment(job_id, {"start": 0.0, "end": 2.0, "text": "สวัสดีครับ"})

    # Check progress
    resp = client.get(f"/api/jobs/{job_id}/progress")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["status"] == "processing"
    assert data["progress"] == 50.0
    assert len(data["latest_segments"]) == 1

    # Mark completed and add final result
    save_final_result(job_id, "สวัสดีครับ ทุกท่าน", [{"start": 0.0, "end": 2.0, "text": "สวัสดีครับ ทุกท่าน"}])
    update_job_status(job_id, "completed", progress=100.0, current_time=60.0, duration=60.0)

    # Check full job
    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    job_data = resp.json()
    assert job_data["job"]["status"] == "completed"
    assert job_data["result"]["text"] == "สวัสดีครับ ทุกท่าน"

    # Test export endpoints
    resp_srt = client.get(f"/api/jobs/{job_id}/export?format=srt")
    assert resp_srt.status_code == 200
    assert "00:00:00,000 --> 00:00:02,000" in resp_srt.text

    resp_vtt = client.get(f"/api/jobs/{job_id}/export?format=vtt")
    assert resp_vtt.status_code == 200
    assert "WEBVTT" in resp_vtt.text

    resp_txt = client.get(f"/api/jobs/{job_id}/export?format=txt")
    assert resp_txt.status_code == 200
    assert "สวัสดีครับ ทุกท่าน" in resp_txt.text

    resp_json = client.get(f"/api/jobs/{job_id}/export?format=json")
    assert resp_json.status_code == 200
    assert job_id in resp_json.text
