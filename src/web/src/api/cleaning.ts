// 清洗预览 HTTP 边界：类型与路径均取 OpenAPI，复用账号客户端和作业超时。
import type { AccountCall } from "./accounts";
import type { components, operations } from "./schema";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";
import { toFailureView } from "./problems";

/** 预览参数、响应及报告嵌套结构均引用生成类型，不另写字段。 */
export type CleaningPreviewInput = components["schemas"]["CleaningPreviewParameters"];
export type CleaningPreview = components["schemas"]["CleaningPreviewResponse"];
export type CleaningReport = components["schemas"]["CleaningReport"];
export type EpisodeIssue = components["schemas"]["EpisodeIssue"];
export type EpisodeReport = components["schemas"]["EpisodeReport"];
export type FileReport = components["schemas"]["FileReport"];
export type TopicAlignment = components["schemas"]["TopicAlignment"];
export type CleaningSourceRules = components["schemas"]["CleaningSourceRules"];

/** 将生成的路径参数与请求体组合为页面提交载荷，不是另一份 HTTP 请求结构。 */
export interface CleaningPreviewSubmission {
  /** 已登记工具名称，不接受程序路径。 */
  tool: operations["submit_cleaning_preview_job"]["parameters"]["path"]["tool_name"];
  /** 数据集、MCAP 数据块和有清洗规则的型号。 */
  parameters: CleaningPreviewInput;
}

/**
 * 提交只读清洗预览作业。
 * @param input - 登记工具、数据集、1 至 200 个 MCAP 数据块、型号及取消信号。
 * @returns 服务端创建的作业，字段沿用已有 Job 类型。
 * @throws Error 权限、输入、网络或超时失败，交统一诊断显示。
 * @sideEffects POST /api/jobs/cleaning-preview/{tool_name}；不直接访问数据文件。
 * @timeSemantics 请求最多 JOB_REQUEST_TIMEOUT_MS 毫秒；不等待预览完成、不重试。
 */
export function submitCleaningPreview(input: AccountCall<CleaningPreviewSubmission>): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.POST("/api/jobs/cleaning-preview/{tool_name}", {
      params: { path: { tool_name: input.payload.tool } },
      body: input.payload.parameters,
      signal,
    });
    if (!response.data) throw new Error("请求失败", { cause: toFailureView(null) });
    return response.data;
  });
}

/**
 * 读取一次已持久化的清洗报告。
 * @param input - 账号客户端、正整数作业编号文本和取消信号。
 * @returns 完整报告与生成时的工具指纹，不混用工具当前配置。
 * @throws Error 404 表示没有报告；其余失败原样交统一诊断。
 * @sideEffects GET /api/cleaning-previews/{job_id}；不写选择状态。
 * @timeSemantics 请求最多 JOB_REQUEST_TIMEOUT_MS 毫秒，不轮询、不重试。
 */
export function getCleaningPreview(input: AccountCall<string>): Promise<CleaningPreview> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.GET("/api/cleaning-previews/{job_id}", {
      params: { path: { job_id: input.payload } },
      signal,
    });
    if (!response.data) throw new Error("请求失败", { cause: toFailureView(null) });
    // openapi-fetch 的 Readable 会把生成的 limits 二元组展开成 number[]；传输不改变 JSON。
    // 仅在响应边界恢复生成契约；依赖保留元组推导后可删除此断言，不放宽页面类型。
    return response.data as CleaningPreview;
  });
}
