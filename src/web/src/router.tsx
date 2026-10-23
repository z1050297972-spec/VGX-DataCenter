// 路由入口（ADR 0002、工单 02），代码式树仅提供 /，不使用文件路由插件。
import { createRootRoute, createRoute, createRouter, Outlet } from "@tanstack/react-router";
import { HealthPage } from "./HealthPage";

const rootRoute = createRootRoute({ component: Outlet });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HealthPage,
});
const routeTree = rootRoute.addChildren([indexRoute]);

/** 应用唯一的路由实例，浏览器地址仍由 TanStack Router 管理。 */
export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
