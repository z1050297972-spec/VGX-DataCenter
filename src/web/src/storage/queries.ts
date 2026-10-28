// 页面查询生命周期（10）：只在进入页面与显式点击时检查，复用账号隔离缓存。
import type { UseQueryResult } from "@tanstack/react-query";
import type { StorageRoots } from "../api/storage";

/**
 * 为当前账号提供一次挂载检查和手动重新检查能力。
 * @returns StorageRoots 查询状态及 refetch；失败保留 error，不合成在线或空状态。
 * @throws Error 账号 Provider 缺失；传输故障通过查询结果交 DiagnosticCard。
 * @sideEffects 使用当前账号客户端，queryKey 前缀 storage-roots 并包含账号编号；换号清理、卸载取消；不改 URL。
 * @timeSemantics 进入页面必查一次，重新检查按钮触发 refetch；无轮询、重试、聚焦或重连刷新，gcTime=0 防止重入复用旧状态。
 */
export function useStorageRoots(): UseQueryResult<StorageRoots> {
  throw new Error("NotImplementedError");
}
