import os
import json
import sqlite3
import datetime
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_DIR = os.path.join(BASE_DIR, "data")
DEFAULT_DB_PATH = os.path.join(DEFAULT_DATA_DIR, "jobs.db")
DEFAULT_STORAGE_DIR = os.path.join(DEFAULT_DATA_DIR, "jobs")


def _resolve_paths(db_path: Optional[str] = None, storage_dir: Optional[str] = None):
    actual_db = db_path if db_path is not None else DEFAULT_DB_PATH
    actual_storage = storage_dir if storage_dir is not None else DEFAULT_STORAGE_DIR
    return actual_db, actual_storage


@contextmanager
def get_db_connection(db_path: Optional[str] = None):
    actual_db, _ = _resolve_paths(db_path)
    os.makedirs(os.path.dirname(actual_db), exist_ok=True)
    conn = sqlite3.connect(actual_db, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None, storage_dir: Optional[str] = None) -> None:
    actual_db, actual_storage = _resolve_paths(db_path, storage_dir)
    os.makedirs(os.path.dirname(actual_db), exist_ok=True)
    os.makedirs(actual_storage, exist_ok=True)

    with get_db_connection(actual_db) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                filesize INTEGER NOT NULL,
                audio_type TEXT DEFAULT 'general',
                vad_filter BOOLEAN DEFAULT 1,
                beam_size INTEGER DEFAULT 1,
                chunk_duration INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'queued',
                progress REAL DEFAULT 0.0,
                current_time REAL DEFAULT 0.0,
                duration REAL DEFAULT 0.0,
                error_message TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")


def create_job(
    job_id: str,
    filename: str,
    filesize: int,
    audio_type: str = "general",
    vad_filter: bool = True,
    beam_size: int = 1,
    chunk_duration: int = 0,
    db_path: Optional[str] = None,
    storage_dir: Optional[str] = None,
) -> Dict[str, Any]:
    actual_db, actual_storage = _resolve_paths(db_path, storage_dir)
    job_dir = os.path.join(actual_storage, job_id)
    os.makedirs(job_dir, exist_ok=True)

    with get_db_connection(actual_db) as conn:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs (
                id, filename, filesize, audio_type, vad_filter, beam_size,
                chunk_duration, status, progress, current_time, duration,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0.0, 0.0, 0.0, ?, ?)
            """,
            (
                job_id,
                filename,
                filesize,
                audio_type,
                1 if vad_filter else 0,
                beam_size,
                chunk_duration,
                now,
                now,
            ),
        )

    return get_job(job_id, db_path=actual_db, storage_dir=actual_storage)


def update_job_status(
    job_id: str,
    status: str,
    progress: Optional[float] = None,
    current_time: Optional[float] = None,
    duration: Optional[float] = None,
    error_message: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    actual_db, _ = _resolve_paths(db_path)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    updates = ["status = ?", "updated_at = ?"]
    params = [status, now]

    if progress is not None:
        updates.append("progress = ?")
        params.append(round(progress, 2))
    if current_time is not None:
        updates.append("current_time = ?")
        params.append(round(current_time, 2))
    if duration is not None:
        updates.append("duration = ?")
        params.append(round(duration, 2))
    if error_message is not None:
        updates.append("error_message = ?")
        params.append(error_message)

    params.append(job_id)
    sql = f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?"

    with get_db_connection(actual_db) as conn:
        conn.execute(sql, params)


def get_job(
    job_id: str,
    db_path: Optional[str] = None,
    storage_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    actual_db, _ = _resolve_paths(db_path, storage_dir)
    with get_db_connection(actual_db) as conn:
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        res["vad_filter"] = bool(res["vad_filter"])
        return res


def list_jobs(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    actual_db, _ = _resolve_paths(db_path)
    with get_db_connection(actual_db) as conn:
        cursor = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = cursor.fetchall()
        jobs = []
        for r in rows:
            d = dict(r)
            d["vad_filter"] = bool(d["vad_filter"])
            jobs.append(d)
        return jobs


def append_segment(job_id: str, segment: Dict[str, Any], storage_dir: Optional[str] = None) -> None:
    _, actual_storage = _resolve_paths(storage_dir=storage_dir)
    job_dir = os.path.join(actual_storage, job_id)
    os.makedirs(job_dir, exist_ok=True)
    jsonl_path = os.path.join(job_dir, "segments.jsonl")

    line = json.dumps(segment, ensure_ascii=False)
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_segments(job_id: str, storage_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    _, actual_storage = _resolve_paths(storage_dir=storage_dir)
    jsonl_path = os.path.join(actual_storage, job_id, "segments.jsonl")
    if not os.path.exists(jsonl_path):
        return []

    segments = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    segments.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return segments


def save_final_result(
    job_id: str,
    full_text: str,
    segments: List[Dict[str, Any]],
    storage_dir: Optional[str] = None,
) -> None:
    _, actual_storage = _resolve_paths(storage_dir=storage_dir)
    job_dir = os.path.join(actual_storage, job_id)
    os.makedirs(job_dir, exist_ok=True)
    result_path = os.path.join(job_dir, "result.json")

    data = {
        "text": full_text,
        "segments": segments,
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_final_result(job_id: str, storage_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    _, actual_storage = _resolve_paths(storage_dir=storage_dir)
    result_path = os.path.join(actual_storage, job_id, "result.json")
    if not os.path.exists(result_path):
        return None
    with open(result_path, "r", encoding="utf-8") as f:
        return json.load(f)
