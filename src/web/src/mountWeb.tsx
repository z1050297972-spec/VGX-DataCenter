// 浏览器启动边界（工单 02）；只组装 React、QueryClientProvider 与 RouterProvider。
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { createRoot } from "react-dom/client";
import { appQueryClient, router } from "./router";

/**
 * 将应用挂载到页面容器。
 *
 * @param container - index.html 中的 root 元素，无单位；null 表示入口 HTML 不完整。
 * @returns 无。
 * @throws Error container 为 null 时同步报错，不尝试挂载。
 * @sideEffects 创建 React 根并绑定当前应用独立的 QueryClient，在容器内渲染路由；页面先确认身份，再发起业务请求。
 * @timeSemantics 每次页面加载只调用一次；健康缓存和超时遵循 useHealth，身份与写请求遵循账号页面契约。
 */
export function mountWeb(container: HTMLElement | null): void {
  if (container === null) {
    throw new Error("缺少页面挂载容器 root");
  }
  createRoot(container).render(
    <QueryClientProvider client={appQueryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}
