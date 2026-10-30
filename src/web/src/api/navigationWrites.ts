// M1-09 HTTP 边界：载荷只取生成契约，不在浏览器重算路径或反向计划。
import type { AccountCall } from "./accounts";
import type { components } from "./schema";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";

/** 单数据集改指向输入，路径存在性由 worker 核对。 */
export type RepointInput = components["schemas"]["RepointParameters"];
/** 仅引用已保存预览和用户明确确认的队列编号。 */
export type WriteConfirmation = components["schemas"]["ConfirmCreationRequest"];

/**
 * 提交只读改指向预览。
 * @param input - 生成的前缀输入、账号客户端及挂载取消信号。
 * @returns queued 预览作业；不代表导航写入成功。
 * @throws Error 权限、输入、网络或超时错误交统一诊断。
 * @sideEffects 一次同源 POST，不提交执行计划。
 * @timeSemantics 上限 JOB_REQUEST_TIMEOUT_MS，无 POST 重试。
 */
export function previewRepoint(input: AccountCall<RepointInput>): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.POST("/api/datasets/repoint-previews", {
      body: input.payload,
      signal,
    });
    if (!response.data) throw new Error("改指向预览未返回作业");
    return response.data;
  });
}

/**
 * 确认已保存的导航预览并提交公共写入作业。
 * @param input - 预览文本编号、已确认队列编号、客户端及取消信号。
 * @returns nav_write_apply 的 queued 作业，编号保留为文本。
 * @throws Error 新排队项通过409诊断返回，其他请求故障沿用统一处理。
 * @sideEffects 一次同源 POST，不重新计算计划，不自动重试。
 * @timeSemantics 使用 JOB_REQUEST_TIMEOUT_MS，返回不代表写入完成。
 */
export function confirmNavigationWrite(input: AccountCall<WriteConfirmation>): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.POST("/api/navigation/writes", {
      body: input.payload,
      signal,
    });
    if (!response.data) throw new Error("导航写入未返回作业");
    return response.data;
  });
}

/**
 * 为实际写作业提交只读撤回预览。
 * @param input - 被撤回作业的文本编号、账号客户端及取消信号。
 * @returns nav_revert_preview 的 queued 作业，不直接执行撤回。
 * @throws Error 目标不存在、类型错误、权限或请求失败经统一诊断呈现。
 * @sideEffects 一次同源 POST；永久变更记录和后像差异由 worker 检查。
 * @timeSemantics 使用 JOB_REQUEST_TIMEOUT_MS；不因打开撤回页面自动调用，不重试。
 */
export function previewRevert(input: AccountCall<string>): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.POST("/api/jobs/{target_job_id}/revert-previews", {
      params: { path: { target_job_id: input.payload } },
      signal,
    });
    if (!response.data) throw new Error("撤回预览未返回作业");
    return response.data;
  });
}
