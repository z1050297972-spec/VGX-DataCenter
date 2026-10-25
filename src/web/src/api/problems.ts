// 请求失败适配边界（M0 工单 04）；使用原生 Response/Error 和生成类型，不安装新依赖。
// 原生 fetch 不因 HTTP 4xx/5xx 自动抛错；由包装器识别 problem，交给 TanStack Query。
// 只在此层选择网络/代理失败的固定文案；组件不拼接服务器错误或展示 HTML。
import type { FetchImplementation } from "./client";
import type { components } from "./schema";
import apiSchema from "./openapi.json";

/** RFC 9457 载荷只取生成的 OpenAPI 类型，不另写字段结构。 */
export type ProblemResponse = components["schemas"]["ProblemResponse"];

/** 本地展示状态不是接口载荷；缺少服务端错误编号时不伪造编号或程序缺陷。 */
export type RequestFailureView =
  | {
      /** 已通过运行时校验的服务端 problem；无单位，固定 problem。 */
      kind: "problem";
      /** 生成类型的完整响应；程序缺陷的 diagnostics 必须为空。 */
      problem: ProblemResponse;
    }
  | {
      /** 网络、超时、无效响应或未知拒绝值；无单位，固定 unavailable。 */
      kind: "unavailable";
      /** 固定安全文案；不拼接 error.message、响应体、HTML 或状态文本。 */
      message: "请求失败，请检查网络或稍后重试。";
      /** 可选响应头编号；仅接受服务端 uuid4.hex，无单位；缺失/非法时省略。 */
      errorId?: ProblemResponse["error_id"];
    };

/**
 * 从失败响应读取并验证 problem，避免把生成类型当成运行时校验。
 *
 * @param response - HTTP Response，无单位；允许已消费或损坏的 body，仅解析克隆副本；调用方须有请求超时。
 * @returns 合法且 status 与 HTTP 状态一致的 ProblemResponse；成功响应、错误媒体类型、
 * 空体、坏 JSON、必填字段缺失、未知枚举/额外字段、非法 uuid、字段约束不符、缺陷含诊断、
 * 状态/类别不匹配或克隆/读取失败均返回 null。媒体类型忽略大小写及参数，须为
 * application/problem+json；不读取并展示代理 HTML。验证约束与后端模型相同；省略的
 * type/diagnostics/expected 分别规范成 about:blank/空数组/null，与后端默认值一致；
 * D1 的 error_chain 只接受非空白文本数组，省略时规范成空数组，保留外到内顺序。
 * @throws 无。损坏响应和读取失败作为不可用响应，不泄漏解析器原文。
 * @sideEffects 读取 response.clone() 的 body，不消费原响应，不发新请求，不写日志。
 * @timeSemantics 沿用调用请求的 AbortSignal 和超时；不加重试、轮询或独立计时器。
 */
export function readProblemResponse(response: Response): Promise<ProblemResponse | null> {
  if (
    response.status < 400 ||
    response.headers.get("content-type")?.split(";")[0]?.trim().toLowerCase() !==
      "application/problem+json"
  )
    return Promise.resolve(null);
  try {
    return response
      .clone()
      .json()
      .then((value: unknown) => parseProblem(value, response.status))
      .catch(() => null);
  } catch {
    return Promise.resolve(null);
  }
}

/**
 * 包装传输，将 HTTP 失败与网络拒绝统一成可供页面消费的原生 Error。
 *
 * @param fetchImpl - 已注入的传输函数，无单位；与 openapi-fetch 的 fetch 契约相同。
 * @returns 独立 FetchImplementation；2xx/3xx 返回原 Response 对象，4xx/5xx 读取 problem 后拒绝；
 * 不改变成功响应的 body、headers、请求 URL 或取消信号。适配器创建本身不发送请求。
 * @throws Error 返回的传输函数在 HTTP 失败、网络断开、超时或取消时拒绝；message 固定为
 * “请求失败”，cause 是 RequestFailureView：合法 problem 原样保留，其余使用固定不可用文案。
 * 无效 problem 的 X-Request-ID 合法时保留编号；网络失败无编号。绝不把原始异常放进 cause。
 * @sideEffects 每次调用返回的传输函数恰好调用 fetchImpl 一次；按 readProblemResponse 读取
 * 失败响应克隆，不打印日志、不更改全局 fetch。失败不会自动重试。
 * @timeSemantics 原样传递 Request.signal；超时继续由 fetchHealth 的 HEALTH_TIMEOUT_MS 控制。
 * createHealthClient 使用本包装器，fetchHealth 透传该 Error；不改变既有超时契约。
 */
export function createProblemFetch(fetchImpl: FetchImplementation): FetchImplementation {
  return async (...args) => {
    let response: Response;
    try {
      response = await fetchImpl(...args);
    } catch {
      throw new Error("请求失败", { cause: unavailable() });
    }
    if (response.status < 400) return response;
    const problem = await readProblemResponse(response);
    throw new Error("请求失败", {
      cause: problem
        ? { kind: "problem", problem }
        : unavailable(response.headers.get("X-Request-ID") ?? undefined),
    });
  };
}

/**
 * 把查询错误转换为诊断卡片输入，不展示任意异常文字。
 *
 * @param error - TanStack Query 的未知拒绝值，无单位，允许 null/undefined/任意对象。
 * @returns 验证原生 Error.cause 后返回 RequestFailureView；合法 problem 和合法的不可用状态
 * 保持内容，其余（包括访问属性抛错的对象）统一为无编号的固定不可用提示。
 * 不把 HTTP 状态或本地失败伪装成程序缺陷，不自动从 error.message 取内容。
 * @throws 无。未知载荷和非法编号都走固定兜底。
 * @sideEffects 无；不发请求、不记录日志、不改变 error 或页面 URL。
 * @timeSemantics 同步转换，不缓存错误，不读时钟。
 */
export function toFailureView(error: unknown): RequestFailureView {
  try {
    if (error instanceof Error && record(error.cause)) {
      const cause: Record<string, unknown> = error.cause;
      if (cause.kind === "problem") {
        const problem = parseProblem(cause.problem);
        if (problem) return { kind: "problem", problem };
      }
      if (cause.kind === "unavailable")
        return unavailable(typeof cause.errorId === "string" ? cause.errorId : undefined);
    }
  } catch {
    return unavailable();
  }
  return unavailable();
}

// 结构名和枚举来自生成的 OpenAPI，避免增加字段后漏改手写的字段清单。
type Diagnostic = components["schemas"]["Diagnostic"];
type DiagnosticInput = Omit<Diagnostic, "expected" | "error_chain"> &
  Partial<Pick<Diagnostic, "expected" | "error_chain">>;
const diagnosticKeys = Object.keys(apiSchema.components.schemas.Diagnostic.properties);
const problemKeys = Object.keys(apiSchema.components.schemas.ProblemResponse.properties);
const categories: readonly string[] = apiSchema.components.schemas.DiagnosticCategory.enum;
const levels: readonly string[] = apiSchema.components.schemas.DiagnosticLevel.enum;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): value is string {
  return typeof value === "string" && /\S/u.test(value);
}

function shape(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return record(value) && Object.keys(value).every((key) => keys.includes(key));
}

function optionalText(value: unknown): boolean {
  return value === undefined || value === null || text(value);
}

function optionalChain(value: unknown): boolean {
  return value === undefined || (Array.isArray(value) && value.every(text));
}

function diagnosticMetadata(value: Record<string, unknown>): boolean {
  if (typeof value.level !== "string" || !levels.includes(value.level)) return false;
  if (typeof value.category !== "string" || !categories.includes(value.category)) return false;
  if (value.category === "conflict" && value.source !== "平台") return false;
  return ["stage", "source", "rule", "actual", "consequence", "next_step"].every((key) =>
    text(value[key]),
  );
}

function diagnosticObjects(value: unknown): boolean {
  if (!Array.isArray(value)) return false;
  const keys = new Set<string>();
  return value.every((item: unknown) => {
    if (
      !shape(item, ["key", "value"]) ||
      !text(item.key) ||
      !text(item.value) ||
      keys.has(item.key)
    )
      return false;
    keys.add(item.key);
    return true;
  });
}

function validDiagnostic(value: unknown): value is DiagnosticInput {
  if (!shape(value, diagnosticKeys)) return false;
  return (
    diagnosticMetadata(value) &&
    optionalText(value.expected) &&
    optionalChain(value.error_chain) &&
    diagnosticObjects(value.objects)
  );
}

function statusFor(
  input: Record<string, unknown>,
  httpStatus?: number,
): readonly [ProblemResponse["category"], string] | undefined {
  if (typeof input.status !== "number" || !Number.isInteger(input.status)) return undefined;
  if (httpStatus !== undefined && httpStatus !== input.status) return undefined;
  const status = statusTable[input.status];
  if (!status || status[0] !== input.category || status[1] !== input.title) return undefined;
  return status;
}

function problemHeader(
  input: Record<string, unknown>,
  httpStatus?: number,
): Omit<ProblemResponse, "diagnostics"> | null {
  const status = statusFor(input, httpStatus);
  if (!status || typeof input.status !== "number") return null;
  if (input.type !== undefined && input.type !== "about:blank") return null;
  if (!text(input.detail) || typeof input.error_id !== "string" || !requestId.test(input.error_id))
    return null;
  return {
    type: "about:blank",
    title: status[1],
    status: input.status,
    category: status[0],
    detail: input.detail,
    error_id: input.error_id,
  };
}

function parseProblem(input: unknown, httpStatus?: number): ProblemResponse | null {
  if (!shape(input, problemKeys)) return null;
  const header = problemHeader(input, httpStatus);
  const diagnostics: unknown = input.diagnostics === undefined ? [] : input.diagnostics;
  if (!header || !Array.isArray(diagnostics) || !diagnostics.every(validDiagnostic)) return null;
  if (diagnostics.some((d: DiagnosticInput) => d.category !== header.category)) return null;
  if (header.category === "defect" && diagnostics.length > 0) return null;
  return {
    ...header,
    diagnostics: diagnostics.map((d: DiagnosticInput) => ({
      ...d,
      expected: d.expected ?? null,
      error_chain: d.error_chain ?? [],
    })),
  };
}

// 对应后端 ProblemResponse.error_id：32 位小写 uuid4 hex，包含 v4 和 variant 位约束。
const requestId = /^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$/u;

// 对应 CODING_STANDARDS 6.2；修改规范表时须同步更新此运行时校验映射。
// 类别与状态码的关联不能由生成的字段类型在运行时检查。
const statusTable: Record<number, readonly [ProblemResponse["category"], string]> = {
  400: ["input", "Bad Request"],
  401: ["input", "Unauthorized"],
  403: ["input", "Forbidden"],
  429: ["input", "Too Many Requests"],
  404: ["input", "Not Found"],
  422: ["input", "Unprocessable Entity"],
  409: ["conflict", "Conflict"],
  502: ["external", "Bad Gateway"],
  500: ["defect", "Internal Server Error"],
};

function unavailable(errorId?: string): RequestFailureView {
  return {
    kind: "unavailable",
    message: "请求失败，请检查网络或稍后重试。",
    ...(errorId && requestId.test(errorId) ? { errorId } : {}),
  };
}
