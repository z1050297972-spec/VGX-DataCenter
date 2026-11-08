// 入库只提交 worker 作业并读取已保存摘要；编号始终按文本传输。
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";
import type { HealthClient } from "./client";
import type { components } from "./schema";

/** 可修改的入库选项；源转换编号通过路由传递。 */
export type IngestOptions = components["schemas"]["IngestOptions"];
/** worker 保存的入库预览摘要。 */
export type IngestPreview = components["schemas"]["ConversionIngestPreviewView"];

/**
 * 为已转换数据集提交只读入库预览。
 * @param client - 认证客户端。
 * @param jobId - 成功转换编号，规范十进制文本。
 * @param input - 名字、同根相对位置和勾选格式。
 * @param signal - 组件卸载时取消。
 * @returns 新排队的预览作业。
 * @throws Error 请求失败或响应缺失。
 * @sideEffects 一次同源 POST，不访问数据目录。
 * @timeSemantics 请求最多 10 秒，不重试；检查在 worker 执行。
 */
export function submitIngestPreview(
  client: HealthClient,
  jobId: string,
  input: IngestOptions,
  signal: AbortSignal,
): Promise<Job> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const response = await client.POST("/api/jobs/{job_id}/conversion-ingest-preview", {
      params: { path: { job_id: jobId } },
      body: input,
      signal: bounded,
    });
    if (!response.data) throw new Error("缺少入库预览作业响应");
    return response.data;
  });
}

/**
 * 读取已成功生成的入库预览。
 * @param client - 认证客户端。
 * @param jobId - 预览编号文本。
 * @param signal - 组件查询取消信号。
 * @returns 保存的名字、位置、14 项和检查说明。
 * @throws Error 请求失败或摘要缺失。
 * @sideEffects 一次只读请求，不访问存储根。
 * @timeSemantics 请求最多 10 秒；快照过期时重新预览。
 */
export function getIngestPreview(
  client: HealthClient,
  jobId: string,
  signal: AbortSignal,
): Promise<IngestPreview> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const response = await client.GET("/api/jobs/{job_id}/conversion-ingest-preview", {
      params: { path: { job_id: jobId } },
      signal: bounded,
    });
    if (!response.data) throw new Error("缺少入库预览摘要");
    return response.data;
  });
}

/**
 * 确认同一份预览并提交入库写作业。
 * @param client - 认证客户端。
 * @param jobId - 已成功预览的编号文本。
 * @param signal - 表单取消信号。
 * @returns 新排队的入库作业。
 * @throws Error 预览不可用或请求失败。
 * @sideEffects 一次同源 POST；目录移动和导航写入由 worker 完成。
 * @timeSemantics 请求最多 10 秒，不自动重试。
 */
export function confirmIngest(
  client: HealthClient,
  jobId: string,
  signal: AbortSignal,
): Promise<Job> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const response = await client.POST("/api/jobs/conversion-ingest", {
      body: { preview_job_id: jobId },
      signal: bounded,
    });
    if (!response.data) throw new Error("缺少入库作业响应");
    return response.data;
  });
}

/** 转换暂存页，字段完全来自生成的OpenAPI契约。 */
export type ConversionStaging = components["schemas"]["StagingPage"];

/**
 * 读取转换暂存的当前状态页。
 * @param client - 已认证客户端。
 * @param before - 上一页返回的编号游标文本；首次省略。
 * @param signal - 页面查询取消信号。
 * @returns 至多50项及下一页游标。
 * @throws Error 查询失败或响应缺失。
 * @sideEffects 只读请求；服务端不扫描存储根。
 * @timeSemantics 请求最多10秒，报告与大小为worker快照。
 */
export function getConversionStaging(
  client: HealthClient,
  before: string | undefined,
  signal: AbortSignal,
): Promise<ConversionStaging> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const response = await client.GET("/api/conversions/staging", {
      params: { query: { before } },
      signal: bounded,
    });
    if (!response.data) throw new Error("缺少转换暂存响应");
    return response.data;
  });
}

/**
 * 提交转换暂存删除作业。
 * @param client - 管理员客户端。
 * @param jobId - 转换编号文本。
 * @param signal - 卸载取消信号。
 * @returns 排队的删除作业。
 * @throws Error 请求失败或响应缺失。
 * @sideEffects 一次POST；worker重查未入库且未占用后删除。
 * @timeSemantics 最多10秒，不自动重试删除提交。
 */
export function deleteConversionStaging(
  client: HealthClient,
  jobId: string,
  signal: AbortSignal,
): Promise<Job> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const response = await client.POST("/api/conversions/{job_id}/delete", {
      params: { path: { job_id: jobId } },
      signal: bounded,
    });
    if (!response.data) throw new Error("缺少转换删除作业响应");
    return response.data;
  });
}
