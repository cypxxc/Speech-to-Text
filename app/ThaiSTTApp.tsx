"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";

interface Segment {
  start: number;
  end: number;
  text: string;
}

interface JobMeta {
  id: string;
  filename: string;
  filesize: number;
  audio_type: string;
  vad_filter: boolean;
  beam_size: number;
  chunk_duration: number;
  status: "queued" | "processing" | "completed" | "failed";
  progress: number;
  current_time: number;
  duration: number;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

interface ProgressResponse {
  job_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  progress: number;
  current_time: number;
  duration: number;
  elapsed_seconds: number;
  estimated_remaining_seconds: number;
  latest_segments: Segment[];
  segment_count: number;
  error_message?: string | null;
}

const BACKEND_URL = "http://localhost:8000";
const STORAGE_KEY = "thai_stt_active_job";

export default function ThaiSTTApp() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copySuccess, setCopySuccess] = useState(false);
  const [showSegments, setShowSegments] = useState(true);

  // Job & Progress state
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<"idle" | "queued" | "processing" | "completed" | "failed">("idle");
  const [progress, setProgress] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const [transcript, setTranscript] = useState("");
  const [segments, setSegments] = useState<Segment[]>([]);

  // Audio Tuning & Performance Options
  const [audioType, setAudioType] = useState<"music" | "general">("music");
  const [vadFilter, setVadFilter] = useState(false);
  const [fastMode, setFastMode] = useState(true); // beam_size = 1 vs 5
  const [enableChunking, setEnableChunking] = useState(true);
  const [chunkDuration, setChunkDuration] = useState(60);

  // Interactive Playback state
  const [currentTime, setCurrentTime] = useState(0);
  const [activeSegmentIndex, setActiveSegmentIndex] = useState<number | null>(null);

  // UI Modals & Dropdowns
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [historyJobs, setHistoryJobs] = useState<JobMeta[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const activeSegmentRef = useRef<HTMLDivElement | null>(null);

  const formatTimeClock = (sec: number) => {
    const mins = Math.floor(sec / 60);
    const secs = Math.floor(sec % 60);
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  const formatTimestamp = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 10);
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}.${ms}`;
  };

  // Load completed job details
  const loadCompletedJob = useCallback(async (jobId: string) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/jobs/${jobId}`);
      if (!res.ok) throw new Error("ไม่สามารถโหลดข้อมูลงานได้");
      const data = await res.json();
      if (data.result) {
        setTranscript(data.result.text || "");
        setSegments(data.result.segments || []);
      }
      setJobStatus("completed");
      setProgress(100);
      setAudioUrl(`${BACKEND_URL}/api/jobs/${jobId}/audio`);
    } catch (err: unknown) {
      console.error("Failed to load completed job:", err);
    }
  }, []);

  // Poll progress function
  const pollProgress = useCallback(
    async (jobId: string) => {
      try {
        const res = await fetch(`${BACKEND_URL}/api/jobs/${jobId}/progress`);
        if (!res.ok) {
          if (res.status === 404) {
            localStorage.removeItem(STORAGE_KEY);
            setActiveJobId(null);
            setJobStatus("idle");
          }
          return;
        }

        const data: ProgressResponse = await res.json();
        setJobStatus(data.status);
        setProgress(data.progress || 0);
        setElapsedSeconds(data.elapsed_seconds || 0);
        setRemainingSeconds(data.estimated_remaining_seconds || 0);

        if (data.latest_segments && data.latest_segments.length > 0) {
          setSegments(data.latest_segments);
          const liveText = data.latest_segments.map((s) => s.text).join(" ");
          setTranscript(liveText);
        }

        if (data.status === "completed") {
          if (pollTimerRef.current) clearInterval(pollTimerRef.current);
          await loadCompletedJob(jobId);
        } else if (data.status === "failed") {
          if (pollTimerRef.current) clearInterval(pollTimerRef.current);
          setError(data.error_message || "การประมวลผลล้มเหลว");
        }
      } catch (err: unknown) {
        console.warn("Poll progress error:", err);
      }
    },
    [loadCompletedJob]
  );

  // Resume active job from localStorage on initial render
  useEffect(() => {
    const savedJobId = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    if (savedJobId) {
      queueMicrotask(() => {
        setActiveJobId(savedJobId);
        setJobStatus("processing");
        pollProgress(savedJobId);
      });
      pollTimerRef.current = setInterval(() => pollProgress(savedJobId), 1500);
    }

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [pollProgress]);

  // Audio Type switch helper
  const handleAudioTypeChange = (type: "music" | "general") => {
    setAudioType(type);
    if (type === "music") {
      setVadFilter(false);
      setEnableChunking(true);
    } else {
      setVadFilter(true);
      setEnableChunking(false);
    }
  };

  const handleFileSelect = (file: File) => {
    const validExtensions = [".mp3", ".wav", ".m4a", ".ogg", ".mp4", ".webm", ".flac", ".aac"];
    const fileExt = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();

    if (!validExtensions.includes(fileExt)) {
      setError(`ไฟล์ไม่รองรับ (รองรับ: ${validExtensions.join(", ")})`);
      return;
    }

    const MAX_SIZE_GB = 10;
    if (file.size > MAX_SIZE_GB * 1024 * 1024 * 1024) {
      setError(`ขนาดไฟล์เกินกำหนด (สูงสุด ${MAX_SIZE_GB} GB, ขนาดปัจจุบัน ${(file.size / (1024 * 1024 * 1024)).toFixed(2)} GB)`);
      return;
    }

    setError(null);
    setSelectedFile(file);
    if (audioUrl && !audioUrl.startsWith(BACKEND_URL)) {
      URL.revokeObjectURL(audioUrl);
    }
    setAudioUrl(URL.createObjectURL(file));
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleStartJob = async () => {
    if (!selectedFile) return;

    setError(null);
    setTranscript("");
    setSegments([]);
    setProgress(0);
    setElapsedSeconds(0);
    setRemainingSeconds(0);
    setJobStatus("queued");

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("audio_type", audioType);
    formData.append("vad_filter", String(vadFilter));
    formData.append("beam_size", fastMode ? "1" : "5");
    formData.append("chunk_duration", enableChunking ? String(chunkDuration) : "0");

    try {
      const response = await fetch(`${BACKEND_URL}/api/jobs`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(errorData?.detail || `Error: ${response.status} ${response.statusText}`);
      }

      const data = await response.json();
      const jobId = data.job_id;
      setActiveJobId(jobId);
      localStorage.setItem(STORAGE_KEY, jobId);

      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      pollTimerRef.current = setInterval(() => pollProgress(jobId), 1500);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "เกิดข้อผิดพลาดในการเริ่มถอดเสียง";
      setError(
        message.includes("Failed to fetch")
          ? "ไม่สามารถเชื่อมต่อกับ Python Backend ได้ (ตรวจสอบว่ารัน uvicorn main:app พอร์ต 8000 หรือยัง)"
          : message
      );
      setJobStatus("failed");
    }
  };

  const handleReset = () => {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    localStorage.removeItem(STORAGE_KEY);
    setActiveJobId(null);
    setJobStatus("idle");
    setProgress(0);
    setTranscript("");
    setSegments([]);
    setSelectedFile(null);
    setError(null);
  };

  const handleTimeUpdate = (e: React.SyntheticEvent<HTMLMediaElement>) => {
    const time = e.currentTarget.currentTime;
    setCurrentTime(time);

    const index = segments.findIndex((seg) => time >= seg.start && time <= seg.end);
    if (index !== -1 && index !== activeSegmentIndex) {
      setActiveSegmentIndex(index);
    }
  };

  const handleSeekSegment = (start: number) => {
    if (mediaRef.current) {
      mediaRef.current.currentTime = start;
      mediaRef.current.play().catch(() => {});
    }
  };

  const handleCopyToClipboard = async () => {
    if (!transcript) return;
    try {
      await navigator.clipboard.writeText(transcript);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch {
      setError("ไม่สามารถคัดลอกข้อความได้");
    }
  };

  const fetchHistory = async () => {
    setLoadingHistory(true);
    try {
      const res = await fetch(`${BACKEND_URL}/api/jobs?limit=30`);
      if (res.ok) {
        const jobs = await res.json();
        setHistoryJobs(jobs);
      }
    } catch (err) {
      console.error("Failed to load history:", err);
    } finally {
      setLoadingHistory(false);
    }
  };

  const selectHistoryJob = async (job: JobMeta) => {
    setShowHistoryModal(false);
    setActiveJobId(job.id);
    localStorage.setItem(STORAGE_KEY, job.id);
    if (job.status === "completed") {
      await loadCompletedJob(job.id);
    } else {
      setJobStatus(job.status);
      pollProgress(job.id);
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      pollTimerRef.current = setInterval(() => pollProgress(job.id), 1500);
    }
  };

  const getExportUrl = (format: string, timestamps: boolean = false) => {
    if (!activeJobId) return "#";
    return `${BACKEND_URL}/api/jobs/${activeJobId}/export?format=${format}&timestamps=${timestamps}`;
  };

  const isWorking = jobStatus === "queued" || jobStatus === "processing";

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 dark:bg-zinc-950 dark:text-zinc-100 py-10 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto space-y-8">
        {/* Header */}
        <header className="flex flex-col sm:flex-row items-center justify-between gap-4 border-b border-slate-200 dark:border-zinc-800 pb-6">
          <div className="space-y-1 text-center sm:text-left">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              faster-whisper large-v3-turbo (Local)
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight">
              ระบบถอดเสียงภาษาไทยความเร็วสูง
            </h1>
            <p className="text-slate-500 dark:text-zinc-400 text-xs sm:text-sm">
              รองรับเสียงพูด เสียงเพลง คาราโอเกะ พร้อมระบบทำงานเบื้องหลัง ป้องกันเน็ตหลุด / ปิดแท็บ
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setShowHistoryModal(true);
                fetchHistory();
              }}
              className="px-3 py-2 rounded-xl border border-slate-200 dark:border-zinc-800 hover:bg-slate-100 dark:hover:bg-zinc-800 text-xs font-medium text-slate-700 dark:text-zinc-300 flex items-center gap-2 cursor-pointer transition-colors"
            >
              <span>🕒 ประวัติการถอดเสียง</span>
            </button>

            {activeJobId && (
              <button
                onClick={handleReset}
                className="px-3 py-2 rounded-xl bg-slate-200 dark:bg-zinc-800 hover:bg-slate-300 dark:hover:bg-zinc-700 text-xs font-medium text-slate-700 dark:text-zinc-300 flex items-center gap-1.5 cursor-pointer transition-colors"
                title="ล้างสถานะงานปัจจุบันเพื่อเริ่มงานใหม่"
              >
                <span>➕ เริ่มงานใหม่</span>
              </button>
            )}
          </div>
        </header>

        {/* Progress & Live Stream Box (When Job is Active or Recovered) */}
        {isWorking && (
          <div className="bg-white dark:bg-zinc-900 shadow-md border-2 border-emerald-500/40 rounded-2xl p-6 space-y-4 animate-in fade-in">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="relative flex h-3 w-3">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
                </span>
                <span className="font-bold text-sm text-slate-800 dark:text-zinc-100">
                  {jobStatus === "queued" ? "กำลังรอคิวประมวลผล..." : "กำลังถอดเสียงในเบื้องหลัง (Background Worker)"}
                </span>
              </div>
              <div className="flex items-center gap-4 text-xs font-mono text-slate-500 dark:text-zinc-400">
                <span>⏱️ ใช้เวลา: {formatTimeClock(elapsedSeconds)}</span>
                {remainingSeconds > 0 && <span>⏳ คาดว่าจะเสร็จ: ~{formatTimeClock(remainingSeconds)}</span>}
                <span className="font-bold text-emerald-600 dark:text-emerald-400">{progress.toFixed(0)}%</span>
              </div>
            </div>

            {/* Progress Bar */}
            <div className="w-full bg-slate-100 dark:bg-zinc-800 rounded-full h-3 overflow-hidden">
              <div
                className="bg-emerald-500 h-3 rounded-full transition-all duration-500 ease-out"
                style={{ width: `${Math.max(5, progress)}%` }}
              ></div>
            </div>

            {/* Note about resilience */}
            <p className="text-[11px] text-slate-400 dark:text-zinc-500 flex items-center gap-1.5">
              <span>🛡️ ปลอดภัยจากอาการหลุด:</span> แม้คุณจะรีเฟรชหรือปิดบราวเซอร์
              ระบบจะยังคงถอดเสียงต่อในเครื่อง และกลับมาแสดงผลต่ออัตโนมัติ
            </p>

            {/* Live Streaming Segments Preview */}
            {segments.length > 0 && (
              <div className="mt-3 p-3 rounded-xl bg-slate-50 dark:bg-zinc-950 border border-slate-200 dark:border-zinc-800 max-h-36 overflow-y-auto space-y-1">
                <div className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 uppercase tracking-wide">
                  ข้อความสดที่ถอดได้เรียลไทม์:
                </div>
                {segments.slice(-3).map((seg, idx) => (
                  <div key={idx} className="text-xs text-slate-700 dark:text-zinc-300 font-mono">
                    <span className="text-slate-400 dark:text-zinc-500">[{formatTimestamp(seg.start)}]</span> {seg.text}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Upload Zone & Settings (Shown when not working or for new file) */}
        {!isWorking && jobStatus !== "completed" && (
          <div className="bg-white dark:bg-zinc-900 shadow-sm border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 sm:p-8 space-y-6">
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-8 sm:p-12 text-center cursor-pointer transition-all duration-200 ${
                isDragging
                  ? "border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/20"
                  : "border-slate-300 dark:border-zinc-700 hover:border-slate-400 dark:hover:border-zinc-600 bg-slate-50/50 dark:bg-zinc-900/50"
              }`}
            >
              <input
                type="file"
                ref={fileInputRef}
                className="hidden"
                accept=".mp3,.wav,.m4a,.ogg,.mp4,.webm,.flac,.aac,audio/*,video/mp4"
                onChange={(e) => {
                  if (e.target.files && e.target.files.length > 0) {
                    handleFileSelect(e.target.files[0]);
                  }
                }}
              />
              <div className="flex flex-col items-center gap-3">
                <div className="p-4 rounded-full bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400">
                  <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                    />
                  </svg>
                </div>
                <div>
                  <p className="text-base font-semibold text-slate-700 dark:text-zinc-200">
                    ลากไฟล์เสียงหรือวิดีโอมาวางที่นี่ หรือคลิกเพื่อเลือกไฟล์
                  </p>
                  <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">
                    รองรับไฟล์ .mp3, .mp4, .wav, .m4a, .ogg, .flac (ขนาดสูงสุด 10 GB)
                  </p>
                </div>
                {selectedFile && (
                  <div className="mt-2 inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-zinc-800 text-xs font-mono text-slate-700 dark:text-zinc-300">
                    <span>📄 {selectedFile.name}</span>
                    <span className="text-slate-400">({(selectedFile.size / (1024 * 1024)).toFixed(2)} MB)</span>
                  </div>
                )}
              </div>
            </div>

            {/* Media Player Preview */}
            {audioUrl && (
              <div className="p-4 bg-slate-50 dark:bg-zinc-800/60 rounded-xl space-y-2 border border-slate-200 dark:border-zinc-700/60">
                <div className="flex items-center justify-between text-xs font-medium text-slate-600 dark:text-zinc-300">
                  <span>ตัวอย่างไฟล์ (Media Preview)</span>
                  <span>{selectedFile?.name}</span>
                </div>
                {selectedFile?.name.toLowerCase().endsWith(".mp4") ? (
                  <video controls className="w-full max-h-64 rounded-lg bg-black" src={audioUrl}>
                    บราวเซอร์ของคุณไม่รองรับการเล่นวิดีโอ
                  </video>
                ) : (
                  <audio controls className="w-full h-10" src={audioUrl}>
                    บราวเซอร์ของคุณไม่รองรับการเล่นไฟล์เสียง
                  </audio>
                )}
              </div>
            )}

            {/* Audio Profile & Options */}
            <div className="space-y-4 pt-1">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400 mb-2">
                  1. เลือกโหมดประเภทเสียง (Audio Mode)
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => handleAudioTypeChange("music")}
                    className={`p-3.5 rounded-xl border text-left transition-all flex items-start gap-3 cursor-pointer ${
                      audioType === "music"
                        ? "border-emerald-500 bg-emerald-50/60 dark:bg-emerald-950/30 ring-2 ring-emerald-500/20"
                        : "border-slate-200 dark:border-zinc-800 hover:border-slate-300 dark:hover:border-zinc-700 bg-slate-50/50 dark:bg-zinc-900/50"
                    }`}
                  >
                    <span className="text-2xl mt-0.5">🎵</span>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm text-slate-800 dark:text-zinc-100">
                          เสียงเพลง / ร้องเพลง
                        </span>
                        {audioType === "music" && (
                          <span className="text-[10px] font-bold bg-emerald-500 text-white px-1.5 py-0.5 rounded">
                            แนะนำ
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-500 dark:text-zinc-400 leading-relaxed">
                        สำหรับเพลง คาราโอเกะ หรือไฟล์ที่มีดนตรีบรรเลงดัง (ปิด VAD และปรับค่าไม่ให้ข้ามเนื้อเพลง)
                      </p>
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleAudioTypeChange("general")}
                    className={`p-3.5 rounded-xl border text-left transition-all flex items-start gap-3 cursor-pointer ${
                      audioType === "general"
                        ? "border-emerald-500 bg-emerald-50/60 dark:bg-emerald-950/30 ring-2 ring-emerald-500/20"
                        : "border-slate-200 dark:border-zinc-800 hover:border-slate-300 dark:hover:border-zinc-700 bg-slate-50/50 dark:bg-zinc-900/50"
                    }`}
                  >
                    <span className="text-2xl mt-0.5">🎙️</span>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm text-slate-800 dark:text-zinc-100">
                          เสียงพูดทั่วไป / ประชุม
                        </span>
                      </div>
                      <p className="text-xs text-slate-500 dark:text-zinc-400 leading-relaxed">
                        สำหรับการสนทนา ประชุม สัมภาษณ์ บรรยาย (เปิด VAD ช่วยตัดความเงียบเพื่อความรวดเร็ว)
                      </p>
                    </div>
                  </button>
                </div>
              </div>

              {/* Speed & Tuning Options */}
              <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-zinc-800/40 border border-slate-200 dark:border-zinc-800 space-y-3">
                {/* Fast Mode Toggle */}
                <div className="flex items-center justify-between pb-2.5 border-b border-slate-200/60 dark:border-zinc-700/60">
                  <div className="flex items-center gap-2.5">
                    <span className="text-lg">⚡</span>
                    <div>
                      <div className="flex items-center gap-2">
                        <label
                          className="text-xs sm:text-sm font-semibold text-slate-700 dark:text-zinc-200 cursor-pointer"
                          onClick={() => setFastMode(!fastMode)}
                        >
                          โหมดประมวลผลเร็ว (Fast Mode - beam_size=1)
                        </label>
                        <span className="text-[10px] bg-amber-500/20 text-amber-700 dark:text-amber-300 font-bold px-1.5 py-0.5 rounded">
                          เร็วขึ้น 2-3 เท่าบน CPU
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-500 dark:text-zinc-400">
                        {fastMode
                          ? "เปิดอยู่: ลดเวลาถอดเสียงลงอย่างมาก เหมาะสำหรับ CPU ทั่วไป"
                          : "ปิดอยู่: ใช้ Precision Mode (beam_size=5) แม่นยำสูงสุดแต่อาจใช้เวลานานขึ้น"}
                      </p>
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={fastMode}
                    onChange={(e) => setFastMode(e.target.checked)}
                    className="w-4 h-4 rounded text-emerald-600 focus:ring-emerald-500 accent-emerald-600 cursor-pointer"
                  />
                </div>

                {/* Chunking Option */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <span className="text-lg">⏱️</span>
                    <div>
                      <label
                        className="text-xs sm:text-sm font-semibold text-slate-700 dark:text-zinc-200 cursor-pointer"
                        onClick={() => setEnableChunking(!enableChunking)}
                      >
                        แบ่งถอดทีละช่วง (Audio Chunking - ทีละ {chunkDuration} วินาที)
                      </label>
                      <p className="text-[11px] text-slate-500 dark:text-zinc-400">
                        ถอดทีละช่วงแล้วนำมารวมกัน ป้องกันปัญหาโมเดลหยุดกลางคัน หรือข้ามช่วง Solo ดนตรี
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 self-end sm:self-center">
                    {enableChunking && (
                      <select
                        value={chunkDuration}
                        onChange={(e) => setChunkDuration(Number(e.target.value))}
                        className="text-xs rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2.5 py-1 text-slate-700 dark:text-zinc-200 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                      >
                        <option value={30}>ท่อนละ 30 วิ</option>
                        <option value={60}>ท่อนละ 60 วิ (แนะนำ)</option>
                        <option value={90}>ท่อนละ 90 วิ</option>
                        <option value={120}>ท่อนละ 2 นาที</option>
                      </select>
                    )}
                    <input
                      type="checkbox"
                      checked={enableChunking}
                      onChange={(e) => setEnableChunking(e.target.checked)}
                      className="w-4 h-4 rounded text-emerald-600 focus:ring-emerald-500 accent-emerald-600 cursor-pointer"
                    />
                  </div>
                </div>

                {/* VAD Option */}
                <div className="flex items-center justify-between pt-2.5 border-t border-slate-200/60 dark:border-zinc-700/60">
                  <div className="flex items-center gap-2.5">
                    <span className="text-lg">🔇</span>
                    <div>
                      <label
                        className="text-xs sm:text-sm font-semibold text-slate-700 dark:text-zinc-200 cursor-pointer"
                        onClick={() => setVadFilter(!vadFilter)}
                      >
                        VAD Filter (กรองตัดช่วงเงียบ)
                      </label>
                      <p className="text-[11px] text-slate-500 dark:text-zinc-400">
                        {vadFilter
                          ? "กำลังเปิดใช้งาน (เหมาะกับเสียงพูด ไม่เหมาะกับเพลง)"
                          : "ปิดอยู่ (แนะนำสำหรับเพลง เพื่อป้องกันเสียงร้องโดนตัดทิ้ง)"}
                      </p>
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={vadFilter}
                    onChange={(e) => setVadFilter(e.target.checked)}
                    className="w-4 h-4 rounded text-emerald-600 focus:ring-emerald-500 accent-emerald-600 cursor-pointer"
                  />
                </div>
              </div>
            </div>

            {/* Action Button */}
            <div className="flex items-center justify-end">
              <button
                onClick={handleStartJob}
                disabled={!selectedFile}
                className={`w-full sm:w-auto px-6 py-3 rounded-xl font-medium text-sm flex items-center justify-center gap-2 transition-all shadow-sm ${
                  !selectedFile
                    ? "bg-slate-200 dark:bg-zinc-800 text-slate-400 cursor-not-allowed"
                    : "bg-emerald-600 hover:bg-emerald-700 text-white cursor-pointer active:scale-95"
                }`}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 100-6 3 3 0 000 6z" />
                </svg>
                <span>เริ่มถอดเสียงภาษาไทย (Background Job)</span>
              </button>
            </div>
          </div>
        )}

        {/* Error Message */}
        {error && (
          <div className="p-4 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-300 text-sm flex items-start gap-2">
            <svg className="w-5 h-5 shrink-0 text-red-500 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>{error}</span>
          </div>
        )}

        {/* Results Section (When completed) */}
        {jobStatus === "completed" && (
          <div className="bg-white dark:bg-zinc-900 shadow-sm border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 sm:p-8 space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-slate-100 dark:border-zinc-800">
              <div>
                <div className="flex items-center gap-2">
                  <span className="p-1 rounded-md bg-emerald-100 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  </span>
                  <h2 className="text-xl font-bold text-slate-800 dark:text-zinc-100">
                    ผลลัพธ์การถอดเสียง (เสร็จสมบูรณ์)
                  </h2>
                </div>
                <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">
                  คลิกที่ประโยคใดเพื่อฟังเสียงตรงช่วงเวลานั้นได้ทันที
                </p>
              </div>

              {/* Action Buttons & Export Dropdown */}
              <div className="flex items-center gap-2">
                <button
                  onClick={handleCopyToClipboard}
                  disabled={!transcript}
                  className="px-3.5 py-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800 text-xs font-medium text-slate-700 dark:text-zinc-200 flex items-center gap-1.5 transition-colors cursor-pointer"
                  title="คัดลอกข้อความ"
                >
                  {copySuccess ? (
                    <>
                      <svg className="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      <span>คัดลอกแล้ว!</span>
                    </>
                  ) : (
                    <>
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                      </svg>
                      <span>คัดลอกข้อความ</span>
                    </>
                  )}
                </button>

                {/* Export Dropdown */}
                <div className="relative">
                  <button
                    onClick={() => setShowExportMenu(!showExportMenu)}
                    className="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer shadow-sm"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    <span>ดาวน์โหลด (Export) ▾</span>
                  </button>

                  {showExportMenu && (
                    <div
                      onMouseLeave={() => setShowExportMenu(false)}
                      className="absolute right-0 mt-2 w-56 rounded-xl bg-white dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700 shadow-xl py-1 z-30 divide-y divide-slate-100 dark:divide-zinc-700"
                    >
                      <div className="py-1">
                        <a
                          href={getExportUrl("txt")}
                          download
                          className="flex items-center gap-2 px-4 py-2 text-xs text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-700/60"
                        >
                          <span>📄</span> ข้อความล้วน (.txt)
                        </a>
                        <a
                          href={getExportUrl("txt", true)}
                          download
                          className="flex items-center gap-2 px-4 py-2 text-xs text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-700/60"
                        >
                          <span>⏱️</span> ข้อความพร้อมช่วงเวลา (.txt)
                        </a>
                      </div>
                      <div className="py-1">
                        <a
                          href={getExportUrl("srt")}
                          download
                          className="flex items-center gap-2 px-4 py-2 text-xs text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-700/60"
                        >
                          <span>🎬</span> ซับไตเติล SubRip (.srt)
                        </a>
                        <a
                          href={getExportUrl("vtt")}
                          download
                          className="flex items-center gap-2 px-4 py-2 text-xs text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-700/60"
                        >
                          <span>🌐</span> ซับไตเติล WebVTT (.vtt)
                        </a>
                      </div>
                      <div className="py-1">
                        <a
                          href={getExportUrl("json")}
                          download
                          className="flex items-center gap-2 px-4 py-2 text-xs text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-700/60"
                        >
                          <span>🔧</span> ข้อมูลดิบ Structured (.json)
                        </a>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Interactive Audio Player Bar */}
            {audioUrl && (
              <div className="p-3 bg-slate-100 dark:bg-zinc-800/80 rounded-xl space-y-1">
                <div className="flex items-center justify-between text-[11px] font-medium text-slate-500 dark:text-zinc-400 px-1">
                  <span>เครื่องเล่นเสียง (คลิก Segment เพื่อข้ามไปยังจุดนั้น)</span>
                  <span>{formatTimeClock(currentTime)}</span>
                </div>
                <audio
                  ref={mediaRef}
                  controls
                  className="w-full h-10"
                  src={audioUrl}
                  onTimeUpdate={handleTimeUpdate}
                >
                  บราวเซอร์ของคุณไม่รองรับการเล่นไฟล์เสียง
                </audio>
              </div>
            )}

            {/* Editable Textarea */}
            <div className="relative">
              <textarea
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
                placeholder="ข้อความที่ถอดได้จะแสดงที่นี่..."
                rows={7}
                className="w-full p-4 rounded-xl border border-slate-200 dark:border-zinc-800 bg-slate-50/50 dark:bg-zinc-950/50 text-slate-800 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500 font-sans leading-relaxed text-sm sm:text-base resize-y"
              />
            </div>

            {/* Interactive Timestamped Segments */}
            {segments.length > 0 && (
              <div className="border border-slate-200 dark:border-zinc-800 rounded-xl overflow-hidden">
                <button
                  onClick={() => setShowSegments(!showSegments)}
                  className="w-full px-4 py-3 bg-slate-50 dark:bg-zinc-800/50 hover:bg-slate-100 dark:hover:bg-zinc-800 flex items-center justify-between text-xs sm:text-sm font-semibold text-slate-700 dark:text-zinc-200 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <svg className="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>ช่วงเวลาและข้อความย่อยแบบซิงค์เสียง (Segments: {segments.length})</span>
                  </div>
                  <svg
                    className={`w-4 h-4 text-slate-400 transform transition-transform duration-200 ${
                      showSegments ? "rotate-180" : ""
                    }`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {showSegments && (
                  <div className="p-3 divide-y divide-slate-100 dark:divide-zinc-800/80 max-h-80 overflow-y-auto space-y-1.5">
                    {segments.map((seg, idx) => {
                      const isActive = activeSegmentIndex === idx;
                      return (
                        <div
                          key={idx}
                          ref={isActive ? activeSegmentRef : null}
                          onClick={() => handleSeekSegment(seg.start)}
                          className={`p-2.5 rounded-lg flex items-start gap-3 text-sm cursor-pointer transition-all ${
                            isActive
                              ? "bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-500/50 ring-1 ring-emerald-500/30"
                              : "hover:bg-slate-50 dark:hover:bg-zinc-800/40"
                          }`}
                        >
                          <span
                            className={`font-mono text-xs px-2 py-0.5 rounded shrink-0 mt-0.5 ${
                              isActive
                                ? "bg-emerald-500 text-white font-bold"
                                : "bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400"
                            }`}
                          >
                            ▶ {formatTimestamp(seg.start)} - {formatTimestamp(seg.end)}
                          </span>
                          <p
                            className={`leading-normal ${
                              isActive
                                ? "text-emerald-900 dark:text-emerald-200 font-semibold"
                                : "text-slate-800 dark:text-zinc-200"
                            }`}
                          >
                            {seg.text}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* History Modal */}
        {showHistoryModal && (
          <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
            <div className="bg-white dark:bg-zinc-900 rounded-2xl max-w-2xl w-full border border-slate-200 dark:border-zinc-800 shadow-2xl p-6 space-y-4 max-h-[85vh] flex flex-col">
              <div className="flex items-center justify-between border-b border-slate-200 dark:border-zinc-800 pb-3">
                <div className="flex items-center gap-2">
                  <span className="text-xl">📜</span>
                  <h3 className="font-bold text-lg text-slate-800 dark:text-zinc-100">
                    ประวัติการถอดเสียง (Transcription History)
                  </h3>
                </div>
                <button
                  onClick={() => setShowHistoryModal(false)}
                  className="text-slate-400 hover:text-slate-600 dark:hover:text-zinc-200 p-1 rounded-lg"
                >
                  ✕
                </button>
              </div>

              <div className="flex-1 overflow-y-auto space-y-2">
                {loadingHistory ? (
                  <div className="text-center py-10 text-slate-400 text-sm">กำลังโหลดประวัติ...</div>
                ) : historyJobs.length === 0 ? (
                  <div className="text-center py-10 text-slate-400 text-sm">ยังไม่มีประวัติการถอดเสียง</div>
                ) : (
                  historyJobs.map((job) => (
                    <div
                      key={job.id}
                      onClick={() => selectHistoryJob(job)}
                      className="p-3 rounded-xl border border-slate-200 dark:border-zinc-800 hover:border-emerald-500 hover:bg-slate-50 dark:hover:bg-zinc-800/50 cursor-pointer flex items-center justify-between transition-all"
                    >
                      <div className="space-y-1">
                        <div className="font-medium text-sm text-slate-800 dark:text-zinc-100 flex items-center gap-2">
                          <span>{job.audio_type === "music" ? "🎵" : "🎙️"}</span>
                          <span>{job.filename}</span>
                        </div>
                        <div className="text-[11px] text-slate-400 flex items-center gap-3">
                          <span>{new Date(job.created_at).toLocaleString("th-TH")}</span>
                          <span>{(job.filesize / (1024 * 1024)).toFixed(1)} MB</span>
                          <span>{job.beam_size === 1 ? "Fast Mode" : "Precision Mode"}</span>
                        </div>
                      </div>
                      <div>
                        <span
                          className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                            job.status === "completed"
                              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                              : job.status === "failed"
                              ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
                              : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                          }`}
                        >
                          {job.status === "completed"
                            ? "สำเร็จ"
                            : job.status === "failed"
                            ? "ล้มเหลว"
                            : "กำลังทำ"}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>

              <div className="pt-2 border-t border-slate-200 dark:border-zinc-800 flex justify-end">
                <button
                  onClick={() => setShowHistoryModal(false)}
                  className="px-4 py-2 rounded-xl bg-slate-100 dark:bg-zinc-800 text-xs font-semibold text-slate-700 dark:text-zinc-200 hover:bg-slate-200 dark:hover:bg-zinc-700 cursor-pointer"
                >
                  ปิดหน้าต่าง
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
