// 日志 HTTP 契约（07）：只复用生成类型和账号感知客户端，不保存原生 fetch 为对象方法。
// 浏览器装配继续使用 api/client.ts 的 defaultFetch；不新建绕过 401 清缓存的传输通道。
import { boundedRequest } from "./_request";
import { toFailureView } from "./problems";
import type { AccountCall } from "./accounts";
import type { components, operations } from "./schema";

/** 操作日志页响应，所有编号是文本，不能转换成 Number。 */
export type OperationLogPage = components["schemas"]["OperationListResponse"];
/** 登录日志页响应；未知账号的名字字段为 null。 */
export type LoginLogPage = components["schemas"]["LoginListResponse"];
/** 保留期请求与响应，严格整数 7-365 天，来自 OpenAPI。 */
export type AuditRetention = components["schemas"]["RetentionPayload"];
/** 操作日志 query：account_id 筛操作人，target_account_id 筛对象账号；两个条件取交集，均由 OpenAPI 生成。 */
export type OperationSearch = NonNullable<operations["list_operation_logs"]["parameters"]["query"]>;
/** 登录日志 query 字段；筛选中的 account_id 是历史内部编号。 */
export type LoginSearch = NonNullable<operations["list_login_logs"]["parameters"]["query"]>;

/** 日志列表每页最多 100 条（07），传输与路由校验共用此上限。 */
export const AUDIT_PAGE_LIMIT = 100;
/** opaque 游标最长 512 字符（07），不在客户端解码其内部结构。 */
export const AUDIT_CURSOR_MAX_CHARS = 512;
/** H1 共同保留期下界，单位天。 */
export const AUDIT_MIN_RETENTION_DAYS = 7;
/** H1 共同保留期上界，单位天。 */
export const AUDIT_MAX_RETENTION_DAYS = 365;

/** 请求超时 10 秒（毫秒），与账号页面一致；超时不证明写操作已回滚。 */
export const AUDIT_TIMEOUT_MS = 10000;
/** 日志立即过期且离页释放缓存（毫秒），避免账号切换后看到旧管理员内容。 */
export const AUDIT_STALE_TIME_MS = 0;
/** 日志缓存不在离页后保留（毫秒），不写 localStorage/sessionStorage。 */
export const AUDIT_GC_TIME_MS = 0;

/**
 * 按类型化筛选读取操作日志的一页。
 * @param _input - 账号感知客户端、OperationSearch payload 和取消信号；操作人 account_id 与对象 target_account_id 独立可选，编号与游标按原文本发送。
 * @returns GET /api/audit/operations 的时间/编号倒序页；末页 next_cursor=null，允许空页。
 * @throws Error 网络、超时、取消、401/403/422/其他服务错误，由 toFailureView/DiagnosticCard 显示；401 先统一清缓存和去登录。
 * @sideEffects 一次同源 GET；参数以生成类型传给 openapi-fetch，客户端来自 useAccountClient，不读取 cookie 或保存原始 fetch 的 this。
 * @timeSemantics 上限 AUDIT_TIMEOUT_MS，结合调用方 AbortSignal；不重试，取消后忽略迟到结果。
 */
export function listOperationLogs(_input: AccountCall<OperationSearch>): Promise<OperationLogPage> {
  return boundedRequest(_input.signal, AUDIT_TIMEOUT_MS, async (signal) => {
    const response = await _input.client.GET("/api/audit/operations", {
      params: { query: _input.payload },
      signal,
    });
    return page(response.data);
  });
}

/**
 * 按类型化筛选读取登录日志的一页。
 * @param _input - 已鉴权客户端、LoginSearch 和取消信号；不发送任何密码或未知登录名原文。
 * @returns GET /api/audit/logins 的倒序页，含未知账号、删除标记和可空来源 IP。
 * @throws Error 网络/取消/超时或服务端失败；权限不足保留统一诊断，不能把 502 当未登录。
 * @sideEffects 一次 GET，无自动翻页、全量拉取、凭据持久化或浏览器原生方法缓存。
 * @timeSemantics 10 秒上限，遵守取消信号并丢弃迟到结果，无轮询或重试。
 */
export function listLoginLogs(_input: AccountCall<LoginSearch>): Promise<LoginLogPage> {
  return boundedRequest(_input.signal, AUDIT_TIMEOUT_MS, async (signal) => {
    const response = await _input.client.GET("/api/audit/logins", {
      params: { query: _input.payload },
      signal,
    });
    return page(response.data);
  });
}

/**
 * 读取操作日志页面的共同保留期。
 * @param _input - 账号感知客户端、undefined payload 和取消信号。
 * @returns GET /api/audit/retention 的 days；数据库未设置时服务端返回 30，不在前端猜默认值。
 * @throws Error 401/403/网络/其他服务错误交统一诊断；读取失败不显示可提交的伪默认值。
 * @sideEffects 一次 GET，仅内存缓存，不修改 URL。
 * @timeSemantics 最多 AUDIT_TIMEOUT_MS，无重试；离页取消请求并忽略迟到结果。
 */
export function getAuditRetention(_input: AccountCall): Promise<AuditRetention> {
  return boundedRequest(_input.signal, AUDIT_TIMEOUT_MS, async (signal) => {
    const response = await _input.client.GET("/api/audit/retention", { signal });
    return retention(response.data);
  });
}

/**
 * 管理员保存两种日志共用的保留期。
 * @param _input - 账号感知客户端、严格整数 days（7-365 天）及取消信号。
 * @returns PUT /api/audit/retention 的已提交 days，不在客户端伪造成功。
 * @throws Error 参数/权限/写入/超时等失败经 DiagnosticCard；超时保持不确定状态，不能声称回滚。
 * @sideEffects 一次同源 PUT，浏览器带 Origin；成功由调用方失效保留期和操作日志查询，失败保留表单。不直接清除日志或读取 cookie。
 * @timeSemantics 10 秒上限，无自动重试；页面禁用重复提交，取消不保证服务器停止。
 */
export function setAuditRetention(_input: AccountCall<AuditRetention>): Promise<AuditRetention> {
  return boundedRequest(_input.signal, AUDIT_TIMEOUT_MS, async (signal) => {
    const response = await _input.client.PUT("/api/audit/retention", {
      body: retention(_input.payload),
      signal,
    });
    return retention(response.data);
  });
}

// 响应类型生成不能替代运行时的基本形状检查；错误正文统一交既有诊断视图。
function page<T extends OperationLogPage | LoginLogPage>(data: T | undefined): T {
  if (
    !data ||
    !Array.isArray(data.items) ||
    data.items.length > AUDIT_PAGE_LIMIT ||
    !(
      data.next_cursor === null ||
      (typeof data.next_cursor === "string" && data.next_cursor.length <= AUDIT_CURSOR_MAX_CHARS)
    ) ||
    !data.items.every(
      (item: unknown) =>
        item !== null &&
        typeof item === "object" &&
        "log_id" in item &&
        typeof item.log_id === "string" &&
        "occurred_at" in item &&
        typeof item.occurred_at === "string",
    )
  )
    throw new Error("请求失败", { cause: toFailureView(null) });
  return data;
}
function retention(data: AuditRetention | undefined): AuditRetention {
  if (
    !data ||
    !Number.isInteger(data.days) ||
    data.days < AUDIT_MIN_RETENTION_DAYS ||
    data.days > AUDIT_MAX_RETENTION_DAYS
  )
    throw new Error("请求失败", { cause: toFailureView(null) });
  return data;
}
