// 作业页面的独立已知记录，数字编号始终是文本，不借生产映射函数制造预期。
import type { Job, WorkerStatus } from "../api/jobs";

export const job: Job = {
  job_id: "9007199254740993",
  type_name: "example_count",
  display_name: "示例：数数",
  parameters: { steps: 4, interval_ms: 0 },
  submitted_by: { account_id: "2", name: "成员", deleted: false },
  submitted_at: "2026-10-26T12:00:00Z",
  resubmitted_from: null,
  state: "running",
  started_at: "2026-10-26T12:00:00Z",
  ended_at: null,
  progress: {
    stage_index: 2,
    stage_count: 4,
    stage_name: "处理",
    done: 2,
    total: 4,
    unit: "条",
    total_items: 2,
    failed_items: 0,
    warning_count: 0,
    parts: [],
  },
  progress_at: "2026-10-26T12:00:02Z",
  elapsed_s: 2,
  log_path: "logs/示例：数数/2026-10-26_120000_000.log",
  summary: null,
  diagnostics: [],
  recovery_mode: "interrupt",
  recovery_count: 0,
  gpu_index: null,
  wait_reason: null,
  holds_navigation_lock: false,
};
export const onlineWorker: WorkerStatus = {
  online: true,
  instance_id: "00000000000040008000000000000001",
  pid: 123,
  started_at: "2026-10-26T12:00:00Z",
  last_seen_at: "2026-10-26T12:00:02Z",
  checked_at: "2026-10-26T12:00:03Z",
};

/** 独立的已完成样本，摘要和最后进度逐项一致。 */
export const completedJob: Job = {
  ...job,
  state: "completed",
  ended_at: "2026-10-26T12:00:04Z",
  elapsed_s: 4,
  summary: {
    state: "completed",
    outcome: "succeeded",
    progress: job.progress,
    total_items: 2,
    failed_items: 0,
    warning_count: 0,
    aborted: false,
    elapsed_s: 4,
    artifacts: [],
    tool_exit_code: null,
  },
};
