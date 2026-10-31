// 创建流程的独立 HTTP 样本，不读取真实导航层，不替换应用内部模块。
import type {
  CreationOptions,
  CreationPreview,
  LinkPreviewInput,
  DatasetPreviewInput,
} from "../api/datasetCreation";
import type { FetchImplementation } from "../api/client";
import type { ProblemResponse } from "../api/problems";
import { completedJob, job } from "../jobs/testSupport";
import { datasetFetch } from "./testSupport";

export const creationOptions: CreationOptions = {
  formats: [
    { format: "lerobot", directory: "lerobot", has_versions: true, versions: ["3.0"] },
    { format: "mcap", directory: "mcap", has_versions: false, versions: [] },
    { format: "archives", directory: "tar、tar.gz（含分卷）", has_versions: false, versions: [] },
  ],
  data_origins: ["真机采集", "UMI 采集", "ego 采集", "仿真生成", "开源下载", "未知"],
};
export const linkInput: LinkPreviewInput = {
  dataset_id: "dataset-14",
  link: { name: "新链接", target_path: "/fake/disk/new", fallback_format: "mcap" },
  format_entries: [],
};
export const creationPreview: CreationPreview = {
  preview_job_id: "101",
  created_at: "2026-10-30T07:00:00Z",
  operation: "create_link",
  dataset_id: "dataset-14",
  dataset_name: "libero_10",
  parameters: linkInput,
  queued_jobs: [],
  format_entry_options: [
    { format: "mcap", version: null },
    { format: "archives", version: null },
    { format: "lerobot", version: "3.0" },
  ],
  report: {
    file_count: 2,
    link_count: 1,
    directory_count: 1,
    field_counts: [],
    listed_changes: [],
    listed_total: 0,
    checks: [{ name: "路径检查", scope: "full", detail: "检查本条目标" }],
    notices: [],
    creation: {
      canonical_entry_path: "按任务/libero_10",
      format_entry_paths: ["按格式/mcap/libero_10"],
      selected_format_entry_paths: [],
      file_paths: ["按任务/libero_10/原始路径.json", "按格式/mcap/libero_10/原始路径.json"],
      directory_paths: ["按格式/mcap/libero_10"],
      links: [{ path: "按任务/libero_10/新链接", target_path: "/fake/disk/new" }],
      sources_added: [
        {
          source_id: "src_0123456789ab",
          original_path: "/fake/disk/new",
          direct_path: "/fake/disk/new",
          format: "mcap",
          version: null,
          validation_status: "path_exists_only",
        },
      ],
      dataset_roots_added: ["/fake/disk/new"],
      resolved_format: "mcap",
      resolved_version: null,
      metadata_source: "selected_format",
      noop: false,
    },
  },
};
export const previewJob = {
  ...job,
  job_id: "101",
  type_name: "nav_create_link_preview",
  display_name: "预览建链",
  state: "queued" as const,
};
export const creationWrite = {
  ...job,
  job_id: "102",
  type_name: "nav_write_apply",
  display_name: "写导航层",
  state: "queued" as const,
  parameters: { preview_job_id: 101 },
};

/**
 * 返回带稳定作业编号对象的队列冲突。
 * @param ids - 未确认的规范编号文本。
 * @returns 409 problem 响应，诊断对象供前端按键读取。
 * @throws 无。
 * @sideEffects 仅构造响应。
 * @timeSemantics 无时钟读取。
 */
export function queueConflict(ids: string[]): Response {
  const problem: ProblemResponse = {
    type: "about:blank",
    title: "Conflict",
    status: 409,
    category: "conflict",
    detail: "已有排队写作业",
    error_id: "00000000000040008000000000000000",
    diagnostics: [
      {
        level: "error",
        category: "conflict",
        stage: "写导航层",
        source: "平台",
        rule: "NAV_CREATE_QUEUE_CONFIRMATION",
        objects: ids.map((id, index) => ({ key: `queued_job_id_${String(index + 1)}`, value: id })),
        actual: "存在新排队作业",
        expected: "确认所列编号",
        consequence: "本次未提交",
        next_step: "勾选确认后重新提交",
        error_chain: [],
      },
    ],
  };
  return Response.json(problem, {
    status: 409,
    headers: { "content-type": "application/problem+json" },
  });
}

/**
 * 创建注入真实 Router 的传输，逐次记录请求并保存最后预览参数。
 * @param requests - 接收实际 Request 的数组。
 * @param overrides - 按路径覆盖外部 HTTP 响应，函数由本函数直接调用。
 * @returns 不联网的客户端传输。
 * @throws Error 覆盖响应抛出的故障原样交客户端。
 * @sideEffects 只记录请求及测试内存参数。
 * @timeSemantics 即时响应，生产 Query 负责轮询。
 */
export function creationFetch(
  requests: Request[] = [],
  overrides: Record<string, (request: Request) => Response | Promise<Response>> = {},
): FetchImplementation {
  const fallback = datasetFetch(requests);
  let current = creationPreview;
  let nextPreviewId = 101;
  return (request) => {
    const path = new URL(request.url).pathname;
    const override = overrides[path];
    if (override) {
      requests.push(request);
      return Promise.resolve(override(request));
    }
    if (path === "/api/navigation/recovery-block") {
      requests.push(request);
      return Promise.resolve(Response.json({ blocked: false }));
    }
    if (path === "/api/datasets/creation-options") {
      requests.push(request);
      return Promise.resolve(Response.json(creationOptions));
    }
    if (path === "/api/datasets/link-previews" || path === "/api/datasets/creation-previews") {
      requests.push(request);
      return request
        .clone()
        .json()
        .then((body: LinkPreviewInput | DatasetPreviewInput) => {
          current = {
            ...creationPreview,
            preview_job_id: String(nextPreviewId),
            parameters: body,
            operation: "dataset_name" in body ? "create_dataset" : "create_link",
            dataset_name: "dataset_name" in body ? body.dataset_name : "libero_10",
            dataset_id: "dataset_name" in body ? "dataset-36" : "dataset-14",
          };
          nextPreviewId += 2;
          return Response.json({ ...previewJob, job_id: current.preview_job_id }, { status: 201 });
        });
    }
    if (path === `/api/datasets/creation-previews/${current.preview_job_id}`) {
      requests.push(request);
      return Promise.resolve(Response.json(current));
    }
    if (path === "/api/datasets/creation-writes") {
      requests.push(request);
      return Promise.resolve(Response.json(creationWrite, { status: 201 }));
    }
    if (path === `/api/jobs/${current.preview_job_id}`) {
      requests.push(request);
      return Promise.resolve(
        Response.json({
          ...completedJob,
          ...previewJob,
          job_id: current.preview_job_id,
          state: "completed",
          summary: completedJob.summary,
        }),
      );
    }
    if (path === "/api/jobs/102") {
      requests.push(request);
      return Promise.resolve(
        Response.json({
          ...completedJob,
          ...creationWrite,
          state: "completed",
          summary: completedJob.summary,
        }),
      );
    }
    return fallback(request);
  };
}
