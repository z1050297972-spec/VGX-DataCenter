// M1-09 独立 HTTP 样本；真实路由、Query 和组件运行，不替换应用模块。
import type { NavigationPreview } from "../api/dataOrigin";
import type { FetchImplementation } from "../api/client";
import { completedJob, job } from "../jobs/testSupport";
import { datasetFetch, detail } from "./testSupport";

export const oldPrefix = "/fake/dataset1/libero_10";
export const newPrefix = "/fake/dataset2/libero_10";
export const writeJob = {
  ...completedJob,
  job_id: "401",
  type_name: "nav_write_apply",
  display_name: "写导航层",
  parameters: { preview_job_id: 301 },
};
export const repointPreview: NavigationPreview = {
  preview_job_id: "301",
  created_at: "2026-10-30T07:00:00Z",
  operation: "repoint_dataset",
  dataset_ids: ["dataset-14"],
  parameters: { dataset_id: "dataset-14", old_prefix: oldPrefix, new_prefix: newPrefix },
  changes: [],
  queued_jobs: [],
  report: {
    file_count: 6,
    link_count: 2,
    directory_count: 0,
    field_counts: [{ file: "按任务/libero_10/子任务.json", field: "tasks[].notes[]", count: 2 }],
    listed_changes: [],
    listed_total: 1,
    repoint_changes: [
      {
        file: "按任务/libero_10/子任务.json",
        json_path: "tasks[0].notes[0]",
        before: oldPrefix,
        after: newPrefix,
      },
    ],
    checks: [{ name: "路径核对", scope: "full", detail: "worker 全量核对" }],
    notices: [
      {
        code: "old_path_missing",
        message: "旧位置原本就不存在",
        objects: [
          ["old_path", oldPrefix + "/missing"],
          ["new_path", newPrefix + "/missing"],
        ],
      },
    ],
  },
};
export const reversePreview: NavigationPreview = {
  ...repointPreview,
  preview_job_id: "302",
  operation: "revert_change",
  parameters: { target_job_id: 401 },
  reverts_job_id: "401",
  reversal: {
    field_counts: repointPreview.report.field_counts,
    listed_total: 1,
    listed_changes: [
      {
        file: "按任务/libero_10/子任务.json",
        json_path: "tasks[0].notes[0]",
        before: newPrefix,
        after: oldPrefix,
      },
    ],
  },
};

/**
 * 构造只替换 HTTP 边界的页面传输。
 * @param requests - 保留实际请求，断言 POST 载荷和调用时机。
 * @param override - 可选特定请求响应，测试恢复阻挡和冲突。
 * @returns 不联网的传输函数，其他请求沿用现有页面样本。
 * @throws 无。
 * @sideEffects 仅记录 HTTP 请求。
 * @timeSemantics 即时完成，无后台任务。
 */
export function repointFetch(
  requests: Request[],
  override?: (request: Request) => Response | undefined,
): FetchImplementation {
  const fallback = datasetFetch();
  return async (request) => {
    requests.push(request);
    return override?.(request) ?? repointRoute(new URL(request.url).pathname) ?? fallback(request);
  };
}
const created = (type: string, id: string) =>
  Response.json({ ...job, job_id: id, type_name: type }, { status: 201 });
const jobResponse = (id: string) => Response.json({ ...completedJob, job_id: id });
const linkDetail = () =>
  Response.json({
    ...detail,
    links: [
      {
        name: "原始数据",
        source_path: oldPrefix,
        source_type: "directory",
        derived_entry_path: "按任务/libero_10/原始数据",
        observed_target: oldPrefix,
        ordinal: 0,
        status: "available",
        storage_root_name: "dataset1",
        checked_at: null,
        size_bytes: null,
        size_checked_at: null,
      },
    ],
  });
const routes: Record<string, () => Response> = {
  "/api/navigation/recovery-block": () => Response.json({ blocked: false }),
  "/api/datasets/detail": linkDetail,
  "/api/datasets/repoint-previews": () => created("nav_repoint_preview", "301"),
  "/api/jobs/401/revert-previews": () => created("nav_revert_preview", "302"),
  "/api/jobs/301": () => jobResponse("301"),
  "/api/jobs/302": () => jobResponse("302"),
  "/api/jobs/401": () => Response.json(writeJob),
  "/api/navigation/previews/301": () => Response.json(repointPreview),
  "/api/navigation/previews/302": () => Response.json(reversePreview),
  "/api/navigation/writes": () =>
    Response.json({ ...writeJob, job_id: "402", state: "queued", summary: null }, { status: 201 }),
};
// 命中返回样本响应；未命中返回 undefined，交给通用数据集样本。
function repointRoute(path: string): Response | undefined {
  return routes[path]?.();
}
