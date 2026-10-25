// Web 报错查询适配层（05/E2）；只使用生成类型和既有客户端，纯文本交给 DiagnosticCard。
// HealthPage 的稳定 loadDetails 回调在展开时调用，TanStack Query 管理请求。
import type { QueryClient } from "@tanstack/react-query";
import type { HealthClient } from "./client";
import type { components } from "./schema";
import type { DiagnosticCardProps } from "../DiagnosticCard";
import apiSchema from "./openapi.json";
import { toFailureView } from "./problems";

/** 报错详情结构只引用 OpenAPI；编号包含请求 uuid4 hex 或作业规范整数文本。 */
export type ErrorDetails = components["schemas"]["ErrorRecord"];

/** SQLite 有符号 64 位整数上限；用 BigInt 校验，避免 Number 丢失精度。 */
const MAX_SQLITE_INTEGER = 9223372036854775807n;

/**
 * 按编号读取完整报错，保持客户端的 problem 失败语义。
 *
 * @param client - createHealthClient 的同源客户端，无单位、非空。
 * @param errorId - 请求 uuid4 hex 或作业正整数文本，无单位、不为空，不接受路径片段。
 * @param signal - 必填取消信号，由 DiagnosticCard 的 ERROR_DETAILS_TIMEOUT_MS（5000 毫秒）控制。
 * @returns GET /api/errors/{error_id} 的 ErrorDetails；运行时验证生成 schema 对应的字段、
 * 编号与查询一致、来源与编号一致、UTC 时间、类别和长度，不将类型断言当校验。
 * @throws Error 非法编号、HTTP 404/422/其他非成功、无效 JSON、缺字段、超长报告、网络失败或取消；
 * 保留统一客户端的安全 cause，绝不把原始响应/异常消息传给卡片。
 * @sideEffects 只发送一次同源 GET，参数由 openapi-fetch 编码；已取消或编号非法时不发送。
 * 不打印日志，不修改 URL、全局 fetch、浏览器存储，不重试。
 * @timeSemantics 沿用调用方 5 秒取消信号，不增加独立时钟或轮询；返回时刻为 UTC。
 */
export function fetchErrorDetails(
  client: HealthClient,
  errorId: ErrorDetails["error_id"],
  signal: AbortSignal,
): Promise<ErrorDetails> {
  if (signal.aborted || !sourceKind(errorId))
    return Promise.reject(new Error("完整报错请求无效或已取消"));
  return client
    .GET("/api/errors/{error_id}", { params: { path: { error_id: errorId } }, signal: signal })
    .then(({ data, response }) => {
      if (!response.ok || !validDetails(data, errorId)) throw new Error("完整报错响应无效");
      return data;
    })
    .catch((error: unknown) => {
      throw new Error("请求失败", { cause: toFailureView(error) });
    });
}

function sourceKind(identifier: string): "request" | "job" | undefined {
  if (/^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/u.test(identifier)) return "request";
  if (/^[1-9][0-9]{0,18}$/u.test(identifier) && BigInt(identifier) <= MAX_SQLITE_INTEGER)
    return "job";
  return undefined;
}

// 字段名、类别和长度直接来自生成 schema；运行时不依赖类型断言验证不可信 JSON。
const detailProperties = apiSchema.components.schemas.ErrorRecord.properties;
const detailKeys = Object.keys(detailProperties);
const categories: readonly string[] = apiSchema.components.schemas.DiagnosticCategory.enum;

function boundedText(value: unknown, maximum: number): value is string {
  if (typeof value !== "string" || value.length === 0) return false;
  let count = 0;
  // Python 的长度单位是 Unicode 字符，不是 JavaScript 的 UTF-16 码元。
  const characters = value[Symbol.iterator]();
  while (!characters.next().done) {
    count += 1;
    if (count > maximum) return false;
  }
  return true;
}

function utcMoment(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    !/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$/u.test(value)
  )
    return false;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 19) === value.slice(0, 19);
}

function validDetails(value: unknown, identifier: string): value is ErrorDetails {
  if (typeof value !== "object" || value === null) return false;
  const keys = Object.keys(value);
  if (keys.length !== detailKeys.length || !keys.every((key) => detailKeys.includes(key)))
    return false;
  return validMetadata(value, identifier) && validReport(value);
}

function validMetadata(value: object, identifier: string): boolean {
  return (
    "error_id" in value &&
    value.error_id === identifier &&
    "source_kind" in value &&
    value.source_kind === sourceKind(identifier) &&
    "occurred_at" in value &&
    utcMoment(value.occurred_at) &&
    "category" in value &&
    typeof value.category === "string" &&
    categories.includes(value.category)
  );
}

function validReport(value: object): boolean {
  return (
    "summary" in value &&
    boundedText(value.summary, detailProperties.summary.maxLength) &&
    value.summary.trim().length > 0 &&
    !/[\r\n\v\f\u0085\u2028\u2029]/u.test(value.summary) &&
    "report" in value &&
    boundedText(value.report, detailProperties.report.maxLength)
  );
}

/**
 * 创建可直接交给 DiagnosticCard.loadDetails 的稳定报错加载器。
 *
 * @param client - 页面复用的非空 API 客户端，无单位。
 * @param queryClient - QueryClientProvider 中的 QueryClient，无单位；不创建全局共享缓存。
 * @returns loadDetails 回调：通过 queryClient.query(options) 调用 fetchErrorDetails，retry=false、staleTime=0、
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
  client: HealthClient,
  queryClient: QueryClient,
): NonNullable<DiagnosticCardProps["loadDetails"]> {
  let identity = clientKeys.get(client);
  if (identity === undefined) {
    identity = nextClientKey++;
    clientKeys.set(client, identity);
  }
  return (errorId, signal) => {
    const queryKey = ["error-details", identity, errorId];

    return queryClient
      .query({
        queryKey,
        queryFn: ({ signal: querySignal }) =>
          fetchErrorDetails(client, errorId, AbortSignal.any([signal, querySignal])),
        retry: false,
        staleTime: 0,
        gcTime: 0,
      })
      .then(detailsText)
      .finally(() => {
        queryClient.removeQueries({ queryKey, exact: true });
      });
  };
}

// 函数型传输不能靠 JSON 哈希区分；弱引用身份避免不同客户端串用报错缓存。
const clientKeys = new WeakMap<HealthClient, number>();
let nextClientKey = 0;

function detailsText(details: ErrorDetails): string {
  const localTime = new Date(details.occurred_at).toLocaleString(undefined, {
    timeZoneName: "short",
  });
  return `发生时间：${localTime}\n类别：${details.category}\n摘要：${details.summary}\n来源：${details.source_kind} ${details.error_id}\n\n${details.report}`;
}
