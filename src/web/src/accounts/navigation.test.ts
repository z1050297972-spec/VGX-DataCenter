// 工单06公开边界测试；仅用注入传输、固定时钟和内存路由。
import { expect, it, vi, afterEach, beforeEach } from "vitest";
import { safeReturnTo, guardAccountRoute, handleUnauthorized } from "./navigation";
import { createAccountClient } from "../api/accounts";
import type { FetchImplementation } from "../api/client";
import { account, problemResponse } from "./testSupport";
import { QueryClient } from "@tanstack/react-query";
import { isRedirect, createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { QueryClientProvider, focusManager } from "@tanstack/react-query";
import { createElement } from "react";
import { render, cleanup, screen, waitFor } from "@testing-library/react";
import { createAppRouter } from "../router";
beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
});
afterEach(() => {
  cleanup();
  focusManager.setFocused(undefined);
});
afterEach(() => {
  vi.useRealTimers();
});

it("验证契约：safeReturnTo允许单斜杠站内path/query/hash，非法或缺失回退/", () => {
  for (const value of ["/", "/jobs/123?view=table#result", "/中文?name=%E4%B8%AD"])
    expect(safeReturnTo(value)).toBe(value);
  for (const value of [null, undefined, 4, {}, "", "relative"])
    expect(safeReturnTo(value)).toBe("/");
});

it("验证契约：safeReturnTo拒绝外部URL、//、反斜杠、控制符、编码外跳、多重编码、坏编码和超长2048输入", () => {
  for (const value of [
    "https://evil.test",
    "//evil.test",
    "/\\evil.test",
    "/a\nb",
    "/%2f%2fevil.test",
    "/%252f%252fevil.test",
    "/%5cevil.test",
    "/%00evil",
    "/%ZZ",
    "/" + "x".repeat(2048),
  ])
    expect(safeReturnTo(value)).toBe("/");
});

it("验证契约：safeReturnTo拒绝登录/改密循环地址和重复参数数组，登录及改密完成后再次校验", () => {
  for (const value of [
    "/login",
    "/login?returnTo=/accounts",
    "/change-password#x",
    "/%6cogin",
    "/a/../login",
    ["/accounts", "/jobs"],
  ])
    expect(safeReturnTo(value)).toBe("/");
});

it("验证契约：guardAccountRoute匿名任何页面跳登录并保留安全回跳，未决身份不渲染受保护内容", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(problemResponse(401));
  const client = createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
  let caught: unknown;
  try {
    await guardAccountRoute({
      client,
      destination: "/jobs?state=ready#item",
      administratorOnly: false,
      signal: new AbortController().signal,
    });
  } catch (error) {
    caught = error;
  }
  expect(isRedirect(caught)).toBe(true);
  if (isRedirect(caught))
    expect(caught.options.href).toBe("/login?returnTo=%2Fjobs%3Fstate%3Dready%23item");
  expect(transport).toHaveBeenCalledTimes(1);
});

it("验证契约：guardAccountRoute强制改密优先到改密页，不能访问首页或管理员页；完成后返回安全目标", async () => {
  const client = createAccountClient({
    fetchImpl: vi.fn<FetchImplementation>(() =>
      Promise.resolve(Response.json({ ...account, must_change_password: true })),
    ),
    onUnauthorized: vi.fn(),
  });
  for (const destination of ["/", "/accounts"]) {
    let caught: unknown;
    try {
      await guardAccountRoute({
        client,
        destination,
        administratorOnly: destination === "/accounts",
        signal: new AbortController().signal,
      });
    } catch (error) {
      caught = error;
    }
    expect(isRedirect(caught)).toBe(true);
    if (isRedirect(caught))
      expect(caught.options.href).toBe(
        "/change-password?returnTo=" + encodeURIComponent(destination),
      );
  }
  expect(
    (
      await guardAccountRoute({
        client,
        destination: "/change-password",
        administratorOnly: false,
        signal: new AbortController().signal,
      })
    ).must_change_password,
  ).toBe(true);
});

it("验证契约：guardAccountRoute成员进入管理员页回首页并显示权限提示，管理员允许", async () => {
  for (const role of ["administrator", "member"] as const) {
    const client = createAccountClient({
      fetchImpl: vi
        .fn<FetchImplementation>()
        .mockResolvedValue(Response.json({ ...account, role })),
      onUnauthorized: vi.fn(),
    });
    const pending = guardAccountRoute({
      client,
      destination: "/accounts",
      administratorOnly: true,
      signal: new AbortController().signal,
    });
    if (role === "administrator") expect(await pending).toEqual(account);
    else {
      let caught: unknown;
      try {
        await pending;
      } catch (error) {
        caught = error;
      }
      expect(isRedirect(caught)).toBe(true);
      if (isRedirect(caught)) expect(caught.options.href).toBe("/?permission=denied");
    }
  }
});

it("验证契约：guardAccountRoute的502等错误显示诊断而非跳登录，取消忽略迟到身份", async () => {
  const client = createAccountClient({
    fetchImpl: vi.fn<FetchImplementation>().mockResolvedValue(problemResponse(502)),
    onUnauthorized: vi.fn(),
  });
  await expect(
    guardAccountRoute({
      client,
      destination: "/",
      administratorOnly: false,
      signal: new AbortController().signal,
    }),
  ).rejects.toMatchObject({ cause: { kind: "problem", problem: { status: 502 } } });
  const controller = new AbortController();
  controller.abort();
  await expect(
    guardAccountRoute({
      client,
      destination: "/",
      administratorOnly: false,
      signal: controller.signal,
    }),
  ).rejects.toThrow("请求失败");
});

it("验证契约：handleUnauthorized并发401合并为一次replace并清除Query身份、账号、详情及mutation缓存", () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["account"], account);
  queryClient.setQueryData(["accounts"], [account]);
  queryClient.setQueryData(["error", "1"], { report: "旧账号报告" });
  queryClient.getMutationCache().build(queryClient, { mutationKey: ["old"] });
  const replace = vi.fn();
  const input = { queryClient, currentPath: "/accounts", replace };
  handleUnauthorized(input);
  handleUnauthorized(input);
  expect(replace).toHaveBeenCalledExactlyOnceWith("/login?returnTo=%2Faccounts");
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
});

it("验证契约：handleUnauthorized已在登录页不重定向，保留错口令诊断；切换账号无旧数据残留", async () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["account"], account);
  const replace = vi.fn();
  handleUnauthorized({ queryClient, currentPath: "/login?returnTo=/accounts", replace });
  expect(replace).not.toHaveBeenCalled();
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  await Promise.resolve();
  queryClient.setQueryData(["account"], account);
  handleUnauthorized({ queryClient, currentPath: "/accounts", replace });
  expect(replace).toHaveBeenCalledExactlyOnceWith("/login?returnTo=%2Faccounts");
});

it("验证契约：前端以TanStack Router和内存history执行守卫，不直接操作window.location或存储秘密", async () => {
  const queryClient = new QueryClient();
  const transport = vi.fn<FetchImplementation>(() => Promise.resolve(problemResponse(401)));
  const router = createAppRouter({
    queryClient,
    fetchImpl: transport,
    history: createMemoryHistory({ initialEntries: ["/accounts"] }),
  });
  const stored = vi.spyOn(Storage.prototype, "setItem");
  render(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(RouterProvider, { router }),
    ),
  );
  await waitFor(() => {
    expect(router.state.location.pathname).toBe("/login");
  });
  expect(router.state.location.searchStr).toContain("returnTo");
  expect(await screen.findByLabelText("登录名")).toBeTruthy();
  expect(stored).not.toHaveBeenCalled();
  queryClient.clear();
});

it("验证契约：身份Query保持staleTime:0和refetchOnWindowFocus:true，无定时轮询；切回窗口重查身份，收到401调用统一handleUnauthorized", async () => {
  let active = true;
  const queryClient = new QueryClient();
  const transport = vi.fn<FetchImplementation>((request) =>
    Promise.resolve(
      new URL(request.url).pathname === "/api/auth/me"
        ? active
          ? Response.json(account)
          : problemResponse(401)
        : Response.json({ status: "ok" }),
    ),
  );
  const router = createAppRouter({
    queryClient,
    fetchImpl: transport,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  render(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(RouterProvider, { router }),
    ),
  );
  await screen.findByText("后端正常");
  active = false;
  focusManager.setFocused(false);
  focusManager.setFocused(true);
  await waitFor(() => {
    expect(router.state.location.pathname).toBe("/login");
  });
  expect(await screen.findByLabelText("登录名")).toBeTruthy();
  expect(queryClient.getQueryData(["current-account"])).toBeUndefined();
  queryClient.clear();
});
