const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const isWin = process.platform === 'win32';
const venvPythonWin = path.join(__dirname, '..', 'backend', 'venv', 'Scripts', 'python.exe');
const venvPythonUnix = path.join(__dirname, '..', 'backend', 'venv', 'bin', 'python');

let pythonCmd = 'python';
if (isWin && fs.existsSync(venvPythonWin)) {
  pythonCmd = venvPythonWin;
} else if (!isWin && fs.existsSync(venvPythonUnix)) {
  pythonCmd = venvPythonUnix;
}

const args = ['-m', 'uvicorn', 'main:app', '--app-dir', 'backend', '--port', '8000', '--reload'];

console.log(`[Backend Runner] Using Python: ${pythonCmd}`);
const proc = spawn(pythonCmd, args, {
  stdio: 'inherit',
  shell: false,
  env: {
    ...process.env,
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8'
  }
});

proc.on('close', (code) => {
  process.exit(code || 0);
});

proc.on('error', (err) => {
  console.error('[Backend Runner] Failed to start backend:', err);
  process.exit(1);
});
