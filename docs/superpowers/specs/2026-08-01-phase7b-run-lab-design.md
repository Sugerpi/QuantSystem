# Phase 7b — Run Lab（回測工作台）設計文件

> 規格來源：`DEVELOPMENT_GUIDE v1.2.md` §9（Phase 7 AC②③）/ §11.3（Run Lab）/ §2.2（依賴方向）。
> brainstorming 定案，作為 writing-plans 的輸入。日期：2026-08-01。
> 前置：Phase 7 唯讀 Web dashboard 重製完成（計畫 1/2a/2b/2c）；頁 8「回測工作台」目前為 stub。
> 引擎已具 CLI：`python -m quantcore.experiments.runner --config <path> --out-root runs --label <label> --strategies <csv>`。

## 0. 範圍與 AC

Run Lab 讓使用者**全程在網頁**提交新回測、看進度、拿到結果，不碰終端機。

- **AC②**：從 Run Lab 提交一份新 config 並完整跑完回測，全程不碰終端機。
- **AC③**：UI 行程強制終止再重啟後，**運行中** job 的狀態與進度無損。

### 不做（YAGNI / 延後）

- 不做引導式參數表單：**config 以 YAML 編輯器提交**（使用者定案）。
- 不做多 job 並行：**一次一個 + 排隊**（使用者定案）。
- 不做 job 取消/刪除 UI（可後續加；本段只到提交/監看/完成）。
- 不做 7c 研究報告（獨立）。

### 硬邊界（§2.2 / CLAUDE.md）

- `presentation/`（含 `jobs.py`）**永不 import 引擎**；啟動回測**只以 subprocess 呼叫引擎 CLI**。由既有 AST 架構守護測試（`rglob` 掃全 `presentation/` 樹）強制——`jobs.py` 落在此樹下，自動涵蓋。
- 禁用 pickle；序列化一律 JSON/YAML/parquet。
- 引擎端新增只在 `experiments/` CLI 層（`runner.py` + 新 `jobstatus.py`），不違反依賴方向。

---

## 1. 架構總覽

三個單元，各一職責：

| 單元 | 位置 | 職責 | 依賴 |
|------|------|------|------|
| **job store + 排程器** | `quantcore/presentation/jobs.py` | 建 job、寫初始 `queued`、spawn detached 子行程、reconcile 狀態、排隊推進 | subprocess、psutil、json/yaml、stdlib。**不 import 引擎** |
| **Run Lab 頁面** | `quantcore/presentation/web/routes/run_lab.py` + 模板 | YAML 編輯器、提交、job 清單、狀態輪詢、log 尾巴、驗證 | `jobs`、`rendering`、`readers` |
| **引擎狀態寫入** | `quantcore/experiments/runner.py`（改）+ `quantcore/experiments/jobstatus.py`（新） | 子行程在階段/策略邊界原子寫 `status.json` | 引擎內部 |

### 狀態所有權（設計核心）

`status.json` **由引擎子行程權威擁有**。UI 只在「提交」時寫一次初始 `queued`，之後**只讀**。單一寫者 + 原子寫（temp + `os.replace`），避免 UI 讀到半寫檔或雙寫競爭。

---

## 2. Job 目錄與 status.json 合約

### 目錄

`jobs/<job_id>/`（`jobs` 根：env `QUANTCORE_JOBS_ROOT` → 預設 `jobs`；與 `runs/` 同層、gitignore）：

- `config.yaml` —— 使用者提交的 YAML（原文）。
- `status.json` —— 狀態（見下）。
- `stdout.log` —— 子行程 stdout+stderr（重導向，供 log 尾巴與失敗診斷）。

`job_id`：`YYYYMMDD_HHMMSS_<label>`（提交時刻 + label；排序即時序）。回測**產物照常落 `runs/`**（引擎 `--out-root runs`），`run_dir` 記於 `status.json`。

### status.json 欄位

```json
{
  "job_id": "20260801_142530_myrun",
  "label": "myrun",
  "state": "queued | running | done | failed",
  "stage": "validating | loading_snapshot | running | writing_artifacts | done | error",
  "strategy_index": 3,
  "strategy_total": 8,
  "current_strategy": "full",
  "pid": 12345,
  "submitted_at": "2026-08-01T14:25:30",
  "started_at": "2026-08-01T14:25:33",
  "heartbeat_at": "2026-08-01T14:27:10",
  "finished_at": null,
  "run_dir": null,
  "error": null
}
```

- **UI 寫**（提交時，一次）：`job_id`/`label`/`state=queued`/`submitted_at`。
- **引擎子行程寫**（spawn 後接管，覆蓋）：`state` running/done/failed、`stage`、`strategy_index/total`、`current_strategy`、`pid`、`started_at`、`heartbeat_at`、`finished_at`、`run_dir`（done 時）、`error`（failed 時）。
- **UI reconcile 寫**（唯一例外）：state=running 但 pid 已死且無終端狀態 → 覆寫 `state=failed`、`error="行程消失（可能硬當機）"`。

原子寫：寫 `status.json.tmp` 再 `os.replace` 為 `status.json`（POSIX/Windows 皆原子）。

---

## 3. 引擎端改動（`experiments/`）

### 3.1 `experiments/jobstatus.py`（新，~30 行）

```python
def write_status(status_file: Path, **fields) -> None
    """讀現有 status.json（若有）、merge fields、加 heartbeat_at、原子寫回。"""
```

純檔案操作、無引擎依賴。可獨立單元測試。

### 3.2 `run_experiment` 加 `on_progress` callback（`runner.py`）

`run_experiment(..., on_progress: Callable[[str, int, int, str | None], None] | None = None)`：
- 在策略迴圈每支策略**開始前**呼叫 `on_progress("running", i, n, sid)`。
- 其餘階段（loading_snapshot / writing_artifacts）在 CLI 端標記即可（見 3.3）。
- 預設 `None` → 行為完全不變（ablation / tests / conftest 既有呼叫不受影響，向後相容）。

### 3.3 `runner._cli` 加 `--status-file` / `--job-id`

當提供 `--status-file`：
1. 進 try：`write_status(sf, state="running", stage="validating", pid=os.getpid(), started_at=now)`。
2. `load_config`（驗證）→ `write_status(stage="loading_snapshot")` → `load_snapshot`。
3. `run_experiment(..., on_progress=lambda state,i,n,sid: write_status(sf, stage="running", strategy_index=i, strategy_total=n, current_strategy=sid))`。
4. `write_status(stage="writing_artifacts")`（run_experiment 內部落盤前後；簡化：run_experiment 回傳後即視為完成）。
5. `write_status(state="done", stage="done", finished_at=now, run_dir=str(run_dir))`。
6. `except Exception as e`：`write_status(state="failed", stage="error", finished_at=now, error=<型別+訊息，截斷>)`；`sys.exit(1)`。

未提供 `--status-file` → 現行行為（print「run 已完成」）不變。

### 3.4 `--validate-only`（可選，加分）

`--validate-only`：只 `load_config`（pydantic 驗證），成功 print `OK`、exit 0；失敗 print 錯誤、exit 1。不跑回測、不需 snapshot。供 UI「驗證」按鈕同步快檢。

---

## 4. `presentation/jobs.py`（job store + 排程器）

**不 import 引擎。** 介面（純函數 + 一個 spawner，便於測試）：

- `submit(jobs_root, label, config_yaml) -> job_id`：建 `jobs/<job_id>/`，寫 `config.yaml`、初始 `status.json`（queued）。回 job_id。
- `list_jobs(jobs_root) -> list[dict]`：讀所有 `status.json`，依 `submitted_at` 排序。
- `load_status(jobs_root, job_id) -> dict`；`tail_log(jobs_root, job_id, n=200) -> str`。
- `validate(config_yaml) -> (ok: bool, message: str)`：同步 subprocess `python -m quantcore.experiments.runner --validate-only --config <tmp>`，回結果。
- `reconcile_and_advance(jobs_root) -> None`（排程器核心）：
  1. **reconcile**：對每個 state=running 的 job，用 `psutil.pid_exists(pid)` 檢查；pid 死且 state 仍 running → 覆寫 failed(crashed)。
  2. **advance**：若無 job 正在跑（無 running-且-pid-活），取 `submitted_at` 最早的 queued job → `_spawn(job)`。
- `_spawn(jobs_root, job) -> None`：組指令 `[sys.executable, "-m", "quantcore.experiments.runner", "--config", <job/config.yaml>, "--out-root", "runs", "--label", <label>, "--status-file", <job/status.json>, "--job-id", <job_id>]`，以 **detached** 方式 `subprocess.Popen`（Windows：`creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`；POSIX：`start_new_session=True`），stdout/stderr 重導 `stdout.log`。**不保留 Popen handle 依賴**（狀態靠 status.json，非 wait）。

排程器決策（reconcile_and_advance 的「下一步」）以純函數 `_next_action(statuses) -> ("spawn", job_id) | ("mark_failed", job_id) | None` 抽出，注入假 statuses 可獨立測、不需真 subprocess。

**背景心跳執行緒**：FastAPI startup 起一條 daemon thread，每 ~3s 呼叫 `reconcile_and_advance`（含鎖，序列化對 jobs store 的存取）。行程死則 thread 死（AC③ 只要求運行中 job 存活，排隊在 UI 死時暫停、重開即續）。Run Lab 輪詢端點亦順手 tick 一次（雙保險）。

---

## 5. Run Lab 頁面（`routes/run_lab.py` + 模板）

- `GET /run-lab`：整頁——① base config 下拉（掃 `config/*.yaml`）+「載入」把 YAML 灌進 `<textarea>`；② YAML 編輯器 + label 欄 +「驗證」「提交」鈕；③ job 清單（狀態徽章 / 進度 策略 i/N / 提交時間 / done 時「看 run」連結）。
- `POST /run-lab/validate`：收 YAML → `jobs.validate` → 回 OK/錯誤片段（HTMX 換一小塊）。
- `POST /run-lab/submit`：收 YAML + label → `jobs.submit` → 觸發 `reconcile_and_advance` → 回 job 清單片段。**需 `python-multipart`**（FastAPI 解析表單）→ 加依賴。
- `GET /run-lab/status`：HTMX 每 ~2s 輪詢 → 回 job 清單片段（狀態/進度/log 尾巴）。順手 tick 排程器。
- 提交/驗證是「送出使用者輸入的表單」→ 屬正常本機操作（localhost 單人、無外送），符合互動規範。

深色 Bloomberg 風沿用既有 CSS；狀態徽章用語意色（queued 灰 / running 琥珀 / done 綠 / failed 紅）。

---

## 6. 資料流（端到端）

```
選 base config → 載入 YAML → 編輯 → （驗證：subprocess --validate-only 快檢）
  → 提交 → jobs.submit 寫 queued
  → 排程器（背景 thread / 輪詢 tick）見無 job 在跑 → _spawn detached
  → 引擎子行程：write running(pid) → validating → loading_snapshot
     → run_experiment（每策略 on_progress 寫 i/N）→ writing_artifacts
     → 落盤 runs/<run_dir> → write done(run_dir)
  → 頁面輪詢 status.json 畫進度＋log 尾巴 → done 後「看 run」連結跳唯讀 dashboard
```

---

## 7. 錯誤處理

- **config 不合法**：子行程 `load_config` 拋 → 引擎寫 `failed` + pydantic 錯誤（截斷）→ 頁面紅字。或提交前按「驗證」先擋。
- **子行程非零退出 / 未寫終端狀態**：reconcile 用 pid-liveness 偵測（pid 死 + 仍 running）→ 標 failed(crashed)，附 `stdout.log` 尾巴。
- **snapshot 缺**：`load_snapshot` 拋 → failed + 訊息（提示該 config 指的快照不在本機）。
- **jobs 讀取**：壞/半寫 status.json → 原子寫已避免；防禦性 `try/except` 讀取回「狀態不明」而非崩潰。

---

## 8. 測試策略

- **`jobstatus.write_status`**（引擎）：merge + 原子寫 + heartbeat；讀回一致。
- **`run_experiment` on_progress**：合成迷你 config 跑，callback 記錄到每支策略的 `(i, n, sid)` 序列。
- **`jobs._next_action`**（純函數）：給假 status 集合——無 running + 有 queued → spawn 最早；有 running-活 pid → None；running-死 pid → mark_failed。注入假 `pid_exists`。
- **`jobs.submit` / `list_jobs`**：tmp jobs_root，提交後目錄/檔案/排序正確。
- **架構守護**：`jobs.py` + `run_lab.py` 不 import 引擎（既有 AST 測試自動涵蓋）。
- **端到端整合（AC②）**：TestClient 對極小合成 config（比照 conftest fixture 規模）走 submit → 背景/手動 tick → 輪詢 status 直到 done（真 subprocess、CI 可跑，因合成快照小）。
- **AC③ 復原**：模擬——寫一個 state=running + 假死 pid 的 status.json → `reconcile_and_advance` → 應標 failed(crashed)；再放一個 queued → 應被 spawn。以此涵蓋「UI 重啟後 reconcile」路徑而不需真的殺行程。
- INV-1~6 不受影響（未動引擎核心邏輯，只加狀態寫入旁路）；全套 pytest + ruff 綠。

---

## 9. 依賴新增

- `psutil>=5.9`（跨平台 pid 存活檢查，reconcile 用）。
- `python-multipart>=0.0.9`（FastAPI 解析提交表單）。

---

## 10. 交付切段（供 writing-plans）

建議兩段（各自 spec→plan→實作→review）：

- **計畫 1 — 引擎端狀態管線**：`jobstatus.write_status`、`run_experiment` 加 `on_progress`、`runner._cli` 加 `--status-file`/`--job-id`/`--validate-only`。TDD + 合成 config 驗證 status.json 逐階段正確。**不動既有 CLI 預設行為**。
- **計畫 2 — presentation Run Lab**：`jobs.py`（store + 排程器 + detached spawn + reconcile）、`run_lab.py` + 模板（YAML 編輯器/提交/驗證/job 清單/輪詢/log）、背景心跳執行緒、`psutil`/`python-multipart` 依賴、頁 8 stub 換真頁、AST 守護涵蓋、端到端 AC②③ 測試。

AC 對映：**AC②** 於計畫 2 端到端達成；**AC③** 由 detached 子行程 + status.json + pid-liveness reconcile 達成（計畫 2 測試涵蓋）。

## 11. 待決 / 已決

- **已決**：YAML 編輯器（非表單）；一次一個 + 排隊；狀態由引擎子行程權威擁有；粗粒度階段 + 心跳；psutil pid-liveness；背景心跳執行緒推排隊；新增 psutil + python-multipart。
- **無其他待決項。**
