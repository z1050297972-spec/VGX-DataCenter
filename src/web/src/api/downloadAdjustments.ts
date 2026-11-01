// 下载详情仅通过生成的 HTTP 类型读写调参通道，不访问下载进程或存储根。
import type { components } from "./schema";
import type { HealthClient } from "./client";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS } from "./jobs";

/** 下载线程最近发布的快照。 */
export type DownloadStatus = components["schemas"]["DownloadStatus"];
/** 只包含允许动态调整的并发与总速率。 */
export type DownloadAdjustment = components["schemas"]["DownloadAdjustment"];

/**
 * 读取下载快照。
 * @param client - 账号感知的类型化客户端。
 * @param jobId - 规范十进制作业编号。
 * @param signal - 页面取消信号。
 * @returns 数据库中的最新快照。
 * @throws Error 请求失败或响应没有数据。
 * @sideEffects 发送一次只读请求。
 * @timeSemantics 超时上限 10 秒，不重试。
 */
export function getDownloadStatus(
  client: HealthClient,
  jobId: string,
  signal: AbortSignal,
): Promise<DownloadStatus> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const result = await client.GET("/api/jobs/{job_id}/download-adjustment", {
      params: { path: { job_id: jobId } },
      signal: bounded,
    });
    if (!result.data) throw new Error("缺少下载状态");
    return result.data;
  });
}

/**
 * 提交下载并发和速率的调整。
 * @param client - 账号感知的类型化客户端。
 * @param jobId - 规范十进制作业编号。
 * @param adjustment - 需要调整的参数，速率单位 B/s。
 * @param signal - 页面取消信号。
 * @returns 提交后的状态，实际生效版本可能落后。
 * @throws Error 请求失败或响应没有数据。
 * @sideEffects 向服务端提交一次调参请求。
 * @timeSemantics 超时上限 10 秒，不自动重试。
 */
export function adjustDownload(
  client: HealthClient,
  jobId: string,
  adjustment: DownloadAdjustment,
  signal: AbortSignal,
): Promise<DownloadStatus> {
  return boundedRequest(signal, JOB_REQUEST_TIMEOUT_MS, async (bounded) => {
    const result = await client.POST("/api/jobs/{job_id}/download-adjustment", {
      params: { path: { job_id: jobId } },
      body: adjustment,
      signal: bounded,
    });
    if (!result.data) throw new Error("缺少下载状态");
    return result.data;
  });
}
