// 导航层恢复失败标记的 HTTP 契约（M1-07）；类型来自 OpenAPI 生成文件，编号保持十进制文本。
import { boundedRequest } from "./_request";
import { JOB_REQUEST_TIMEOUT_MS } from "./jobs";
import { toFailureView } from "./problems";
import type { AccountCall } from "./accounts";
import type { components } from "./schema";

/** 标记状态；blocked=false 时没有其他字段。 */
export type RecoveryBlock = components["schemas"]["RecoveryBlockResponse"];
/** 一项对不上的步骤。 */
export type MismatchItem = components["schemas"]["MismatchItemResponse"];
/** 管理员确认的结果。 */
export type AcknowledgeResult = components["schemas"]["AcknowledgeResponse"];

/**
 * 读取当前的恢复失败标记。
 * @param _input - 账号客户端、undefined payload 和取消信号；所有登录账号可读。
 * @returns GET /api/navigation/recovery-block 的 RecoveryBlock。
 * @throws Error 网络、超时、取消、401/403/服务端错误经 toFailureView。
 * @sideEffects 一次同源 GET，不读导航层。
 * @timeSemantics 上限 JOB_REQUEST_TIMEOUT_MS，无重试；布局约每秒轮询。
 */
export function getRecoveryBlock(_input: AccountCall): Promise<RecoveryBlock> {
  return boundedRequest(_input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await _input.client.GET("/api/navigation/recovery-block", { signal });
    return required(response.data);
  });
}

/**
 * 管理员确认已处理，放行写导航层的作业。
 * @param _input - 账号客户端、undefined payload 和取消信号。
 * @returns POST /api/navigation/recovery-block/acknowledge 的已清理作业编号。
 * @throws Error 403 非管理员、409 没有标记、网络等失败交统一诊断，不乐观清除。
 * @sideEffects 一次同源 POST（带 Origin）；服务端写一条 confirm_navigation_recovery 操作日志。
 * @timeSemantics 上限 JOB_REQUEST_TIMEOUT_MS，不重试不确定的写请求。
 */
export function acknowledgeRecoveryBlock(_input: AccountCall): Promise<AcknowledgeResult> {
  return boundedRequest(_input.signal, JOB_REQUEST_TIMEOUT_MS, async (signal) => {
    const response = await _input.client.POST("/api/navigation/recovery-block/acknowledge", {
      signal,
    });
    return required(response.data);
  });
}

function required<T>(data: T | undefined): T {
  if (data === undefined || data === null)
    throw new Error("请求失败", { cause: toFailureView(null) });
  return data;
}
