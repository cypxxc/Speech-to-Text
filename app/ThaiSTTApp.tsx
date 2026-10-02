"use client";

import React, { useState, useRef } from "react";

interface Segment {
  start: number;
  end: number;
  text: string;
}

interface TranscriptionResponse {
  text: string;
  segments: Segment[];
}

export default function ThaiSTTApp() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [segments, setSegments] = useState<Segment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [copySuccess, setCopySuccess] = useState(false);
  const [showSegments, setShowSegments] = useState(true);

  // Real-time Progress State
  const [progressPct, setProgressPct] = useState<number>(0);
  const [progressMessage, setProgressMessage] = useState<string>("");
  const [currentChunkInfo, setCurrentChunkInfo] = useState<{ current: number; total: number } | null>(null);

  // Audio Tuning & Chunking Options
  const [audioType, setAudioType] = useState<"music" | "general">("music");
  const [vadFilter, setVadFilter] = useState(false);
  const [enableChunking, setEnableChunking] = useState(true);
  const [chunkDuration, setChunkDuration] = useState(60);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

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
    if (audioUrl) {
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

  const handleTranscribe = async () => {
    if (!selectedFile) return;

    setIsLoading(true);
    setError(null);
    setTranscript("");
    setSegments([]);
    setProgressPct(5);
    setProgressMessage("กำลังเชื่อมต่อเซิร์ฟเวอร์และส่งไฟล์...");
    setCurrentChunkInfo(null);

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("audio_type", audioType);
    formData.append("vad_filter", String(vadFilter));
    formData.append("chunk_duration", enableChunking ? String(chunkDuration) : "0");

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      const response = await fetch("http://localhost:8000/api/transcribe_stream", {
        method: "POST",
        body: formData,
        signal: abortController.signal,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(errorData?.detail || `Error: ${response.status} ${response.statusText}`);
      }

      if (!response.body) {
        throw new Error("ReadableStream not supported by browser");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        // Keep the last unprocessed part in buffer
        buffer = parts.pop() || "";

        for (const part of parts) {
          const lines = part.split("\n");
          let eventType = "message";
          let dataStr = "";

          for (const line of lines) {
            if (line.startsWith("event: ")) {
              eventType = line.replace("event: ", "").trim();
            } else if (line.startsWith("data: ")) {
              dataStr += line.replace("data: ", "").trim();
            }
          }

          if (!dataStr) continue;

          try {
            const data = JSON.parse(dataStr);

            if (eventType === "progress") {
              if (data.progress !== undefined) setProgressPct(data.progress);
              if (data.message) setProgressMessage(data.message);
              if (data.current_chunk && data.total_chunks) {
                setCurrentChunkInfo({ current: data.current_chunk, total: data.total_chunks });
              }
            } else if (eventType === "segment") {
              setSegments((prev) => [...prev, data]);
              setTranscript((prev) => (prev ? `${prev} ${data.text}` : data.text));
            } else if (eventType === "complete") {
              setProgressPct(100);
              setProgressMessage("ถอดเสียงเสร็จสมบูรณ์เรียบร้อย!");
              if (data.text) setTranscript(data.text);
              if (data.segments) setSegments(data.segments);
            } else if (eventType === "error") {
              throw new Error(data.detail || "เกิดข้อผิดพลาดในการประมวลผล");
            }
          } catch (jsonErr: any) {
            if (jsonErr.message && !jsonErr.message.includes("JSON")) {
              throw jsonErr;
            }
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error)?.name === "AbortError") {
        setProgressMessage("ยกเลิกการถอดเสียงแล้ว");
        return;
      }
      const message = err instanceof Error ? err.message : "เกิดข้อผิดพลาดในการถอดเสียง";
      setError(
        message.includes("Failed to fetch")
          ? "ไม่สามารถเชื่อมต่อกับ Python Backend ได้ (ตรวจสอบว่ารันพอร์ต 8000 หรือยัง)"
          : message
      );
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  const handleCancelTranscribe = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
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

  const downloadFile = (content: string, filename: string, type: string) => {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const getBaseFilename = () => {
    return selectedFile?.name.replace(/\.[^/.]+$/, "") || "transcript";
  };

  const handleDownloadTxt = () => {
    if (!transcript) return;
    downloadFile(transcript, `${getBaseFilename()}.txt`, "text/plain;charset=utf-8");
  };

  const formatSrtTime = (seconds: number) => {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 1000);
    return `${hrs.toString().padStart(2, "0")}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")},${ms.toString().padStart(3, "0")}`;
  };

  const formatVttTime = (seconds: number) => {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 1000);
    return `${hrs.toString().padStart(2, "0")}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(3, "0")}.${ms.toString().padStart(3, "0")}`;
  };

  const handleDownloadSrt = () => {
    if (segments.length === 0) return;
    const srtContent = segments
      .map((seg, idx) => {
        return `${idx + 1}\n${formatSrtTime(seg.start)} --> ${formatSrtTime(seg.end)}\n${seg.text}\n`;
      })
      .join("\n");
    downloadFile(srtContent, `${getBaseFilename()}.srt`, "text/plain;charset=utf-8");
  };

  const handleDownloadVtt = () => {
    if (segments.length === 0) return;
    const vttContent =
      "WEBVTT\n\n" +
      segments
        .map((seg, idx) => {
          return `${idx + 1}\n${formatVttTime(seg.start)} --> ${formatVttTime(seg.end)}\n${seg.text}\n`;
        })
        .join("\n");
    downloadFile(vttContent, `${getBaseFilename()}.vtt`, "text/vtt;charset=utf-8");
  };

  const formatTimestamp = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 10);
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}.${ms}`;
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 dark:bg-zinc-950 dark:text-zinc-100 py-10 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto space-y-8">
        {/* Header */}
        <header className="text-center space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            faster-whisper large-v3-turbo
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight">
            ระบบถอดเสียงภาษาไทย (Thai Speech-to-Text)
          </h1>
          <p className="text-slate-500 dark:text-zinc-400 max-w-xl mx-auto text-sm sm:text-base">
            แปลงไฟล์เสียงเป็นข้อความภาษาไทยด้วย AI ทำงานบนเครื่องของคุณ (Local Inference)
          </p>
        </header>

        {/* Upload Zone */}
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

          {/* Media Player Preview (Audio / Video) */}
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
                เลือกโหมดการถอดเสียง (Audio Mode)
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

            {/* Advanced Chunking & VAD Options */}
            <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-zinc-800/40 border border-slate-200 dark:border-zinc-800 space-y-3">
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
                      ถอดทีละ {chunkDuration} วินาทีแล้วนำมารวมกัน ป้องกันปัญหาโมเดลหยุดกลางคัน หรือข้ามช่วง Solo ดนตรี
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

          {/* Action Button & Progress */}
          <div className="space-y-4">
            <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
              <div className="text-xs text-slate-500 dark:text-zinc-400">
                {isLoading && (
                  <span className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
                    กำลังสตรีมผลลัพธ์แบบ Real-time...
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
                {isLoading && (
                  <button
                    type="button"
                    onClick={handleCancelTranscribe}
                    className="px-4 py-2.5 rounded-xl border border-red-200 dark:border-red-900/60 bg-red-50 hover:bg-red-100 dark:bg-red-950/40 text-red-700 dark:text-red-300 font-medium text-xs sm:text-sm transition-all cursor-pointer"
                  >
                    ยกเลิก
                  </button>
                )}
                <button
                  onClick={handleTranscribe}
                  disabled={!selectedFile || isLoading}
                  className={`w-full sm:w-auto px-6 py-3 rounded-xl font-medium text-sm flex items-center justify-center gap-2 transition-all shadow-sm ${
                    !selectedFile || isLoading
                      ? "bg-slate-200 dark:bg-zinc-800 text-slate-400 cursor-not-allowed"
                      : "bg-emerald-600 hover:bg-emerald-700 text-white cursor-pointer active:scale-95"
                  }`}
                >
                  {isLoading ? (
                    <>
                      <svg className="animate-spin h-4 w-4 text-white" viewBox="0 0 24 24" fill="none">
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        ></circle>
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                        ></path>
                      </svg>
                      <span>กำลังประมวลผล ({progressPct}%)...</span>
                    </>
                  ) : (
                    <>
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 100-6 3 3 0 000 6z" />
                      </svg>
                      <span>เริ่มถอดเสียงภาษาไทย</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Real-time Progress Bar & Status Card */}
            {isLoading && (
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-zinc-800/60 border border-slate-200 dark:border-zinc-700/80 space-y-2.5 transition-all">
                <div className="flex items-center justify-between text-xs font-medium">
                  <div className="flex items-center gap-2 text-slate-700 dark:text-zinc-200">
                    <span className="font-semibold text-emerald-600 dark:text-emerald-400">
                      {progressMessage || "กำลังประมวลผล..."}
                    </span>
                    {currentChunkInfo && (
                      <span className="px-2 py-0.5 rounded bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 font-mono text-[11px]">
                        Chunk {currentChunkInfo.current}/{currentChunkInfo.total}
                      </span>
                    )}
                  </div>
                  <span className="font-mono text-emerald-600 dark:text-emerald-400 font-bold">{progressPct}%</span>
                </div>

                <div className="w-full h-2.5 bg-slate-200 dark:bg-zinc-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-emerald-500 to-teal-500 rounded-full transition-all duration-300 ease-out"
                    style={{ width: `${progressPct}%` }}
                  ></div>
                </div>

                <div className="flex justify-between items-center text-[11px] text-slate-500 dark:text-zinc-400">
                  <span>ข้อความและท่อนเสียงจะทยอยแสดงผลด้านล่างแบบสดๆ</span>
                  <span>{segments.length} ท่อนที่พบแล้ว</span>
                </div>
              </div>
            )}
          </div>

          {/* Error Message */}
          {error && (
            <div className="p-4 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-300 text-sm flex items-start gap-2">
              <svg className="w-5 h-5 shrink-0 text-red-500 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>{error}</span>
            </div>
          )}
        </div>

        {/* Results Section */}
        {(transcript || isLoading || segments.length > 0) && (
          <div className="bg-white dark:bg-zinc-900 shadow-sm border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 sm:p-8 space-y-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-slate-100 dark:border-zinc-800">
              <div>
                <h2 className="text-xl font-bold text-slate-800 dark:text-zinc-100">
                  ผลลัพธ์การถอดเสียง (Transcription)
                </h2>
                <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">
                  สามารถแก้ไขข้อความได้โดยตรงในช่องด้านล่าง หรือเลือกส่งออกรูปแบบที่ต้องการ
                </p>
              </div>

              {/* Action Buttons: Copy & Subtitle Exports */}
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={handleCopyToClipboard}
                  disabled={!transcript}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800 text-xs font-medium text-slate-700 dark:text-zinc-200 flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
                  title="Copy to clipboard"
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

                {/* Export TXT */}
                <button
                  onClick={handleDownloadTxt}
                  disabled={!transcript}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800 text-xs font-medium text-slate-700 dark:text-zinc-200 flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
                  title="Download as Plain Text (.txt)"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  <span>.TXT</span>
                </button>

                {/* Export SRT Subtitle */}
                <button
                  onClick={handleDownloadSrt}
                  disabled={segments.length === 0}
                  className="px-3 py-1.5 rounded-lg border border-emerald-300 dark:border-emerald-700/60 bg-emerald-50/50 dark:bg-emerald-950/20 hover:bg-emerald-100 text-xs font-medium text-emerald-800 dark:text-emerald-300 flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
                  title="Download as SubRip Subtitle (.srt)"
                >
                  <svg className="w-4 h-4 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z" />
                  </svg>
                  <span className="font-semibold">.SRT</span>
                </button>

                {/* Export VTT Subtitle */}
                <button
                  onClick={handleDownloadVtt}
                  disabled={segments.length === 0}
                  className="px-3 py-1.5 rounded-lg border border-teal-300 dark:border-teal-700/60 bg-teal-50/50 dark:bg-teal-950/20 hover:bg-teal-100 text-xs font-medium text-teal-800 dark:text-teal-300 flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
                  title="Download as WebVTT Subtitle (.vtt)"
                >
                  <svg className="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  <span className="font-semibold">.VTT</span>
                </button>
              </div>
            </div>

            {/* Editable Textarea */}
            <div className="relative">
              <textarea
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
                placeholder={isLoading ? "กำลังประมวลผลการถอดเสียง..." : "ข้อความที่ถอดได้จะแสดงที่นี่..."}
                rows={8}
                className="w-full p-4 rounded-xl border border-slate-200 dark:border-zinc-800 bg-slate-50/50 dark:bg-zinc-950/50 text-slate-800 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500 font-sans leading-relaxed text-sm sm:text-base resize-y"
              />
            </div>

            {/* Collapsible Timestamped Segments */}
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
                    <span>ช่วงเวลาและข้อความย่อย (Timestamped Segments: {segments.length})</span>
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
                  <div className="p-4 divide-y divide-slate-100 dark:divide-zinc-800/80 max-h-96 overflow-y-auto space-y-2">
                    {segments.map((seg, idx) => (
                      <div key={idx} className="pt-2 first:pt-0 flex items-start gap-3 text-sm">
                        <span className="font-mono text-xs px-2 py-0.5 rounded bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 shrink-0 mt-0.5">
                          {formatTimestamp(seg.start)} - {formatTimestamp(seg.end)}
                        </span>
                        <p className="text-slate-800 dark:text-zinc-200 leading-normal">
                          {seg.text}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
