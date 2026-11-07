// M1-09 导航写入门禁：恢复失败、未知或读取失败时一律禁用，并给出原因。
import type { UseQueryResult } from "@tanstack/react-query";
import type { RecoveryBlock } from "../api/navigation";

/**
 * 把恢复状态查询翻译成禁用原因。
 * @param recovery - useRecoveryBlock 的查询结果。
 * @param verb - 被禁止的动作名，用于原因文案（例如"提交"）。
 * @returns 可以操作时为 null，否则为面向用户的原因文本。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 纯函数，取决于最近一次查询快照。
 */
export function recoveryReason(
  recovery: Pick<UseQueryResult<RecoveryBlock>, "isError" | "data">,
  verb: string,
): string | null {
  if (recovery.isError) return `无法核对恢复状态，暂不能${verb}`;
  if (recovery.data?.blocked) return `导航层恢复失败，请管理员处理后再${verb}`;
  if (recovery.data?.blocked !== false) return "正在核对导航层恢复状态";
  return null;
}
