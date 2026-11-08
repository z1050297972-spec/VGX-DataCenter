// 人工转换关系的 HTTP 边界；使用生成契约，预览确认复用通用导航写入。
import type { AccountCall } from "./accounts";
import type { components } from "./schema";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";

/** 登记或删除记录的请求，字段约束以服务端生成契约为准。 */
export type LineageParameters = components["schemas"]["LineageParameters"];

/**
 * 提交人工转换关系的添加或删除预览。
 * @param input - 客户端、当前数据集编号、操作参数和取消信号。
 * @returns 排队的预览作业；通过既有报告接口读取差异。
 * @throws Error 输入、权限、恢复门禁或传输失败交统一诊断；缺失响应时报错。
 * @sideEffects 一次 POST /api/navigation/lineage/preview，不执行导航写入。
 * @timeSemantics 最多等待 JOB_REQUEST_TIMEOUT_MS，不自动重试，不等待 worker 完成。
 */
export function previewLineage(input: AccountCall<LineageParameters>): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await input.client.POST("/api/navigation/lineage/preview", {
      body: input.payload,
      signal,
    });
    if (!response.data) throw new Error("转换关系预览未返回作业");
    return response.data;
  });
}
