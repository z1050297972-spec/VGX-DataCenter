// 页面查询层（11 M2）：缓存由 TanStack Query 管理，客户端身份隔离，不直接调用 fetch。
import type { UseQueryResult } from "@tanstack/react-query";
import type { HealthClient } from "./api/client";

/** 版本每次进程启动才变化；缓存 60000 毫秒，避免页面间跳转重复查询。 */
export const VERSION_STALE_TIME_MS = 60000;

/**
 * 提供服务端版本文字的加载、成功及失败状态。
 * @param _client - 同源客户端；同实例复用请求，不同客户端不共享版本缓存。
 * @returns TanStack Query 字符串查询结果；失败保留 error，不替换为伪造版本。
 * @throws 无；请求错误通过查询状态返回，调用者必须位于 QueryClientProvider 内。
 * @sideEffects 调用 fetchPlatformVersion 并更新当前应用内存缓存，不写浏览器持久存储。
 * @timeSemantics 缓存 VERSION_STALE_TIME_MS 毫秒；不轮询、不自动重试；窗口聚焦且缓存过期时重新查询以发现部署升级。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 仅抛异常的契约函数保留客户端依赖；函数使用参数后删除。
export function usePlatformVersion(_client: HealthClient): UseQueryResult<string> {
  throw new Error("NotImplementedError");
}
