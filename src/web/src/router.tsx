// 路由入口（ADR 0002、工单 02），代码式树仅提供 /，不使用文件路由插件。
import { createRootRoute, createRoute, createRouter, Outlet } from "@tanstack/react-router";
import { HealthPage } from "./HealthPage";

const rootRoute = createRootRoute({ component: Outlet });

/**
 * 返回首页所属的根路由。
 *
 * @param 无 - 无参数。
 * @returns 当前模块唯一的根路由，供 TanStack Router 建立父子关系。
 * @throws 无。
 * @sideEffects 无。
 * @timeSemantics 同步返回；路由树在模块初始化时构造，不读时钟。
 */
function getRootRoute(): typeof rootRoute {
  throw new Error("未实现");
}

const indexRoute = createRoute({ getParentRoute: getRootRoute, path: "/", component: HealthPage });
const routeTree = rootRoute.addChildren([indexRoute]);

/** 应用唯一的路由实例，浏览器地址仍由 TanStack Router 管理。 */
export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
