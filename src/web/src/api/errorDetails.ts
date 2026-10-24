// Web 报错查询适配层（05/E2）；只使用生成类型和既有客户端，纯文本交给 DiagnosticCard。
// 骨架不发请求；实现阶段由 HealthPage 的稳定 loadDetails 回调调用，TanStack Query 管理请求。
import type { QueryClient } from "@tanstack/react-query";
import type { HealthClient } from "./client";
import type { components } from "./schema";
import type { DiagnosticCardProps } from "../DiagnosticCard";

/** 报错详情结构只引用 OpenAPI；编号包含请求 uuid4 hex 或作业规范整数文本。 */
export type ErrorDetails = components["schemas"]["ErrorRecord"];

/**
 * 按编号读取完整报错，保持客户端的 problem 失败语义。
 *
 * @param _client - createHealthClient 的同源客户端，无单位、非空。
 * @param _errorId - 请求 uuid4 hex 或作业正整数文本，无单位、不为空，不接受路径片段。
 * @param _signal - 必填取消信号，由 DiagnosticCard 的 ERROR_DETAILS_TIMEOUT_MS（5000 毫秒）控制。
 * @returns GET /api/errors/{error_id} 的 ErrorDetails；运行时验证生成 schema 对应的字段、
 * 编号与查询一致、来源与编号一致、UTC 时间、类别和长度，不将类型断言当校验。
 * @throws Error 非法编号、HTTP 404/422/其他非成功、无效 JSON、缺字段、超长报告、网络失败或取消；
 * 保留统一客户端的安全 cause，绝不把原始响应/异常消息传给卡片。
 * @sideEffects 只发送一次同源 GET，参数由 openapi-fetch 编码；已取消或编号非法时不发送。
 * 不打印日志，不修改 URL、全局 fetch、浏览器存储，不重试。
 * @timeSemantics 沿用调用方 5 秒取消信号，不增加独立时钟或轮询；返回时刻为 UTC。
 */
export function fetchErrorDetails(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 骨架只允许 throw；实现阶段使用该参数并删除豁免。
  _client: HealthClient,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 骨架只允许 throw；实现阶段使用该参数并删除豁免。
  _errorId: ErrorDetails["error_id"],
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 骨架只允许 throw；实现阶段使用该参数并删除豁免。
  _signal: AbortSignal,
): Promise<ErrorDetails> {
  throw new Error("未实现");
}

/**
 * 创建可直接交给 DiagnosticCard.loadDetails 的稳定报错加载器。
 *
 * @param _client - 页面复用的非空 API 客户端，无单位。
 * @param _queryClient - QueryClientProvider 中的 QueryClient，无单位；不创建全局共享缓存。
 * @returns loadDetails 回调：通过 fetchQuery 调用 fetchErrorDetails，retry=false、staleTime=0、
 * gcTime=0，键含详情命名空间、客户端身份和编号；不跨账号长期保留报告。
 * 成功返回发生时间（浏览器本地时间并含时区）、类别、摘要、来源种类及编号和原报告纯文本；
 * report 段逐字不变，全部按 React 文本渲染。每个展开请求只发送一次，折叠复用交给卡片。
 * @throws Error 返回的回调在 404、网络/协议错误或取消时拒绝；创建函数本身不抛请求错误。
 * 卡片统一显示“完整报错暂不可用，请按编号查询运行日志。”，不展示代理 HTML 或错误原文。
 * @sideEffects 创建时无请求；回调只在首次展开时查询。组合 Query signal 与卡片 signal，
 * 卸载/切换编号/切换加载器取消并移除已结束查询，迟到响应不更新旧卡片，不修改页面 URL。
 * @timeSemantics 由卡片维持 ERROR_DETAILS_TIMEOUT_MS 的 5 秒上限，不轮询、不自动重试。
 */
export function createErrorDetailsLoader(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 骨架只允许 throw；实现阶段使用该参数并删除豁免。
  _client: HealthClient,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 骨架只允许 throw；实现阶段使用该参数并删除豁免。
  _queryClient: QueryClient,
): NonNullable<DiagnosticCardProps["loadDetails"]> {
  throw new Error("未实现");
}
