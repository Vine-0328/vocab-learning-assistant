param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name VocabAssistant --icon data/app_icon.ico --add-data "data;data" vocab_learner.py
if ($LASTEXITCODE -ne 0) { throw "Windows 打包失败" }
Write-Host "完成：$PSScriptRoot\dist\VocabAssistant.exe"
