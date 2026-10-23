// 健康查询适配层（工单 02），将 HTTP 失败交给 TanStack Query，不把失败伪装为 ok。
// AbortSignal.timeout 没有主动取消计时器的 API；保留可 clearTimeout 的定时器，
// 在请求提前完成或取消时立即清理，并通过假时钟验证 5000 毫秒的超时边界。
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
export function fetchHealth(client: HealthClient, signal?: AbortSignal): Promise<HealthResponse> {
  if (signal?.aborted) {
    const reason: unknown = signal.reason;
    return Promise.reject(reason instanceof Error ? reason : new Error("健康请求已取消"));
  }
  const timeout = new AbortController();
  // 超时和调用方取消取先发生者；结束后清理定时器，不影响后续查询。
  const timer = setTimeout(() => {
    timeout.abort(new Error("健康请求超时"));
  }, HEALTH_TIMEOUT_MS);
  const requestSignal = signal ? AbortSignal.any([signal, timeout.signal]) : timeout.signal;
  return client
    .GET("/api/health", { signal: requestSignal })
    .then<HealthResponse>(({ data, response }) => {
      // 生成类型只约束编译期；外部 JSON 仍须验证，不能把任意 2xx 当作健康。
      const payload: unknown = data;
      if (
        !response.ok ||
        typeof payload !== "object" ||
        payload === null ||
        !("status" in payload) ||
        payload.status !== "ok"
      ) {
        throw new Error(`健康响应无效，HTTP ${String(response.status)}`);
      }
      return { status: "ok" };
    })
    .finally(() => {
      clearTimeout(timer);
    });
}
