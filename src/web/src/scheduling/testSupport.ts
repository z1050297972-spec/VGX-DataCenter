// 独立的调度样本；编号与预期时刻由测试给定，不用生产映射函数生成。
import type { Scheduling } from "../api/scheduling";

export const scheduling: Scheduling = {
  types: [
    {
      type_name: "example_gpu",
      display_name: "示例：占用 GPU",
      concurrency: 2,
      requires_gpu: true,
      running_count: 1,
    },
    {
      type_name: "example_count",
      display_name: "示例：数数",
      concurrency: 1,
      requires_gpu: false,
      running_count: 0,
    },
  ],
  gpus: [
    {
      gpu_index: 0,
      job_id: "9007199254740993",
      availability: "available",
      diagnostics: [],
      checked_at: "2026-10-26T12:00:00Z",
    },
    {
      gpu_index: 1,
      job_id: null,
      availability: "available",
      diagnostics: [],
      checked_at: "2026-10-26T12:00:00Z",
    },
  ],
  navigation_job_id: "73",
  schedules: [
    {
      name: "清除过期报错",
      next_run_at: "2026-10-27T03:00:00Z",
      last_job_id: "70",
      last_submitted_at: "2026-10-26T03:00:00Z",
      last_state: "completed",
      last_outcome: "succeeded",
    },
    {
      name: "清除过期日志",
      next_run_at: "2026-10-27T03:00:00Z",
      last_job_id: null,
      last_submitted_at: null,
      last_state: null,
      last_outcome: null,
    },
  ],
  checked_at: "2026-10-26T12:00:00Z",
  worker_online: true,
};
