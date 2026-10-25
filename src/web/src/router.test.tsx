// 工单 02 的公开边界测试；传输显式注入，缓存和 DOM 在测试结束时清理。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { account } from "./accounts/testSupport";

afterEach(cleanup);

it("验证契约：代码式路由树在登录后将 / 映射到健康页面", async () => {
  const { router: applicationRouter, createAppRouter } = await import("./router");
  const originalHistory = applicationRouter.history;
  const originalState = applicationRouter.state;
  // 独立工厂同时隔离路由、传输和查询缓存，不能复用闭包绑定到另一实例的路由树。
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createAppRouter({
    queryClient,
    fetchImpl: (request) =>
      Promise.resolve(
        Response.json(
          new URL(request.url).pathname === "/api/auth/me" ? account : { status: "ok" },
        ),
      ),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  try {
    await router.load();
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("后端正常")).toBeTruthy();
    expect(router.state.location.pathname).toBe("/");
  } finally {
    cleanup();
    queryClient.clear();
  }
  expect(applicationRouter.history).toBe(originalHistory);
  expect(applicationRouter.state).toBe(originalState);
});
