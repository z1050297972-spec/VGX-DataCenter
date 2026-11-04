// 账号 HTTP 边界（06）：仅使用生成类型和统一 openapi-fetch；不把秘密放 URL、日志或持久缓存。
import { boundedRequest } from "./_request";
import type { FetchImplementation, HealthClient } from "./client";
import { createHealthClient } from "./client";
import type { components } from "./schema";
import { toFailureView } from "./problems";
import apiSchema from "./openapi.json";

/** 新密码最小字符数，取后端 PASSWORD_MIN_CHARS 生成的约束，避免提示与服务端校验漂移。 */
export const PASSWORD_MIN_CHARS =
  apiSchema.components.schemas.ChangePasswordRequest.properties.new_password.minLength;
/** 新密码最大字符数，与最小长度共用后端生成的同一字段约束。 */
export const PASSWORD_MAX_CHARS =
  apiSchema.components.schemas.ChangePasswordRequest.properties.new_password.maxLength;

/** 安全账号快照；编号为文本，禁止 Number 转换以免丢失 64 位精度。 */
export type Account = components["schemas"]["AccountResponse"];
/** 一页账号列表。 */
export type AccountList = components["schemas"]["AccountListResponse"];
/** 登录请求，只在内存里使用。 */
export type LoginInput = components["schemas"]["LoginRequest"];
/** 本人改密请求，只在内存里使用。 */
export type PasswordInput = components["schemas"]["ChangePasswordRequest"];
/** 管理员建号请求。 */
export type NewAccountInput = components["schemas"]["CreateAccountRequest"];
/** 角色变更请求。 */
export type RoleInput = components["schemas"]["RoleRequest"];
/** 状态变更请求。 */
export type StatusInput = components["schemas"]["StatusRequest"];
/** 重置密码请求，只在内存里使用。 */
export type ResetInput = components["schemas"]["ResetPasswordRequest"];

/** 交互请求上限 10 秒，单位毫秒；超时只能说明客户端未收到结果，不证明服务器回滚。 */
export const ACCOUNT_TIMEOUT_MS = 10000;
/** 身份快照立即失效，跨页面重新读取；单位毫秒，避免持久缓存旧角色。 */
export const ACCOUNT_STALE_TIME_MS = 0;
/** 账号查询离开页面即清理，单位毫秒，避免登出后残留敏感视图。 */
export const ACCOUNT_GC_TIME_MS = 0;

/** 客户端装配参数，不使用隐式全局 fetch 或浏览器持久存储。 */
export interface AccountClientOptions {
  /** 注入的传输函数，必填、无单位、无默认，沿用现有客户端边界。 */
  fetchImpl: FetchImplementation;
  /** 任意接口 401 时统一调用一次，必填；导航层负责清缓存、去登录页和防重定向循环。 */
  onUnauthorized: () => void;
}

/** 单次请求上下文，payload 的服务器字段全部来自生成类型。 */
export interface AccountCall<T = undefined> {
  /** 已装配统一失败/401 处理的客户端，必填、无默认。 */
  client: HealthClient;
  /** 请求载荷，必填；无 body 的操作明确传 undefined，不作为 query 使用秘密。 */
  payload: T;
  /** 取消信号，必填；与 ACCOUNT_TIMEOUT_MS 联合控制，卸载时取消。 */
  signal: AbortSignal;
}

/** 管理员指定目标的请求上下文。 */
export interface TargetAccountCall<T = undefined> extends AccountCall<T> {
  /** 规范正整数十进制字符串，最大 2^63-1；必填，禁止浮点编号。 */
  accountId: Account["account_id"];
}

/** 分页参数；URL 中只记录游标，不记录密码。 */
export interface ListAccountCall extends AccountCall {
  /** 0 或规范账号编号文本；必填，首页为 "0"。 */
  afterId: string;
}

/**
 * 装配所有 API 共用的账号感知客户端。
 *
 * @param options - 必填传输与 401 回调，字段见 AccountClientOptions。
 * @returns 独立的相对路径客户端；同源 credentials=same-origin，先观察原始 HTTP 状态再交 createProblemFetch。
 * @throws 无；创建本身不发请求。返回客户端的失败由既有安全 Error.cause 表达。
 * @sideEffects 每次传输仅一次；任何 API 的 401（即使 body 非法）先通知 onUnauthorized，再保留安全失败供登录页显示；429 保留 problem 和安全 Retry-After。创建不读 cookie、不改全局 fetch。
 * @timeSemantics 同步构造；请求取消/10 秒超时由调用函数负责，不自动重试。
 */
export function createAccountClient(options: AccountClientOptions): HealthClient {
  const { fetchImpl } = options;
  return createHealthClient(async (...args) => {
    const response = await fetchImpl(...args);
    if (response.status === 401) options.onUnauthorized();
    return response;
  });
}

/**
 * 提交登录凭据并读取身份。
 *
 * @param input - 客户端、仅内存的登录载荷和取消信号。
 * @returns POST /api/auth/login 的 200 Account；浏览器保存 HttpOnly cookie，代码不读取 Set-Cookie。
 * @throws Error 网络、超时、取消、401/403/422/429/502 或其他失败，沿用 toFailureView；429 只展示 G2 的安全倒计时；Argon2 容量不足的 502 显示资源繁忙，不自动重试。
 * @sideEffects 一次 POST；不把密码放 query、localStorage、日志或 Query 缓存；表单秘密由调用页面在成功和失败后清空。
 * @timeSemantics 最多 ACCOUNT_TIMEOUT_MS 毫秒；失败不自动重试，取消不保证服务端撤销。
 */
export function login(input: AccountCall<LoginInput>): Promise<Account> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/auth/login", { body: input.payload, signal });
    return required(result.data);
  });
}

/**
 * 退出当前会话。
 *
 * @param input - 已认证客户端、undefined payload 和取消信号。
 * @returns POST /api/auth/logout 的 204，无数据；401 也统一清理本地身份。
 * @throws Error 其他失败经 toFailureView 显示，不能把网络失败伪装为服务端登出成功。
 * @sideEffects 一次 POST；cookie 由服务器删除；成功或 401 后的清缓存和导航由 AccountMenu 与统一导航边界负责。
 * @timeSemantics 10 秒上限，无重试；等待期间的重复点击由页面禁用。
 */
export function logout(input: AccountCall): Promise<void> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/auth/logout", { signal });
    if (result.response.status !== 204) throw new Error("请求失败", { cause: toFailureView(null) });
  });
}

/**
 * 读取当前身份与必须改密标志。
 *
 * @param input - 客户端、undefined payload、取消信号。
 * @returns GET /api/auth/me 的 200 Account。
 * @throws Error 401 统一跳登录，其他失败保留诊断；不把 502 当匿名身份。
 * @sideEffects 一次调用发一次 GET；内存身份缓存、staleTime/gcTime=0 和 refetchOnWindowFocus:true 由 AccountLayout/AccountMenu 的查询配置负责。
 * @timeSemantics 10 秒上限；遵守传入的 AbortSignal，忽略取消后的迟到结果；路由等待与窗口聚焦重查由调用方负责。
 */
export function fetchCurrentAccount(input: AccountCall): Promise<Account> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const result = await input.client.GET("/api/auth/me", { signal });
    return required(result.data);
  });
}

/**
 * 本人改密码并刷新身份。
 *
 * @param input - 当前和新密码只在 payload 内存中，不接受目标编号。
 * @returns POST /api/auth/password 的 200 Account，must_change_password=False；浏览器接收轮换 cookie。
 * @throws Error 经 toFailureView；当前密码错误以 400 显示“当前密码不正确”，保留身份和当前页；第五次起 429。真实会话失效的 401 仍统一跳登录，不输出原文或自动重试。
 * @sideEffects 一次 POST；服务器使旧会话全部作废；两份密码清理与身份缓存失效由改密页面负责。
 * @timeSemantics 10 秒上限，写请求不自动重试。
 */
export function changePassword(input: AccountCall<PasswordInput>): Promise<Account> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/auth/password", { body: input.payload, signal });
    return required(result.data);
  });
}

/**
 * 按游标读取管理员账号列表。
 *
 * @param input - afterId 为规范十进制字符串，客户端和取消信号必填。
 * @returns GET /api/accounts?after_id=... 的有序一页，最多 100 项；next_after_id=null 表示末页。
 * @throws Error 401 跳登录，403 显示权限诊断，其他失败用 DiagnosticCard。
 * @sideEffects 一次 GET，不把编号转 Number；不全量拉取列表。
 * @timeSemantics 10 秒上限；遵守传入信号并忽略取消后结果；旧分页请求由账号管理页取消，无轮询。
 */
export function listAccounts(input: ListAccountCall): Promise<AccountList> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const result = await input.client.GET("/api/accounts", {
      params: { query: { after_id: input.afterId } },
      signal,
    });
    return required(result.data);
  });
}

/**
 * 管理员提交新账号。
 *
 * @param input - 生成类型的新建载荷、客户端和取消信号。
 * @returns POST /api/accounts 的 201 Account，必须首次改密。
 * @throws Error 409 登录名冲突及其他失败统一显示 DiagnosticCard，不回显初始密码。
 * @sideEffects 一次 POST；列表失效和结束后的密码清理由账号管理页负责，本函数不持久缓存请求。
 * @timeSemantics 10 秒上限，无自动重试；账号管理页负责禁止重复提交。
 */
export function createAccount(input: AccountCall<NewAccountInput>): Promise<Account> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/accounts", { body: input.payload, signal });
    return required(result.data);
  });
}

/**
 * 管理员修改目标角色。
 *
 * @param input - 目标编号文本、生成的 role 载荷、客户端和信号。
 * @returns PATCH /api/accounts/{account_id}/role 的 200 Account。
 * @throws Error 最后管理员 409、无权限 403 等以 DiagnosticCard 显示。
 * @sideEffects 一次 PATCH；服务器可能撤销目标会话；列表及当前身份的刷新由账号管理页负责。
 * @timeSemantics 10 秒上限，不乐观确认、不自动重试。
 */
export function setAccountRole(input: TargetAccountCall<RoleInput>): Promise<Account> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const result = await input.client.PATCH("/api/accounts/{account_id}/role", {
      body: input.payload,
      params: { path: { account_id: input.accountId } },
      signal,
    });
    return required(result.data);
  });
}

/**
 * 管理员启用或停用目标账号。
 *
 * @param input - 目标编号文本和 status 载荷；停用须由页面完成二次确认。
 * @returns PATCH /api/accounts/{account_id}/status 的 200 Account。
 * @throws Error 409/403/其他失败统一诊断。
 * @sideEffects 一次 PATCH；停用使目标全部会话失效；列表刷新和二次确认由账号管理页负责，不能替代服务端不变量。
 * @timeSemantics 10 秒上限，不自动重试。
 */
export function setAccountStatus(input: TargetAccountCall<StatusInput>): Promise<Account> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const result = await input.client.PATCH("/api/accounts/{account_id}/status", {
      body: input.payload,
      params: { path: { account_id: input.accountId } },
      signal,
    });
    return required(result.data);
  });
}

/**
 * 管理员重置目标密码。
 *
 * @param input - 目标编号文本、新 SecretStr 对应的请求文本、客户端和信号。
 * @returns POST /api/accounts/{account_id}/password 的 200 Account，必须改密。
 * @throws Error 404/403/其他失败经 DiagnosticCard，不泄漏密码。
 * @sideEffects 一次 POST；列表失效和结束后的秘密清理由账号管理页负责；不显示或复制服务端哈希。
 * @timeSemantics 10 秒上限，不自动重试。
 */
export function resetAccountPassword(input: TargetAccountCall<ResetInput>): Promise<Account> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/accounts/{account_id}/password", {
      body: input.payload,
      params: { path: { account_id: input.accountId } },
      signal,
    });
    return required(result.data);
  });
}

/**
 * 管理员删除已二次确认的目标账号。
 *
 * @param input - 目标编号文本、undefined payload、客户端和信号。
 * @returns DELETE /api/accounts/{account_id} 的 204，无数据。
 * @throws Error 最后管理员 409、目标已删 404、无权限 403 等用 DiagnosticCard，保留列表。
 * @sideEffects 一次 DELETE；账号管理页在成功后才使列表查询失效，不乐观删除。
 * @timeSemantics 10 秒上限，不自动重试；超时后的状态确认由账号管理页重新查询。
 */
export function deleteAccount(input: TargetAccountCall): Promise<void> {
  return boundedRequest(input.signal, ACCOUNT_TIMEOUT_MS, async (signal) => {
    const result = await input.client.DELETE("/api/accounts/{account_id}", {
      params: { path: { account_id: input.accountId } },
      signal,
    });
    if (result.response.status !== 204) throw new Error("请求失败", { cause: toFailureView(null) });
  });
}

function required<T>(data: T | undefined): T {
  if (data === undefined || data === null)
    throw new Error("请求失败", { cause: toFailureView(null) });
  return data;
}
