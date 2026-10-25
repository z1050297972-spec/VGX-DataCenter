// 账号导航规则（06），只负责站内回跳和权限路由，不读写 cookie 或浏览器持久存储。
import { redirect } from "@tanstack/react-router";
import { fetchCurrentAccount } from "../api/accounts";
import { toFailureView } from "../api/problems";
import type { HealthClient } from "../api/client";
import type { Account } from "../api/accounts";
import type { QueryClient } from "@tanstack/react-query";

/** 路由守卫的可注入输入，真实导航由 TanStack Router 完成，测试用内存 history。 */
export interface AccountGuardInput {
  /** 类型化客户端，必填、无默认。 */
  client: HealthClient;
  /** 当前 pathname+search+hash，必填；不得包含 origin 或凭据。 */
  destination: string;
  /** 管理员页面为 true，普通页面 false；必填。 */
  administratorOnly: boolean;
  /** 路由加载的取消信号，必填。 */
  signal: AbortSignal;
}

/** 统一未登录跳转的依赖，禁止硬编码 window.location 造成测试不可控。 */
export interface UnauthorizedNavigation {
  /** 当前查询缓存，必填；账号切换时清空旧身份、列表及报错详情。 */
  queryClient: QueryClient;
  /** 当前站内位置，必填；登录页自身不作为回跳地址。 */
  currentPath: string;
  /** 用 TanStack Router replace 执行站内跳转；必填，不接受外部 URL。 */
  replace: (path: string) => void;
}

/**
 * 校验登录后的站内回跳目标。
 *
 * @param value - 未信任的 search 参数，允许任意值、undefined 或重复参数数组。
 * @returns 仅以单个 / 开头的站内 pathname+query+hash；拒绝协议相对、反斜杠、控制字符、编码后外跳、
 * 外部协议、登录/改密循环地址、长度超过 2048 或非法编码，回退 /；不执行或记录输入。
 * @throws 无。恶意和畸形目标一律安全回退。
 * @sideEffects 无；不导航、不发请求、不写浏览器存储。
 * @timeSemantics 同步校验，无时钟或重试。
 */
export function safeReturnTo(value: unknown): string {
  if (typeof value !== "string" || value.length > 2048) return "/";
  let decoded = value;
  // 每次解码会缩短百分号转义；长度上界同时限制多重编码的工作量。
  for (let remaining = value.length + 1; remaining > 0; remaining--) {
    if (unsafePath(decoded)) return "/";
    try {
      const path = new URL(decoded, "http://rdp.invalid").pathname.replace(/\/$/u, "");
      if (path === "/login" || path === "/change-password") return "/";
      const next = decodeURIComponent(decoded);
      if (next === decoded) return value;
      decoded = next;
    } catch {
      return "/";
    }
  }
  return "/";
}

/**
 * 在受保护页面加载前核验身份、改密标记和角色。
 *
 * @param input - 路由守卫输入，字段见 AccountGuardInput。
 * @returns 已登录且满足页面权限的 Account；每次导航查 /api/auth/me，不把 502 当作未登录。
 * @throws TanStack Router redirect：401 去 /login?returnTo=安全目标；必须改密去 /change-password，
 * 保留安全回跳；成员访问 /accounts 去 / 并显示权限提示。其他 Error 交统一诊断视图。
 * @sideEffects 本次路由守卫最多一次身份 GET，不加载受保护页内容直到身份确定；进入页面后由布局的 refetchOnWindowFocus: true 身份 Query 负责切回窗口重查。路由取消则取消请求并忽略迟到结果。
 * @timeSemantics 使用 ACCOUNT_TIMEOUT_MS，不轮询、不重试；身份 staleTime 为 0。
 */
export function guardAccountRoute(input: AccountGuardInput): Promise<Account> {
  return fetchCurrentAccount({ client: input.client, payload: undefined, signal: input.signal })
    .then((account) => {
      const target = safeReturnTo(input.destination);
      if (
        account.must_change_password &&
        input.destination.split(/[?#]/u)[0] !== "/change-password"
      ) {
        routeRedirect("/change-password?returnTo=" + encodeURIComponent(target));
      }
      if (input.administratorOnly && account.role !== "administrator")
        routeRedirect("/?permission=denied");
      return account;
    })
    .catch((error: unknown) => {
      const failure = toFailureView(error);
      if (failure.kind === "problem" && failure.problem.status === 401) {
        routeRedirect("/login?returnTo=" + encodeURIComponent(safeReturnTo(input.destination)));
      }
      throw error;
    });
}

/**
 * 将任意接口的 401 汇合为一次清缓存和登录导航。
 *
 * @param input - 内存 QueryClient、当前位置和 replace 回调，不可缺失。
 * @returns 无；已经在登录页时不再次跳转，保留登录错误卡片；否则回跳目标经 safeReturnTo。
 * @throws 无。并发 401 合并，不把原始服务端异常作为导航参数。
 * @sideEffects 取消并清空所有旧账号查询和 mutation，防止切换账号后出现旧内容；使用 replace 导航，
 * 不读写 cookie/localStorage/sessionStorage。登录后的目的地和强制改密完成后的目标都重新校验。
 * @timeSemantics 同步请求导航；清理期间忽略迟到响应，不自动重试登录。
 */
export function handleUnauthorized(input: UnauthorizedNavigation): void {
  if (pendingNavigation.has(input.queryClient)) return;
  pendingNavigation.add(input.queryClient);
  try {
    void input.queryClient.cancelQueries().catch(() => undefined);
    input.queryClient.clear();
    if (input.currentPath.split(/[?#]/u)[0] !== "/login") {
      input.replace("/login?returnTo=" + encodeURIComponent(safeReturnTo(input.currentPath)));
    }
  } catch {
    /* 导航适配器失效也不能把异常或敏感位置带到页面。 */
  } finally {
    queueMicrotask(() => {
      pendingNavigation.delete(input.queryClient);
    });
  }
}

// 同一批未授权响应只导航一次；下一任务重新允许，避免新登录后永远不能退出。
const pendingNavigation = new WeakSet<QueryClient>();

// ASCII 控制字符按码元检测即可，不拆分或重写正常 Unicode 文本。
function unsafePath(value: string): boolean {
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return true;
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code < 32 || code === 127) return true;
  }
  return false;
}

// TanStack Router 用 Response 控制导航，不是供错误视图展示的异常。
function routeRedirect(href: string): never {
  // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router 要求抛出 redirect 返回的 Response 来中断页面加载。
  throw redirect({ href });
}
