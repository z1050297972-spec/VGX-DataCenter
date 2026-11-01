// 管理员 token 接口；凭据不进入 URL、缓存、日志或服务端响应。
import { boundedRequest } from "./_request";
import { ACCOUNT_TIMEOUT_MS } from "./accounts";
import type { HealthClient } from "./client";
import type { components } from "./schema";

type State = components["schemas"]["TokenState"];

/**
 * 读取 token 是否设置。
 * @param client - 管理员客户端。
 * @param signal - 请求取消信号。
 * @returns 凭据存在状态，不含凭据本身。
 * @throws Error 请求失败。
 * @sideEffects 一次只读请求。
 * @timeSemantics 最多等待 10 秒，不重试。
 */
export function getTokenState(client: HealthClient, signal: AbortSignal): Promise<State> {
  return boundedRequest(signal, ACCOUNT_TIMEOUT_MS, async (bounded) => {
    const response = await client.GET("/api/downloads/token", { signal: bounded });
    if (!response.data) throw new Error("缺少状态");
    return response.data;
  });
}

/**
 * 设置或清除 token，密钥仅由调用方的短期闭包持有。
 * @param client - 管理员客户端。
 * @param token - 密钥，null 表示清除。
 * @param signal - 请求取消信号。
 * @returns 最新存在状态，不含凭据。
 * @throws Error 请求失败。
 * @sideEffects 发送一次写请求，不存浏览器持久存储。
 * @timeSemantics 最多等待 10 秒，不自动重试。
 */
export function changeToken(
  client: HealthClient,
  token: string | null,
  signal: AbortSignal,
): Promise<State> {
  return boundedRequest(signal, ACCOUNT_TIMEOUT_MS, async (bounded) => {
    const response =
      token === null
        ? await client.DELETE("/api/downloads/token", { signal: bounded })
        : await client.PUT("/api/downloads/token", { body: { token }, signal: bounded });
    if (!response.data) throw new Error("缺少状态");
    return response.data;
  });
}
