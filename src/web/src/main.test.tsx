// 工单 02 的公开边界测试；传输显式注入，缓存和 DOM 在测试结束时清理。
import { act, screen } from "@testing-library/react";
import type { ClientOptions } from "openapi-fetch";
import * as ReactDOMClient from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { FetchImplementation } from "./api/client";
import type { paths } from "./api/schema";
import { mountWeb } from "./mountWeb";

const transport = vi.hoisted(() => vi.fn<FetchImplementation>());
vi.mock("react-dom/client", { spy: true });

// mountWeb 的批准签名不提供依赖参数，在第三方 HTTP 客户端边界注入传输，保留真实 React/路由。
// 生产工厂与 hook 都照常运行；不修改全局 fetch，也不向外发送请求。
vi.mock("openapi-fetch", async (importOriginal) => {
  const actual = await importOriginal<typeof import("openapi-fetch")>();
  return {
    ...actual,
    default: (options: ClientOptions) => actual.default<paths>({ ...options, fetch: transport }),
  };
});

it("验证契约：空容器同步报错且不挂载", () => {
  const before = document.body.innerHTML;
  expect(() => {
    mountWeb(null);
  }).toThrow(Error);
  expect(document.body.innerHTML).toBe(before);
});

it("验证契约：有效容器创建 React 根并提供查询和路由上下文", async () => {
  transport.mockImplementation(() => Promise.resolve(Response.json({ status: "ok" })));
  const container = document.createElement("div");
  document.body.append(container);
  // 只记录渲染器创建的资源以便释放，不替换渲染行为，不断言内部调用顺序。
  const rootSpy = vi.mocked(ReactDOMClient.createRoot);
  try {
    // 返回 Promise 让 act 等待路由与查询的异步提交。
    await act(() => {
      mountWeb(container);
      return Promise.resolve();
    });
    expect(await screen.findByText("后端正常")).toBeTruthy();
    expect(container.textContent).toContain("后端正常");
    expect(transport.mock.calls[0]?.[0].url).toBe(new URL("/api/health", location.href).href);
  } finally {
    await act(() => {
      for (const result of rootSpy.mock.results) {
        if (result.type === "return") result.value.unmount();
      }
      return Promise.resolve();
    });
    rootSpy.mockRestore();
    container.remove();
  }
});
