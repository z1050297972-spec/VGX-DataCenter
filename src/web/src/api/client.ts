// Web 请求边界（ADR 0001、0002）；只使用生成的接口类型和 openapi-fetch，不承载页面状态。
import type { Client, ClientOptions } from "openapi-fetch";
import createClient from "openapi-fetch";
import { createProblemFetch } from "./problems";
import type { components, paths } from "./schema";
import type { SceneArrays } from "./sceneTypes";

/** 健康响应只引用生成类型，禁止另写重复的接口结构。 */
export type HealthResponse = components["schemas"]["HealthResponse"];
/** 客户端方法和路径由 OpenAPI 约束。 */
export type HealthClient = Client<SceneArrays<paths>>;
/** 注入边界沿用 openapi-fetch 的 Request 输入契约，测试不用替换全局 fetch。 */
export type FetchImplementation = NonNullable<ClientOptions["fetch"]>;

/**
 * 转发到调用时的浏览器 fetch，隔离调用方的 this 接收者。
 *
 * @param args - 沿用 FetchImplementation 的传输参数，包含请求及取消信号。
 * @returns 浏览器 fetch 的响应 Promise，不消费响应体。
 * @throws Error 浏览器的输入、网络或取消错误原样传播，由统一失败适配器处理。
 * @sideEffects 每次调用发送一次请求；调用时读取全局 fetch，不修改全局对象或持久化凭据。
 * @timeSemantics 遵守请求取消信号；不另加超时、等待或重试。
 */
export const defaultFetch: FetchImplementation = (...args) => {
  // eslint-disable-next-line no-restricted-globals -- 唯一默认传输边界，直接调用避免把配置对象绑定为浏览器 fetch 的 this。
  return fetch(...args);
};

/**
 * 创建只请求同源 API 的类型化客户端。
 *
 * @param fetchImpl - 实际传输函数，无单位；省略时使用浏览器 fetch，测试传入独立替身。
 * @returns 新的 openapi-fetch 客户端，基地址为空，请求路径使用 /api/...。
 * @throws 无。创建客户端不发请求；传输错误由调用请求方法的 Promise 拒绝返回。
 * @sideEffects 无；只创建内存对象，不访问网络或修改全局 fetch。
 * @timeSemantics 同步创建；请求的取消和超时由调用方的 AbortSignal 控制。
 */
export function createHealthClient(fetchImpl: FetchImplementation = defaultFetch): HealthClient {
  return createClient<SceneArrays<paths>>({ baseUrl: "", fetch: createProblemFetch(fetchImpl) });
}
