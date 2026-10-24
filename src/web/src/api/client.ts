// Web 请求边界（ADR 0001、0002）；只使用生成的接口类型和 openapi-fetch，不承载页面状态。
import type { Client, ClientOptions } from "openapi-fetch";
import createClient from "openapi-fetch";
import { createProblemFetch } from "./problems";
import type { components, paths } from "./schema";

/** 健康响应只引用生成类型，禁止另写重复的接口结构。 */
export type HealthResponse = components["schemas"]["HealthResponse"];
/** 客户端方法和路径由 OpenAPI 约束。 */
export type HealthClient = Client<paths>;
/** 注入边界沿用 openapi-fetch 的 Request 输入契约，测试不用替换全局 fetch。 */
export type FetchImplementation = NonNullable<ClientOptions["fetch"]>;

// eslint-disable-next-line no-restricted-globals -- 唯一允许读取默认 fetch 的客户端边界；测试显式注入替身。
const defaultFetch: FetchImplementation = fetch;

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
  return createClient<paths>({ baseUrl: "", fetch: createProblemFetch(fetchImpl) });
}
