import os
import shutil
import tempfile
import pytest
import sys

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db import (
    init_db,
    create_job,
    update_job_status,
    get_job,
    list_jobs,
    append_segment,
    get_segments,
    save_final_result,
    get_final_result
)

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
    job = create_job("job-123", "meeting.mp3", 1024, "general", True, 1, 0, db_path=db_file, storage_dir=storage_dir)
    assert job["id"] == "job-123"
    assert job["status"] == "queued"
    assert job["filename"] == "meeting.mp3"

    update_job_status("job-123", "processing", progress=50.0, current_time=60.0, duration=120.0, db_path=db_file)
    fetched = get_job("job-123", db_path=db_file, storage_dir=storage_dir)
    assert fetched is not None
    assert fetched["status"] == "processing"
    assert fetched["progress"] == 50.0
    assert fetched["duration"] == 120.0
    assert fetched["current_time"] == 60.0

    append_segment("job-123", {"start": 0.0, "end": 2.5, "text": "สวัสดีครับ"}, storage_dir=storage_dir)
    append_segment("job-123", {"start": 2.5, "end": 5.0, "text": "ยินดีต้อนรับ"}, storage_dir=storage_dir)
    segments = get_segments("job-123", storage_dir=storage_dir)
    assert len(segments) == 2
    assert segments[0]["text"] == "สวัสดีครับ"
    assert segments[1]["text"] == "ยินดีต้อนรับ"

    save_final_result("job-123", "สวัสดีครับ ยินดีต้อนรับ", segments, storage_dir=storage_dir)
    final_res = get_final_result("job-123", storage_dir=storage_dir)
    assert final_res is not None
    assert final_res["text"] == "สวัสดีครับ ยินดีต้อนรับ"
    assert len(final_res["segments"]) == 2

    jobs_list = list_jobs(limit=10, db_path=db_file)
    assert len(jobs_list) == 1
    assert jobs_list[0]["id"] == "job-123"


def test_recover_interrupted_jobs(temp_env):
    from db import recover_interrupted_jobs
    db_file, storage_dir = temp_env
    init_db(db_file, storage_dir)

    # Simulate a job that was in 'processing' when server died
    create_job("job-stuck", "podcast.mp3", 2048, "general", True, 1, 0, db_path=db_file, storage_dir=storage_dir)
    update_job_status("job-stuck", "processing", progress=40.0, current_time=48.0, duration=120.0, db_path=db_file)
    append_segment("job-stuck", {"start": 0.0, "end": 5.0, "text": "ท่อนแรกก่อนไฟดับ"}, storage_dir=storage_dir)

    recovered = recover_interrupted_jobs(db_path=db_file, storage_dir=storage_dir)
    assert "job-stuck" in recovered

    stuck_job = get_job("job-stuck", db_path=db_file, storage_dir=storage_dir)
    assert stuck_job["status"] == "failed"
    assert "ระบบหยุดทำงาน" in stuck_job["error_message"]

    # Partial result should be saved from segments
    partial_res = get_final_result("job-stuck", storage_dir=storage_dir)
    assert partial_res is not None
    assert partial_res["text"] == "ท่อนแรกก่อนไฟดับ"

