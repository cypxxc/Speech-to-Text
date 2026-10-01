# Speech-to-Text (Thai Speech-to-Text System)

ระบบถอดเสียงภาษาไทยและเสียงเพลงความแม่นยำสูง (Thai Speech-to-Text) ทำงานบนเครื่องของคุณเอง (Local Inference) โดยใช้ **Faster-Whisper (large-v3-turbo)** พร้อมรองรับการประมวลผลทั้งเสียงพูดทั่วไปและเสียงเพลงที่มีดนตรีประกอบ

## ✨ ฟีเจอร์เด่น
- **รองรับภาษาไทย:** ถอดเสียงภาษาไทยได้อย่างแม่นยำและรวดเร็ว
- **โหมดเสียงเพลง / ร้องเพลง (Music Mode):** ปรับจูนโมเดลเพื่อป้องกันเสียงร้องถูกกลบหรือถูกตัดทิ้งจากเสียงดนตรี (ปิด VAD Filter และขยาย Threshold)
- **ระบบแบ่งถอดทีละช่วง (Audio Chunking):** รองรับการแบ่งถอดเสียงเป็นท่อนย่อย (เช่น ทีละ 60 วินาที) ป้องกันโมเดลหยุดกลางคันจากท่อน Solo หรือดนตรีคั่น
- **ตัวเล่นไฟล์ตัวอย่าง (Media Player Preview):** รองรับการเล่นไฟล์เสียงและวิดีโอก่อนถอดเสียง
- **Timestamped Segments:** แสดงช่วงเวลาเริ่มต้น-สิ้นสุดของแต่ละประโยค พร้อมส่งออกเป็นไฟล์ `.txt` ได้ทันที

## 🛠️ โครงสร้างระบบ
- **Frontend:** Next.js (App Router), Tailwind CSS, TypeScript
- **Backend:** FastAPI, Python, Faster-Whisper, PyAV

## 🚀 วิธีการติดตั้งและเริ่มใช้งาน

### 1. รันระบบทั้งหมดแบบอัตโนมัติ (Windows)
ดับเบิลคลิกไฟล์:
```cmd
run_all.bat
```
*(สคริปต์จะสร้าง Virtual Environment, ติดตั้งแพ็กเกจที่จำเป็น และเปิดทั้ง Backend และ Frontend ในหน้าต่างแยกให้อัตโนมัติ)*

### 2. หรือเริ่มรันแยกทีละส่วน
**Backend (FastAPI):**
```bash
cd backend
python -m venv venv
# สำหรับ Windows:
call venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --port 8000 --reload
```

**Frontend (Next.js):**
```bash
npm install
npm run dev
```

เปิดเว็บเบราว์เซอร์ไปที่: [http://localhost:3000](http://localhost:3000)
Backend API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)
