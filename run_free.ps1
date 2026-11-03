# Double-click-free runner: asks for the Groq key (typing is hidden), checks the setup, then runs the experiment.
# Usage (PowerShell, inside this folder):   .\run_free.ps1
$sec = Read-Host "Paste your Groq API key (hidden), then press Enter" -AsSecureString
$env:GROQ_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
python check_setup.py --config config.free.json
Write-Host "`nStarting the experiment. Safe to stop with Ctrl+C; run .\run_free.ps1 again to resume." -ForegroundColor Cyan
python run_experiments.py --config config.free.json --out results.jsonl
Write-Host "`nDone or stopped. Rows so far:" (Get-Content results.jsonl).Count
