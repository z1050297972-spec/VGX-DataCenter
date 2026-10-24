// 工单 02 的公开边界测试；传输显式注入，缓存和 DOM 在测试结束时清理。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createHealthClient, type FetchImplementation } from "./api/client";
import { HealthPage } from "./HealthPage";

const queryClients: QueryClient[] = [];

function queryClient() {
  const client = new QueryClient();
  queryClients.push(client);
  return client;
}

afterEach(() => {
  cleanup();
  for (const client of queryClients.splice(0)) client.clear();
});

it("验证契约：React Testing Library 渲染成功页面显示后端正常", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json({ status: "ok" }));
  render(
    <QueryClientProvider client={queryClient()}>
      <HealthPage client={createHealthClient(transport)} />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("后端正常")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(transport).toHaveBeenCalledTimes(1);
  expect(transport.mock.calls[0]?.[0].url).toBe(new URL("/api/health", location.href).href);
});

it("验证契约：React Testing Library 渲染失败页面显示 Alert 且无成功提示", async () => {
  const transport = vi.fn<FetchImplementation>().mockRejectedValue(new Error("后端离线"));
  render(
    <QueryClientProvider client={queryClient()}>
      <HealthPage client={createHealthClient(transport)} />
    </QueryClientProvider>,
  );
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("请求失败");
  expect(screen.queryByText("后端正常")).toBeNull();
});

it("验证契约：加载中显示提示，不提前显示成功", () => {
  const transport = vi.fn<FetchImplementation>(
    (request) =>
      new Promise<Response>((_resolve, reject) => {
        request.signal.addEventListener(
          "abort",
          () => {
            reject(new Error("测试结束"));
          },
          { once: true },
        );
      }),
  );
  render(
    <QueryClientProvider client={queryClient()}>
      <HealthPage client={createHealthClient(transport)} />
    </QueryClientProvider>,
  );
  expect(screen.getByText("正在检查后端…")).toBeTruthy();
  expect(screen.queryByText("后端正常")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("验证契约：默认客户端跨重渲染稳定且页面不修改 URL", () => {
  const cache = queryClient();
  // 不触碰默认 fetch：关闭本测试的网络执行，通过公开查询缓存观察客户端身份是否稳定。
  cache.setDefaultOptions({ queries: { enabled: false } });
  const initialUrl = location.href;
  const page = render(
    <QueryClientProvider client={cache}>
      <HealthPage />
    </QueryClientProvider>,
  );
  expect(cache.getQueryCache().getAll()).toHaveLength(1);
  page.rerender(
    <QueryClientProvider client={cache}>
      <HealthPage />
    </QueryClientProvider>,
  );
  expect(cache.getQueryCache().getAll()).toHaveLength(1);
  expect(location.href).toBe(initialUrl);
});

it.skip("验证契约：派工 B 用 DiagnosticCard 替代 Alert 权宜，四类problem按契约展示且不保留成功提示", () => {
  // 本轮只列迁移清单，保留 HealthPage 已实现的行为。
});

it.skip("验证契约：派工 B 的fetchHealth透传统一Error，网络断开和代理HTML经toFailureView显示固定文案", () => {
  // 本轮只列迁移清单，保留 HealthPage 已实现的行为。
});

it.skip("验证契约：派工 B 移除HealthPage的Alert导入及权宜注释，成功加载缓存超时行为保持第2张契约", () => {
  // 本轮只列迁移清单，保留 HealthPage 已实现的行为。
});
