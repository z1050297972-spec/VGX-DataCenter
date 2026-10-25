// 路由入口（ADR 0002、工单 02），代码式树仅提供 /，不使用文件路由插件。
import { createRootRoute, createRoute, createRouter, Outlet } from "@tanstack/react-router";
import { AccountsPage, LoginPage, PasswordPage } from "./accounts/Pages";
import { HealthPage } from "./HealthPage";

const rootRoute = createRootRoute({ component: Outlet });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HealthPage,
});
// 06 骨架仅登记占位页；实现阶段给根布局/受保护路由接入 guardAccountRoute，当前健康页行为不变。
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginPage,
});
const passwordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/change-password",
  component: PasswordPage,
});
const accountsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/accounts",
  component: AccountsPage,
});
const routeTree = rootRoute.addChildren([indexRoute, loginRoute, passwordRoute, accountsRoute]);

/** 应用唯一的路由实例，浏览器地址仍由 TanStack Router 管理。 */
export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
