// 应用路由入口：所有页面除登录外先鉴权；请求客户端与内存缓存按应用实例隔离。
import { QueryClient } from "@tanstack/react-query";
import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  useLocation,
  type RouterHistory,
} from "@tanstack/react-router";
import { AccountLayout, AccountsPage, LoginPage, PasswordPage } from "./accounts/Pages";
import { AccountClientProvider } from "./accounts/runtime";
import {
  ADMINISTRATOR_PAGE_PATHS,
  guardAccountRoute,
  handleUnauthorized,
} from "./accounts/navigation";
import { LoginLogsPage, OperationLogsPage } from "./audit/Pages";
import { validateLoginSearch, validateOperationSearch } from "./audit/search";
import type { LoginSearch, OperationSearch } from "./api/audit";
import { createAccountClient } from "./api/accounts";
import { defaultFetch, type FetchImplementation } from "./api/client";
import { toFailureView } from "./api/problems";
import { DiagnosticCard } from "./DiagnosticCard";
import { HealthPage } from "./HealthPage";
import { JobsPage, JobDetailPage, SubmitCountJobPage } from "./jobs/Pages";
import type { JobSearch } from "./api/jobs";

/** 路由装配输入；测试使用内存 history 与注入传输，不启动服务器。 */
interface AppRouterOptions {
  /** 当前应用内存查询缓存，必填。 */
  queryClient: QueryClient;
  /** 同源 HTTP 传输，必填。 */
  fetchImpl: FetchImplementation;
  /** 浏览器默认 history；测试可提供内存 history。 */
  history?: RouterHistory;
}
/**
 * 创建独立、默认需要登录的应用路由。
 * @param options - 缓存、传输和可选 history，无秘密。
 * @returns TanStack Router 实例；同实例所有 API 401 共用清理和 replace 导航。
 * @throws 无；创建不发请求，导航失败由诊断视图呈现。
 * @sideEffects 导航前核验身份；仅登录页公开，服务器仍独立鉴权；不保存浏览器凭据。
 * @timeSemantics 每次导航使用守卫的取消信号，身份聚焦查询由布局负责，无自动重试。
 */
export function createAppRouter(options: AppRouterOptions) {
  const client = createAccountClient({
    fetchImpl: options.fetchImpl,
    onUnauthorized: () => {
      handleUnauthorized({
        queryClient: options.queryClient,
        currentPath: instance.state.location.href,
        replace: (path) => {
          void instance.navigate({ href: path, replace: true });
        },
      });
    },
  });
  const root = createRootRoute({
    component: function RootShell() {
      const pathname = useLocation({ select: (location) => location.pathname });
      return (
        <AccountClientProvider client={client}>
          {pathname === "/login" ? <Outlet /> : <AccountLayout />}
        </AccountClientProvider>
      );
    },
    beforeLoad: async ({ location, abortController }) => {
      if (location.pathname !== "/login")
        await guardAccountRoute({
          client,
          destination: location.href,
          administratorOnly: ADMINISTRATOR_PAGE_PATHS.has(location.pathname),
          signal: abortController.signal,
        });
    },
    errorComponent: ({ error }) => <DiagnosticCard failure={toFailureView(error)} />,
  });
  const index = createRoute({
    getParentRoute: () => root,
    path: "/",
    component: () => <HealthPage client={client} />,
  });
  const login = createRoute({ getParentRoute: () => root, path: "/login", component: LoginPage });
  const password = createRoute({
    getParentRoute: () => root,
    path: "/change-password",
    component: PasswordPage,
  });
  const accounts = createRoute({
    getParentRoute: () => root,
    path: "/accounts",
    component: AccountsPage,
  });
  const operationLogs = createRoute({
    getParentRoute: () => root,
    path: "/audit/operations",
    validateSearch: (search): OperationSearch & { invalidAuditSearch?: true } =>
      auditSearch(() => validateOperationSearch(search)),
    component: OperationLogsPage,
  });
  const loginLogs = createRoute({
    getParentRoute: () => root,
    path: "/audit/logins",
    validateSearch: (search): LoginSearch & { invalidAuditSearch?: true } =>
      auditSearch(() => validateLoginSearch(search)),
    component: LoginLogsPage,
  });
  const jobs = createRoute({
    getParentRoute: () => root,
    path: "/jobs",
    validateSearch: (search): JobSearch & { invalidJobSearch?: true } => jobSearch(search),
    component: JobsPage,
  });
  const jobDetail = createRoute({
    getParentRoute: () => root,
    path: "/jobs/$jobId",
    component: JobDetailPage,
  });
  const submitCount = createRoute({
    getParentRoute: () => root,
    path: "/jobs/new",
    component: SubmitCountJobPage,
  });
  const instance = createRouter({
    routeTree: root.addChildren([
      index,
      login,
      password,
      accounts,
      operationLogs,
      loginLogs,
      jobs,
      jobDetail,
      submitCount,
    ]),
    history: options.history,
    defaultPreload: false,
  });
  return instance;
}

// 作业 URL 错误保留页面表单；具体字段校验集中在 validateJobSearch。
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
function jobSearch(_search: Record<string, unknown>): JobSearch & { invalidJobSearch?: true } {
  throw new Error("未实现");
}

// 校验错误属于可修正的筛选输入，不触发根路由失败；不保留或回显原始坏参数。
function auditSearch<T>(validate: () => T): T | { invalidAuditSearch: true } {
  try {
    return validate();
  } catch {
    return { invalidAuditSearch: true };
  }
}

/** 页面应用的唯一内存缓存，不持久化任何查询或 mutation。 */
export const appQueryClient = new QueryClient();
/** 浏览器路由实例；测试通过 createAppRouter 创建隔离实例。 */
export const router = createAppRouter({ queryClient: appQueryClient, fetchImpl: defaultFetch });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
