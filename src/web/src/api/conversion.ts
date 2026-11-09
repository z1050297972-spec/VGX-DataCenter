// 转换提交边界（M4.5-04）：只能从清洗报告转换，禁止绕过预览直接提交工具。
import type { AccountCall } from "./accounts";
import type { CleaningConversionSubmission } from "./cleaningTemp";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";
import { toFailureView } from "./problems";

/**
 * 按清洗报告和当前剔除选择提交转换。
 * @param input - 预览作业编号、输出版本、空间百分比和 GiB 偏置、稳定的文件及段下标。
 * @returns 新转换作业；服务端再次核对管理员权限及报告有效性。
 * @throws Error 权限、报告过期、参数、网络或超时失败，以统一诊断呈现。
 * @sideEffects POST /api/cleaning-previews/{job_id}/convert；不在浏览器访问数据路径。
 * @timeSemantics 请求最多 JOB_REQUEST_TIMEOUT_MS 毫秒，不等待转换完成，不自动重试。
 */
export function convertFromCleaningPreview(
  input: AccountCall<CleaningConversionSubmission>,
): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.POST("/api/cleaning-previews/{job_id}/convert", {
      params: { path: { job_id: input.payload.jobId } },
      body: input.payload.parameters,
      signal,
    });
    if (!response.data) throw new Error("请求失败", { cause: toFailureView(null) });
    return response.data;
  });
}
