// M1.5-16 分类删除预览的 HTTP 边界；计划由 worker 生成，确认复用通用导航写入接口。
import type { AccountCall } from "./accounts";
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS, type Job } from "./jobs";
import type { components } from "./schema";

/** 删除预览请求直接引用生成契约，字段种类和取值约束由服务端定义。 */
export type ClassificationRemoveParameters =
  components["schemas"]["ClassificationRemoveParameters"];

/**
 * 提交一个场景或任务值的全量删除预览。
 * @param input - 账号客户端、字段种类与待删除值、取消信号。
 * @returns 排队的预览作业；成功后通过既有报告接口读取差异。
 * @throws Error 参数、权限、恢复门禁或传输失败交统一诊断；缺失响应时报错。
 * @sideEffects 一次 POST /api/navigation/classification/remove/preview，不写导航层。
 * @timeSemantics 最多等待 JOB_REQUEST_TIMEOUT_MS，不重试；返回不表示预览已完成。
 */
export function previewClassificationRemoval(
  input: AccountCall<ClassificationRemoveParameters>,
): Promise<Job> {
  return boundedRequest(input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/navigation/classification/remove/preview", {
      body: input.payload,
      signal,
    });
    if (!result.data) throw new Error("删除分类预览未返回作业");
    return result.data;
  });
}
