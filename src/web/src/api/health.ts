// 健康查询适配层（工单 02），将 HTTP 失败交给 TanStack Query，不把失败伪装为 ok。
import type { HealthClient, HealthResponse } from "./client";

/** 本票契约选择健康请求上限 5000 毫秒，避免后端无响应时页面永久等待；由骨架评审确认。 */
export const HEALTH_TIMEOUT_MS = 5000;

/**
 * 通过类型化客户端读取健康状态。
 *
 * @param client - createHealthClient 创建的非空客户端，无单位。
 * @param signal - 调用方取消信号，可省略；已取消时立即拒绝，不发送请求。
 * @returns GET /api/health 的 HealthResponse；只接受 status 为 ok 的 JSON 对象。
 * @throws Error 请求失败、非 2xx、缺少响应或载荷不符合健康契约时拒绝 Promise。
 * @sideEffects 通过 client 发送一次同源 GET /api/health，不写 URL、存储或全局对象。
 * @timeSemantics 最长 HEALTH_TIMEOUT_MS 毫秒，合并调用方取消信号；取消或超时拒绝，不重试。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- A2 契约桩不使用参数；B 实现函数后删除此豁免。
export function fetchHealth(client: HealthClient, signal?: AbortSignal): Promise<HealthResponse> {
  throw new Error("未实现");
}
