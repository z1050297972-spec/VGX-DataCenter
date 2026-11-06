// M1.5-15 回填预览的 HTTP 边界；只提交空参数，计划与迁移规则全部由 worker 计算。
import type { AccountCall } from "./accounts";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";

/**
 * 管理员提交全部数据集的信息回填预览。
 * @param input - 账号客户端、undefined 载荷及取消信号，不接受路径或数据集范围。
 * @returns 排队的只读预览作业，成功后读取既有导航预览报告。
 * @throws Error 权限、恢复门禁、请求或响应缺失交统一诊断。
 * @sideEffects 一次 POST /api/navigation/backfill/preview，尚不写导航层。
 * @timeSemantics 请求最多 JOB_REQUEST_TIMEOUT_MS，不自动重试；取消不保证服务端没有排队。
 */
export function previewInformationBackfill(input: AccountCall): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/navigation/backfill/preview", {
      body: {},
      signal,
    });
    if (!result.data) throw new Error("回填预览未返回作业");
    return result.data;
  });
}
