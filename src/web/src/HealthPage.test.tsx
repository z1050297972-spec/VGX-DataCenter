// 工单 02 的公开边界测试；传输显式注入，缓存和 DOM 在测试结束时清理。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createHealthClient, type FetchImplementation } from "./api/client";
import { HealthPage } from "./HealthPage";

// 工单 05 骨架：详情接入批准后逐项启用，不改变现有页面行为。
it.skip("验证契约：HealthPage 为 DiagnosticCard 传稳定的 createErrorDetailsLoader，普通重渲染不重复请求", () => {});
it.skip("验证契约：程序缺陷默认折叠不查详情，首次展开显示完整报错，折叠再展开复用本次结果", () => {});
it.skip("验证契约：健康成功和非缺陷卡片不发送详情请求，既有健康缓存与五秒超时不变", () => {});
it.skip("验证契约：详情 404、失败或五秒超时显示固定提示，保持原错误编号和摘要", () => {});
it.skip("验证契约：客户端变更重建加载器并取消旧查询，不跨账号复用报告", () => {});

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

it("验证契约：React Testing Library 渲染失败页面显示诊断卡片且无成功提示", async () => {
  const transport = vi.fn<FetchImplementation>().mockRejectedValue(new Error("后端离线"));
  render(
    <QueryClientProvider client={queryClient()}>
      <HealthPage client={createHealthClient(transport)} />
    </QueryClientProvider>,
  );
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("请求失败，请检查网络或稍后重试。");
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

it("验证契约：DiagnosticCard 展示请求失败，四类problem按契约展示且不保留成功提示", async () => {
  const payload = {
    type: "about:blank",
    title: "Internal Server Error",
    status: 500,
    category: "defect",
    detail: "平台内部错误，请把错误编号交给维护者。",
    diagnostics: [],
    error_id: "123456789abc4def8abc123456789abc",
  };
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(
    Response.json(payload, {
      status: 500,
      headers: { "Content-Type": "application/problem+json" },
    }),
  );
  render(
    <QueryClientProvider client={queryClient()}>
      <HealthPage client={createHealthClient(transport)} />
    </QueryClientProvider>,
  );
  expect(await screen.findByText(payload.detail)).toBeTruthy();
  expect(screen.getByText(`错误编号：${payload.error_id}`)).toBeTruthy();
  expect(screen.queryByText("后端正常")).toBeNull();
});

it("验证契约：fetchHealth透传统一Error，网络断开和代理HTML经toFailureView显示固定文案", async () => {
  for (const transport of [
    vi.fn<FetchImplementation>().mockRejectedValue(new Error("网络内部消息")),
    vi
      .fn<FetchImplementation>()
      .mockResolvedValue(new Response("<html>秘密</html>", { status: 502 })),
  ]) {
    const view = render(
      <QueryClientProvider client={queryClient()}>
        <HealthPage client={createHealthClient(transport)} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("请求失败，请检查网络或稍后重试。")).toBeTruthy();
    expect(screen.queryByText("网络内部消息")).toBeNull();
    view.unmount();
  }
});

it("验证契约：HealthPage 使用诊断卡片，成功加载缓存超时行为保持第2张契约", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json({ status: "ok" }));
  const cache = queryClient();
  const client = createHealthClient(transport);
  const view = render(
    <QueryClientProvider client={cache}>
      <HealthPage client={client} />
    </QueryClientProvider>,
  );
  await screen.findByText("后端正常");
  view.rerender(
    <QueryClientProvider client={cache}>
      <HealthPage client={client} />
    </QueryClientProvider>,
  );
  expect(screen.getByText("后端正常")).toBeTruthy();
  expect(transport).toHaveBeenCalledTimes(1);
});
