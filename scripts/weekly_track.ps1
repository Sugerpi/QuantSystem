#Requires -Version 5.1
<#
  QuantCore — 每週追蹤自動化
  ----------------------------------------------------------------------------
  流程：
    1) 建立新快照（snapshots/<date>_<hash>）；建立失敗即中止，
       不在舊 / 半成品資料上跑回測（資料源交叉驗證 §4.5 超標會讓 create 非零退出）。
    2) 以生產 config（default.yaml）+ 剛建的新快照，跑一次全策略回測 → runs/<date>_weekly。
    3) 全程寫 logs/weekly/<stamp>.log。

  設計取捨：
    * 直接呼叫引擎 CLI（snapshot / runner），不走 Run Lab 的 job 排程器——
      後者的 pid 存活檢查在極端併發下會誤判 running→failed；單獨排程跑一個回測不需要它。
    * 不修改版控中的 default.yaml：每次生成一份指向新快照的暫時 run config
      （放 logs/weekly/<stamp>.config.yaml），避免每週 git 變動；
      run 的 manifest 仍記錄 snapshot_id / config_hash / git_commit（INV-6 provenance）。

  排程：週六早上，Task Scheduler 開「錯過起始時間就儘快補跑」（StartWhenAvailable）。
  註冊指令見 scripts/register_weekly_task.ps1。
#>

# 原生指令的 stderr（節流訊息等）不應中止腳本；改為每步顯式檢查 $LASTEXITCODE。
$ErrorActionPreference = 'Continue'
$env:PYTHONUTF8        = '1'
$env:PYTHONIOENCODING  = 'utf-8'

$Repo = 'C:\Users\user\QuantSystem'
Set-Location $Repo

# uv 完整路徑（Task Scheduler 的 PATH 可能與互動 shell 不同）
$Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $Uv) { $Uv = 'C:\Users\user\AppData\Local\Programs\Python\Python312\Scripts\uv.exe' }

$Stamp  = Get-Date -Format 'yyyy-MM-dd_HHmm'
$LogDir = Join-Path $Repo 'logs\weekly'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "$Stamp.log"

# PS 5.1 的 Tee-Object 預設把檔案寫成 UTF-16，log 用一般工具讀會變亂碼。
# 改用這個 filter：以無 BOM UTF-8 逐行 append，同時把該行往下游傳（互動執行仍看得到）。
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
filter TeeUtf8([string]$Path) {
  $s = if ($null -eq $_) { '' } else { [string]$_ }
  [System.IO.File]::AppendAllText($Path, $s + "`r`n", $Utf8NoBom)
  $_
}

function Log([string]$m) {
  $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m
  $line | TeeUtf8 $Log
}

Log '=== QuantCore 每週追蹤開始 ==='
Log "uv：$Uv"

# ---- 步驟 1：建立新快照 -----------------------------------------------------
Log '步驟 1/2：建立新快照（連網抓 20 檔，四源交叉驗證）…'
& $Uv run python -m quantcore.data.snapshot create --config quantcore\config\default.yaml *>&1 |
  TeeUtf8 $Log
if ($LASTEXITCODE -ne 0) {
  Log "!! 快照建立失敗（exit $LASTEXITCODE）— 中止，不在舊資料上跑回測。"
  Log '   常見原因：資料源日報酬跨源差異超標（§4.5），或供應商暫時異常。下週會自動再試。'
  exit 1
}

# 取剛建的快照：目錄名以日期前綴，字母序最後 = 最新
$NewSnap = Get-ChildItem (Join-Path $Repo 'snapshots') -Directory |
  Sort-Object Name | Select-Object -Last 1
if (-not $NewSnap) { Log '!! 找不到任何快照，中止。'; exit 1 }
$SnapRel = 'snapshots/' + $NewSnap.Name
Log "新快照：$SnapRel"

# ---- 生成指向新快照的暫時 run config（不動版控中的 default.yaml）-----------
# 必須用 .NET File IO 明確以 UTF-8 讀寫：PS 5.1 的 Get-Content -Raw 會把 default.yaml
# 的 UTF-8 中文註解當 cp950 讀而毀損（產生非法字元讓 YAML parser 拒絕）；寫檔用無 BOM
# UTF-8（避免 BOM 混進 YAML）。
$RunCfg = Join-Path $LogDir "$Stamp.config.yaml"
$srcCfg = [System.IO.File]::ReadAllText((Join-Path $Repo 'quantcore\config\default.yaml'), [System.Text.Encoding]::UTF8)
$genCfg = $srcCfg -replace '(?m)^snapshot:\s*\S+', "snapshot: $SnapRel"
[System.IO.File]::WriteAllText($RunCfg, $genCfg, (New-Object System.Text.UTF8Encoding($false)))
Log "run config：$RunCfg"

# ---- 步驟 2：跑一次全策略回測 ----------------------------------------------
Log '步驟 2/2：跑回測（全策略，直接呼叫引擎 CLI）…'
& $Uv run python -m quantcore.experiments.runner --config $RunCfg --out-root runs --label weekly *>&1 |
  TeeUtf8 $Log
if ($LASTEXITCODE -ne 0) { Log "!! 回測失敗（exit $LASTEXITCODE）。詳見本 log。"; exit 1 }

Log '=== 完成。runs/ 下已有本週結果；dashboard 可開來看。 ==='
exit 0
