// 下载接口只提交作业和读取 worker 快照；浏览器不访问存储根。
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";
import type { HealthClient } from "./client";
import type { components } from "./schema";

/** 下载表单持久化参数，字段范围由服务端模型最终校验。 */
export type DownloadInput = components["schemas"]["DownloadParameters"];
/** 已发布的只读预览摘要。 */
export type DownloadPreview = components["schemas"]["PreviewResult"];

/**
 * 提交下载或只读预览作业。
 * @param client - 账号感知客户端。
 * @param input - 不含凭据的下载参数。
 * @param preview - true 只预览，false 提交实际下载。
 * @param signal - 调用方取消信号。
 * @returns 新建的排队作业。
 * @throws Error 请求失败或缺少响应体。
 * @sideEffects 发一次同源写请求，不访问数据目录。
 * @timeSemantics 最多等待 10 秒，不重试，超时不证明未提交。
 */
export function submitDownload(
  client: HealthClient,
  input: DownloadInput,
  preview: boolean,
  signal: AbortSignal,
): Promise<Job> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const response = preview
      ? await client.POST("/api/jobs/download-preview", { body: input, signal: bounded })
      : await client.POST("/api/jobs/download", { body: input, signal: bounded });
    if (!response.data) throw new Error("缺少作业响应");
    return response.data;
  });
}

/**
 * 按已成功作业编号读取下载预览。
 * @param client - 账号感知客户端。
 * @param jobId - 规范十进制编号文本，不转为数字。
 * @param signal - 调用方取消信号。
 * @returns worker 生成的预览摘要。
 * @throws Error 请求失败或缺少响应体。
 * @sideEffects 一次只读请求。
 * @timeSemantics 最多等待 10 秒，不重试。
 */
export function getDownloadPreview(
  client: HealthClient,
  jobId: string,
  signal: AbortSignal,
): Promise<DownloadPreview> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const response = await client.GET("/api/jobs/{job_id}/download-preview", {
      params: { path: { job_id: jobId } },
      signal: bounded,
    });
    if (!response.data) throw new Error("缺少预览响应");
    return response.data;
  });
}

/** worker 发布的暂存扫描数据库快照。 */
export type DownloadStaging = components["schemas"]["StagingSnapshot"];

/**
 * 提交只读的暂存扫描作业。
 * @param client - 账号感知客户端。
 * @param signal - 调用方取消信号。
 * @returns 新排队的扫描作业。
 * @throws Error 请求失败或缺少响应体。
 * @sideEffects 发送一次同源写请求；浏览器不访问存储根。
 * @timeSemantics 最多等待 10 秒，不自动重试。
 */
export function submitStagingScan(client: HealthClient, signal: AbortSignal): Promise<Job> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const response = await client.POST("/api/jobs/download-staging-scan", {
      body: {},
      signal: bounded,
    });
    if (!response.data) throw new Error("缺少作业响应");
    return response.data;
  });
}

/**
 * 读取扫描作业发布的数据库快照。
 * @param client - 账号感知客户端。
 * @param jobId - 正整数作业编号文本。
 * @param signal - 调用方取消信号。
 * @returns 扫描时刻的暂存目录摘要。
 * @throws Error 请求失败或缺少响应体。
 * @sideEffects 一次只读数据库接口请求。
 * @timeSemantics 最多等待 10 秒，快照不保证与当前状态一致。
 */
export function getStagingSnapshot(
  client: HealthClient,
  jobId: string,
  signal: AbortSignal,
): Promise<DownloadStaging> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const response = await client.GET("/api/jobs/{job_id}/download-staging", {
      params: { path: { job_id: jobId } },
      signal: bounded,
    });
    if (!response.data) throw new Error("缺少扫描结果");
    return response.data;
  });
}

/** 管理员提交的受限暂存身份，不包含存储绝对路径。 */
export type DeleteStagingInput = components["schemas"]["DeleteParameters"];

/**
 * 为管理员提交单个暂存目录清理作业。
 * @param client - 账号感知客户端。
 * @param input - 存储根名、仓库类型和编号、固定 commit 短码。
 * @param signal - 调用方取消信号。
 * @returns 新排队的清理作业，不表示磁盘删除已完成。
 * @throws Error 非管理员、目录占用或请求失败。
 * @sideEffects 发送一次同源提交请求，不直接访问存储根。
 * @timeSemantics 最多等待 10 秒，不自动重试；后端入队时重新核对占用。
 */
export function submitStagingDelete(
  client: HealthClient,
  input: DeleteStagingInput,
  signal: AbortSignal,
): Promise<Job> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const response = await client.POST("/api/jobs/download-staging-delete", {
      body: input,
      signal: bounded,
    });
    if (!response.data) throw new Error("缺少清理作业响应");
    return response.data;
  });
}
