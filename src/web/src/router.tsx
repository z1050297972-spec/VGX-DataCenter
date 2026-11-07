// 应用路由入口：所有页面除登录外先鉴权；请求客户端与内存缓存按应用实例隔离。
import { QueryClient } from "@tanstack/react-query";
import {
  createRootRoute,
  lazyRouteComponent,
  createRoute,
  createRouter,
  Outlet,
  useLocation,
  notFound,
  type RouterHistory,
} from "@tanstack/react-router";
import { Result } from "antd";
// M1-04：鉴权外壳和轻量首页保持同步，业务页面按路由加载，离开页面时立即释放查询。
import { AccountLayout, AccountsPage, LoginPage, PasswordPage } from "./accounts/Pages";
import { JobCardsProvider } from "./jobs/Cards";
import { AccountClientProvider } from "./accounts/runtime";
import {
  ADMINISTRATOR_PAGE_PATHS,
  guardAccountRoute,
  handleUnauthorized,
} from "./accounts/navigation";
const LoginLogsPage = lazyRouteComponent(() => import("./audit/Pages"), "LoginLogsPage");
const OperationLogsPage = lazyRouteComponent(() => import("./audit/Pages"), "OperationLogsPage");
import { validateLoginSearch, validateOperationSearch } from "./audit/search";
import type { LoginSearch, OperationSearch } from "./api/audit";
import { createAccountClient } from "./api/accounts";
import { defaultFetch, type FetchImplementation } from "./api/client";
import { toFailureView } from "./api/problems";
import { DiagnosticCard } from "./DiagnosticCard";
import { HealthPage } from "./HealthPage";
const SchedulingPage = lazyRouteComponent(() => import("./scheduling/Pages"), "SchedulingPage");
import { validateDownloadSearch } from "./downloads/search";
const DownloadPage = lazyRouteComponent(() => import("./downloads/Pages"), "DownloadPage");
const MonitoringPage = lazyRouteComponent(() => import("./monitoring/Pages"), "MonitoringPage");
const JobsPage = lazyRouteComponent(() => import("./jobs/Pages"), "JobsPage");
const JobDetailPage = lazyRouteComponent(() => import("./jobs/Pages"), "JobDetailPage");
import type { JobSearch } from "./api/jobs";
import { validateJobSearch } from "./jobs/search";
import { validateDatasetSearch } from "./datasets/search";
import { validateCreationSearch } from "./datasets/creationState";
const DatasetsPage = lazyRouteComponent(() => import("./datasets/Pages"), "DatasetsPage");
const CreateLinkPage = lazyRouteComponent(
  () => import("./datasets/CreationPages"),
  "CreateLinkPage",
);
const CreateDatasetPage = lazyRouteComponent(
  () => import("./datasets/CreationPages"),
  "CreateDatasetPage",
);
const StorageRootsPage = lazyRouteComponent(() => import("./storage/Pages"), "StorageRootsPage");
const NavigationRecoveryPage = lazyRouteComponent(
  () => import("./navigation/Pages"),
  "NavigationRecoveryPage",
);

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
 * @returns TanStack Router 实例；含所有登录账号可访问的只读 /scheduling；未登记页面及非法作业编号显示前端404，同实例所有 API 401 共用清理和 replace 导航。
 * @throws 无；创建不发请求，导航失败由诊断视图呈现。
 * @sideEffects 导航前核验身份；仅登录页公开，服务器仍独立鉴权；不保存浏览器凭据。调度路由为单一只读页，不定义 search 参数。
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
    notFoundComponent: () => <Result status="404" title="404" subTitle="页面不存在" />,
    component: function RootShell() {
      const pathname = useLocation({ select: (location) => location.pathname });
      return (
        <AccountClientProvider client={client}>
          {pathname === "/login" ? (
            <Outlet />
          ) : (
            <JobCardsProvider>
              <AccountLayout />
            </JobCardsProvider>
          )}
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
  const downloads = createRoute({
    getParentRoute: () => root,
    path: "/downloads",
    validateSearch: validateDownloadSearch,
    component: DownloadPage,
  });
  const monitoring = createRoute({
    getParentRoute: () => root,
    path: "/monitoring",
    component: MonitoringPage,
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
    beforeLoad: ({ params }) => {
      // 作业编号必须是正十进制文本；避免已删除的静态入口落入详情并发送无效 API 请求。
      if (!/^[1-9][0-9]*$/u.test(params.jobId)) notFound({ throw: true });
    },
    component: JobDetailPage,
  });
  const scheduling = createRoute({
    getParentRoute: () => root,
    path: "/scheduling",
    component: SchedulingPage,
  });
  const storageRoots = createRoute({
    getParentRoute: () => root,
    path: "/storage-roots",
    component: StorageRootsPage,
  });
  const navigationRecovery = createRoute({
    getParentRoute: () => root,
    path: "/navigation/recovery",
    component: NavigationRecoveryPage,
  });
  const datasets = createRoute({
    getParentRoute: () => root,
    path: "/datasets",
    validateSearch: validateDatasetSearch,
    component: DatasetsPage,
  });
  const createLink = createRoute({
    getParentRoute: () => root,
    path: "/datasets/links/new",
    validateSearch: validateCreationSearch,
    component: CreateLinkPage,
  });
  const createDataset = createRoute({
    getParentRoute: () => root,
    path: "/datasets/new",
    validateSearch: validateCreationSearch,
    component: CreateDatasetPage,
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
      downloads,
      monitoring,
      jobDetail,
      scheduling,
      storageRoots,
      datasets,
      createLink,
      createDataset,
      navigationRecovery,
    ]),
    history: options.history,
    defaultPreload: false,
  });
  return instance;
}

// 作业 URL 错误保留页面表单；具体字段校验集中在 validateJobSearch。
function jobSearch(_search: Record<string, unknown>): JobSearch & { invalidJobSearch?: true } {
  try {
    return validateJobSearch(_search);
  } catch {
    return { invalidJobSearch: true };
  }
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
