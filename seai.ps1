# SEAI PowerShell 入口脚本
# 用法: seai --start | seai --status | seai --stop | seai --help
# 将此脚本所在目录添加到 PATH 环境变量后即可在任意位置使用

param(
    [Parameter(Position=0)]
    [string]$Command = "--help"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ScriptDir "seai_cli.py"

if (-not (Test-Path $PythonScript)) {
    Write-Host "[SEAI 错误] 找不到 seai_cli.py，请确保脚本位于 SEAI 安装目录" -ForegroundColor Red
    exit 1
}

$PythonCmd = $null
$PythonPaths = @(
    (Get-Command python -ErrorAction SilentlyContinue).Source,
    (Get-Command python3 -ErrorAction SilentlyContinue).Source,
    (Get-Command py -ErrorAction SilentlyContinue).Source
)

foreach ($p in $PythonPaths) {
    if ($p) {
        $PythonCmd = $p
        break
    }
}

if (-not $PythonCmd) {
    Write-Host "[SEAI 错误] 未找到 Python，请确保已安装 Python 并添加到 PATH" -ForegroundColor Red
    exit 1
}

& $PythonCmd $PythonScript $Command