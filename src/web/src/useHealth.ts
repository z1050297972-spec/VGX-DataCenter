// 页面查询层（工单 02）；缓存交给 TanStack Query，传输交给 api/health，不直接调用 fetch。
import type { UseQueryResult } from "@tanstack/react-query";
import type { HealthClient, HealthResponse } from "./api/client";

/** 健康查询缓存有效期为 1000 毫秒；按 ADR 0001 秒级状态更新，不做高频请求。 */
export const HEALTH_STALE_TIME_MS = 1000;

/**
 * 管理一次健康查询的加载、缓存和失败状态。
 *
 * @param client - 非空的类型化客户端；调用期间保持身份稳定，不同客户端不共享缓存。
 * @returns TanStack Query 的健康结果，加载时无 data，成功时 status 为 ok，失败时携带 Error。
 * @throws 无。请求错误保存在返回值的 error 中；调用方必须处于 QueryClientProvider 内。
 * @sideEffects 通过 fetchHealth 发起健康请求，更新查询缓存，不修改 URL 或全局 fetch。
 * @timeSemantics 缓存 HEALTH_STALE_TIME_MS 毫秒，不轮询、不自动重试、不因窗口聚焦刷新；
 * 过期后再次挂载可重新获取，取消信号传递给请求，单次超时由 HEALTH_TIMEOUT_MS 约束。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- A2 契约桩不使用参数；B 实现函数后删除此豁免。
export function useHealth(client: HealthClient): UseQueryResult<HealthResponse> {
  throw new Error("未实现");
}
