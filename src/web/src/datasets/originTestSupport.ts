// 字段编辑页面测试只替换 HTTP 边界，预览报告和作业使用独立已知样本，不访问真实导航层。
import type { components } from "../api/schema";
import type { FetchImplementation } from "../api/client";
import { completedJob, job } from "../jobs/testSupport";
import { datasetFetch } from "./testSupport";

export const originUrl = '/datasets?selected="按任务/libero_10"';
export const originPreview: components["schemas"]["NavigationPreviewResponse"] = {
  preview_job_id: "301",
  created_at: "2026-10-30T07:00:00Z",
  parameters: { dataset_id: "dataset-14", changes: [] },
  operation: "edit_dataset_fields",
  dataset_ids: ["dataset-14"],
  changes: [],
  queued_jobs: [],
  report: {
    file_count: 1,
    link_count: 0,
    directory_count: 0,
    field_counts: [],
    listed_changes: [
      {
        file: "按任务/libero_10/数据集信息.json",
        json_path: "data_origin",
        before: "未知",
        after: "开源下载",
      },
    ],
    listed_total: 1,
    checks: [{ name: "来源格式", scope: "full", detail: "只改按任务入口" }],
    notices: [],
  },
};
export const previewJob = {
  ...completedJob,
  job_id: "301",
  type_name: "nav_fields_preview",
  display_name: "预览字段编辑",
};
export const writingJob = {
  ...job,
  job_id: "302",
  type_name: "nav_write_apply",
  display_name: "写导航层",
  parameters: { preview_job_id: 301 },
};
export const writtenJob = {
  ...completedJob,
  ...writingJob,
  state: completedJob.state,
  summary: completedJob.summary,
  ended_at: completedJob.ended_at,
};

/** HTTP 路径到测试响应的映射；不替换组件、hook 或内部协作者。 */
export type OriginHandlers = Partial<
  Record<string, (request: Request) => Response | Promise<Response>>
>;

/**
 * 装配真实路由测试的来源操作响应。
 * @param requests - 记录实际 HTTP 请求，测试读取载荷及取消信号。
 * @param handlers - 可选路径响应覆盖，用于恢复标记、冲突和延迟响应。
 * @returns 不联网的传输函数，未覆盖路径沿用数据集夹具。
 * @throws 无。
 * @sideEffects 向 requests 追加请求，不修改应用内部状态。
 * @timeSemantics 默认即时返回，延迟由各测试显式控制。
 */
export function originFetch(
  requests: Request[] = [],
  handlers: OriginHandlers = {},
): FetchImplementation {
  const fallback = datasetFetch(requests);
  return async (request) => {
    const path = new URL(request.url).pathname;
    const custom = handlers[path];
    if (custom) {
      requests.push(request);
      return custom(request);
    }
    const responses: Record<string, unknown> = {
      "/api/navigation/recovery-block": { blocked: false },
      "/api/navigation/fields/preview": { ...previewJob, state: "queued", summary: null },
      "/api/jobs/301": previewJob,
      "/api/navigation/previews/301": originPreview,
    };
    if (path in responses) {
      requests.push(request);
      return Response.json(responses[path]);
    }
    if (path === "/api/jobs" && request.method === "POST") {
      requests.push(request);
      return Response.json(writingJob, { status: 201 });
    }
    if (path === "/api/jobs/302") {
      requests.push(request);
      return Response.json(writingJob);
    }
    return fallback(request);
  };
}
