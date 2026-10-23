// 工单 02 的公开边界测试；传输显式注入，缓存和 DOM 在测试结束时清理。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

afterEach(cleanup);

it("验证契约：代码式路由树将 / 映射到健康页面", async () => {
  const { router: applicationRouter } = await import("./router");
  const originalHistory = applicationRouter.history;
  const originalState = applicationRouter.state;
  // 共享路由定义，测试单独持有路由实例及内存历史，不改模块单例的状态。
  const router = createRouter({
    routeTree: applicationRouter.routeTree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { enabled: false } } });
  try {
    await router.load();
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("正在检查后端…")).toBeTruthy();
    expect(router.state.location.pathname).toBe("/");
  } finally {
    cleanup();
    queryClient.clear();
  }
  expect(applicationRouter.history).toBe(originalHistory);
  expect(applicationRouter.state).toBe(originalState);
});
