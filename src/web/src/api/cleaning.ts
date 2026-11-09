// 清洗预览 HTTP 边界：请求复用账号客户端与作业超时，报告类型集中于临时契约。
import type { AccountCall } from "./accounts";
import type { CleaningPreview, CleaningPreviewSubmission } from "./cleaningTemp";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";
import { toFailureView } from "./problems";

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
    return response.data;
  });
}
