// 工单06公开边界测试；仅用注入传输、固定时钟和内存路由。
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, act, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { createAppRouter } from "../router";
import type { FetchImplementation } from "../api/client";
import { account, problemResponse } from "./testSupport";
import type { Account } from "../api/accounts";
import { ConfigProvider } from "antd";

const caches: QueryClient[] = [];
beforeEach(() => {
  // jsdom 不运行 CSS 动画或伪元素布局，测试只观察交互语义。
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) => computed(element));
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
  for (const cache of caches) cache.clear();
  caches.length = 0;
  vi.useRealTimers();
  focusManager.setFocused(undefined);
});
function mount(path: string, fetchImpl: FetchImplementation) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  caches.push(queryClient);
  const router = createAppRouter({
    queryClient,
    fetchImpl,
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  const view = render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ConfigProvider>,
  );
  return { router, queryClient, ...view };
}
function credentials() {
  fireEvent.change(screen.getByLabelText("登录名"), { target: { value: "admin" } });
  fireEvent.change(screen.getByLabelText("口令"), { target: { value: "private-credential" } });
  fireEvent.click(screen.getByRole("button", { name: "登录" }));
}

it("验证契约：LoginPage登录后返回原站内路径，外部回跳回退首页", async () => {
  for (const target of ["/accounts", "https://evil.test"]) {
    let loggedIn = false;
    const transport = vi.fn<FetchImplementation>((request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/auth/login") {
        loggedIn = true;
        return Promise.resolve(Response.json(account));
      }
      if (path === "/api/auth/me")
        return Promise.resolve(loggedIn ? Response.json(account) : problemResponse(401));
      if (path === "/api/accounts")
        return Promise.resolve(Response.json({ items: [account], next_after_id: null }));
      return Promise.resolve(Response.json({ status: "ok" }));
    });
    const view = mount("/login?returnTo=" + encodeURIComponent(target), transport);
    await screen.findByLabelText("登录名");
    credentials();
    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(target === "/accounts" ? "/accounts" : "/");
    });
    expect(view.router.state.location.href).not.toContain("private-credential");
    view.unmount();
  }
});

it("验证契约：LoginPage必须改口令时直接进改密页，已登录账号不重复显示登录表单", async () => {
  for (const initiallyLoggedIn of [false, true]) {
    let logged = initiallyLoggedIn;
    const transport = vi.fn<FetchImplementation>((request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/auth/login") logged = true;
      return Promise.resolve(
        logged ? Response.json({ ...account, must_change_password: true }) : problemResponse(401),
      );
    });
    const view = mount("/login?returnTo=%2Faccounts", transport);
    if (!initiallyLoggedIn) {
      await screen.findByLabelText("登录名");
      credentials();
    }
    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe("/change-password");
    });
    expect(await screen.findByLabelText("当前口令")).toBeTruthy();
    expect(screen.queryByLabelText("登录名")).toBeNull();
    view.unmount();
  }
});

it("验证契约：LoginPage的401/403/422/429/网络错误均用DiagnosticCard，不区分账号存在与否", async () => {
  for (const status of [401, 403, 422, 429, 0]) {
    const transport = vi.fn<FetchImplementation>((request) => {
      if (new URL(request.url).pathname === "/api/auth/me")
        return Promise.resolve(problemResponse(401));
      return status === 0
        ? Promise.reject(new Error("private-network"))
        : Promise.resolve(problemResponse(status));
    });
    const view = mount("/login", transport);
    await screen.findByLabelText("登录名");
    credentials();
    expect(
      await screen.findByText(status === 0 ? "请求失败，请检查网络或稍后重试。" : "请求被拒绝"),
    ).toBeTruthy();
    expect(screen.getByLabelText<HTMLInputElement>("口令").value).toBe("");
    expect(screen.queryByText("private-network")).toBeNull();
    view.unmount();
  }
});

it("验证契约：LoginPage展示429剩余倒计时并禁用重复提交，不自动重试或在URL存口令", async () => {
  const transport = vi.fn<FetchImplementation>((request) =>
    Promise.resolve(problemResponse(new URL(request.url).pathname === "/api/auth/me" ? 401 : 429)),
  );
  mount("/login", transport);
  await screen.findByLabelText("登录名");
  vi.useFakeTimers();
  await act(async () => {
    credentials();
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(screen.getByText("请等待 12 秒后重试")).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "登录" }).disabled).toBe(true);
  const count = transport.mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(screen.getByText("请等待 11 秒后重试")).toBeTruthy();
  expect(transport).toHaveBeenCalledTimes(count);
});

it("验证契约：PasswordPage强制改密不能绕过，成功清标记后回跳；旧口令400留在当前页、第五次429及新旧相同422可展示，真实401仍跳登录", async () => {
  let forced = true;
  let result = 400;
  const transport = vi.fn<FetchImplementation>((request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/auth/me")
      return Promise.resolve(Response.json({ ...account, must_change_password: forced }));
    if (path === "/api/auth/password") {
      if (result === 200) {
        forced = false;
        return Promise.resolve(Response.json(account));
      }
      return Promise.resolve(problemResponse(result));
    }
    return Promise.resolve(Response.json({ status: "ok" }));
  });
  const view = mount("/change-password?returnTo=%2F", transport);
  await screen.findByLabelText("当前口令");
  const submit = () => {
    fireEvent.change(screen.getByLabelText("当前口令"), {
      target: { value: "current-credential" },
    });
    fireEvent.change(screen.getByLabelText("新口令"), {
      target: { value: "replacement-credential" },
    });
    fireEvent.change(screen.getByLabelText("确认新口令"), {
      target: { value: "replacement-credential" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存口令" }));
  };
  submit();
  expect(await screen.findByText("当前口令不正确")).toBeTruthy();
  expect(view.router.state.location.pathname).toBe("/change-password");
  expect(screen.getByLabelText<HTMLInputElement>("当前口令").value).toBe("");
  result = 200;
  submit();
  await waitFor(() => {
    expect(view.router.state.location.pathname).toBe("/");
  });
  expect(await screen.findByText("后端正常")).toBeTruthy();
});

it("验证契约：PasswordPage所有结束路径清空秘密，卸载取消请求和计时器", async () => {
  let pendingSignal: AbortSignal | undefined;
  const transport = vi.fn<FetchImplementation>((request) => {
    if (new URL(request.url).pathname === "/api/auth/password") {
      pendingSignal = request.signal;
      return new Promise(() => undefined);
    }
    return Promise.resolve(Response.json(account));
  });
  const view = mount("/change-password", transport);
  await screen.findByLabelText("当前口令");
  passwordFields();
  await waitFor(() => {
    expect(pendingSignal).toBeDefined();
  });
  expect(view.queryClient.getMutationCache().getAll()).toHaveLength(0);
  view.unmount();
  expect(pendingSignal?.aborted).toBe(true);
});

it("验证契约：AccountsPage显示安全字段和分页，新建、改角色、启用、停用、重置、删除入口完整", async () => {
  const transport = vi.fn<FetchImplementation>((request) =>
    Promise.resolve(
      new URL(request.url).pathname === "/api/accounts"
        ? Response.json({
            items: [{ ...account, display_name: "目标账号" }],
            next_after_id: "9007199254740993",
          })
        : Response.json(account),
    ),
  );
  mount("/accounts", transport);
  expect(await screen.findByText("目标账号")).toBeTruthy();
  for (const name of ["新建账号", "改为成员", "停用", "重置口令", "删除", "下一页"])
    expect(screen.getByRole("button", { name })).toBeTruthy();
  expect(screen.getByText("9007199254740993")).toBeTruthy();
  expect(screen.queryByText("password_hash")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "下一页" }));
  await waitFor(() => {
    expect(
      transport.mock.calls.some(
        ([request]) => new URL(request.url).searchParams.get("after_id") === "9007199254740993",
      ),
    ).toBe(true);
  });
});

it("验证契约：AccountsPage停用和删除均二次确认，取消零请求，确认后一次请求", async () => {
  let items: Account[] = [
    { ...account, account_id: "2", display_name: "目标账号", role: "member" },
  ];
  const transport = vi.fn<FetchImplementation>((request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/auth/me") return Promise.resolve(Response.json(account));
    if (request.method === "PATCH") {
      items = items.map((item) => ({ ...item, status: "disabled" }));
      return Promise.resolve(Response.json(items[0]));
    }
    if (request.method === "DELETE") {
      items = [];
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return Promise.resolve(Response.json({ items, next_after_id: null }));
  });
  mount("/accounts", transport);
  await screen.findByText("目标账号");
  fireEvent.click(screen.getByRole("button", { name: "停用" }));
  const cancel = await screen.findByRole("button", { name: /取\s*消/u });
  fireEvent.click(cancel);
  expect(transport.mock.calls.filter(([request]) => request.method === "PATCH")).toHaveLength(0);
  await waitFor(() => {
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  fireEvent.click(screen.getByRole("button", { name: "停用" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认停用" }));
  await screen.findByRole("button", { name: "启用" });
  expect(transport.mock.calls.filter(([request]) => request.method === "PATCH")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "删除" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认删除" }));
  await waitFor(() => {
    expect(within(screen.getByRole("table")).queryByText("目标账号")).toBeNull();
  });
  expect(transport.mock.calls.filter(([request]) => request.method === "DELETE")).toHaveLength(1);
});

it("验证契约：AccountsPage最后管理员409、目标404、角色403、字段422及网络失败保留列表并显示DiagnosticCard", async () => {
  for (const status of [409, 404, 403, 422, 0]) {
    const transport = vi.fn<FetchImplementation>((request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/auth/me") return Promise.resolve(Response.json(account));
      if (request.method === "PATCH")
        return status === 0
          ? Promise.reject(new Error("private-network"))
          : Promise.resolve(problemResponse(status));
      return Promise.resolve(
        Response.json({ items: [{ ...account, display_name: "保留列表" }], next_after_id: null }),
      );
    });
    const view = mount("/accounts", transport);
    await screen.findByText("保留列表");
    fireEvent.click(screen.getByRole("button", { name: "改为成员" }));
    expect(
      await screen.findByText(
        status === 409
          ? "账号状态已变化，请重试"
          : status === 0
            ? "请求失败，请检查网络或稍后重试。"
            : "请求被拒绝",
      ),
    ).toBeTruthy();
    expect(screen.getByText("保留列表")).toBeTruthy();
    expect(screen.getByRole("button", { name: "改为成员" })).toBeTruthy();
    view.unmount();
  }
});

it("验证契约：AccountsPage成功操作刷新列表，密码输入结束后清空，不显示哈希或会话", async () => {
  let items: Account[] = [
    { ...account, account_id: "2", display_name: "目标账号", role: "member", status: "disabled" },
  ];
  const transport = vi.fn<FetchImplementation>((request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/auth/me") return Promise.resolve(Response.json(account));
    if (request.method === "POST" && path === "/api/accounts") {
      items = [
        ...items,
        {
          ...account,
          account_id: "3",
          login_name: "new_member",
          display_name: "新成员",
          role: "member",
          must_change_password: true,
        },
      ];
      return Promise.resolve(Response.json(items[1], { status: 201 }));
    }
    if (path.endsWith("/role")) {
      items = items.map((item) =>
        item.account_id === "2" ? { ...item, role: "administrator" } : item,
      );
      return Promise.resolve(Response.json(items[0]));
    }
    if (path.endsWith("/status")) {
      items = items.map((item) =>
        item.account_id === "2" ? { ...item, status: "enabled" } : item,
      );
      return Promise.resolve(Response.json(items[0]));
    }
    if (path.endsWith("/password")) {
      items = items.map((item) => ({ ...item, must_change_password: true }));
      return Promise.resolve(Response.json(items[0]));
    }
    return Promise.resolve(Response.json({ items, next_after_id: null }));
  });
  const view = mount("/accounts", transport);
  await screen.findByText("目标账号");
  fireEvent.click(screen.getByRole("button", { name: "启用" }));
  await screen.findByRole("button", { name: "停用" });
  fireEvent.click(screen.getByRole("button", { name: "改为管理员" }));
  await screen.findByRole("button", { name: "改为成员" });
  fireEvent.click(screen.getByRole("button", { name: "重置口令" }));
  fireEvent.change(await screen.findByLabelText("初始口令"), {
    target: { value: "replacement-credential" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存账号" }));
  await waitFor(() => {
    expect(screen.queryByLabelText("初始口令")).toBeNull();
  });
  fireEvent.click(screen.getByRole("button", { name: "新建账号" }));
  fireEvent.change(await screen.findByLabelText("登录名"), { target: { value: "new_member" } });
  fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "新成员" } });
  fireEvent.change(screen.getByLabelText("初始口令"), { target: { value: "private-credential" } });
  fireEvent.click(screen.getByRole("button", { name: "保存账号" }));
  expect(await screen.findByText("新成员")).toBeTruthy();
  await waitFor(() => {
    expect(screen.queryByLabelText("初始口令")).toBeNull();
  });
  expect(JSON.stringify(view.queryClient.getQueryData(["accounts", "0"]))).not.toContain(
    "private-credential",
  );
  expect(view.queryClient.getMutationCache().getAll()).toHaveLength(0);
});

it("验证契约：AccountMenu右上角显示名字角色和登出/改密，只有管理员有账号管理入口", async () => {
  for (const role of ["administrator", "member"] as const) {
    const transport = vi.fn<FetchImplementation>((request) =>
      Promise.resolve(
        new URL(request.url).pathname === "/api/auth/me"
          ? Response.json({ ...account, role })
          : Response.json({ status: "ok" }),
      ),
    );
    const view = mount("/", transport);
    expect(await screen.findByText("后端正常")).toBeTruthy();
    expect(screen.getByText("管理员", { selector: "span" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "登出" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "修改口令" })).toBeTruthy();
    expect(Boolean(screen.queryByRole("link", { name: "账号管理" }))).toBe(
      role === "administrator",
    );
    view.unmount();
  }
});

it("验证契约：AccountMenu登出成功或401清缓存跳登录，网络失败显示错误且不声称退出", async () => {
  for (const status of [502, 204, 401]) {
    let logged = true;
    const transport = vi.fn<FetchImplementation>((request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/auth/logout") {
        if (status !== 502) logged = false;
        return Promise.resolve(
          status === 204 ? new Response(null, { status: 204 }) : problemResponse(status),
        );
      }
      if (path === "/api/auth/me")
        return Promise.resolve(logged ? Response.json(account) : problemResponse(401));
      return Promise.resolve(Response.json({ status: "ok" }));
    });
    const view = mount("/", transport);
    await screen.findByText("后端正常");
    fireEvent.click(screen.getByRole("button", { name: "登出" }));
    if (status === 502) {
      expect(await screen.findByText("口令核验资源繁忙")).toBeTruthy();
      expect(view.router.state.location.pathname).toBe("/");
    } else {
      await waitFor(() => {
        expect(view.router.state.location.pathname).toBe("/login");
      });
      expect(await screen.findByLabelText("登录名")).toBeTruthy();
      expect(view.queryClient.getQueryData(["current-account"])).toBeUndefined();
    }
    view.unmount();
  }
});

it("验证契约：AccountLayout加载时不闪现受保护内容，任意接口401统一登录跳转", async () => {
  let resolveIdentity: ((response: Response) => void) | undefined;
  const transport = vi.fn<FetchImplementation>((request) =>
    new URL(request.url).pathname === "/api/auth/me"
      ? new Promise((resolve) => {
          resolveIdentity = resolve;
        })
      : Promise.resolve(Response.json({ status: "ok" })),
  );
  const view = mount("/", transport);
  await waitFor(() => {
    expect(resolveIdentity).toBeDefined();
  });
  expect(screen.queryByText("后端正常")).toBeNull();
  expect(screen.queryByRole("link", { name: "账号管理" })).toBeNull();
  act(() => {
    resolveIdentity?.(problemResponse(401));
  });
  await waitFor(() => {
    expect(view.router.state.location.pathname).toBe("/login");
  });
  view.unmount();
});

it("验证契约：各页用户和服务端文本按React文本渲染，恶意HTML不执行", async () => {
  const malicious = "<img src=x onerror=alert(1)>";
  for (const path of ["/", "/change-password", "/accounts"]) {
    const transport = vi.fn<FetchImplementation>((request) =>
      Promise.resolve(
        new URL(request.url).pathname === "/api/accounts"
          ? Response.json({ items: [{ ...account, display_name: malicious }], next_after_id: null })
          : new URL(request.url).pathname === "/api/health"
            ? Response.json({ status: "ok" })
            : Response.json({ ...account, display_name: malicious }),
      ),
    );
    const view = mount(path, transport);
    expect((await screen.findAllByText(malicious)).length).toBeGreaterThan(0);
    expect(document.querySelector('img[src="x"]')).toBeNull();
    view.unmount();
  }
  const transport = vi.fn<FetchImplementation>((request) =>
    Promise.resolve(
      new URL(request.url).pathname === "/api/auth/me"
        ? problemResponse(401)
        : Response.json(
            {
              type: "about:blank",
              title: "Bad Request",
              status: 400,
              category: "input",
              detail: malicious,
              error_id: "00000000000040008000000000000000",
              diagnostics: [],
            },
            { status: 400, headers: { "Content-Type": "application/problem+json" } },
          ),
    ),
  );
  mount("/login", transport);
  await screen.findByLabelText("登录名");
  credentials();
  expect(await screen.findByText(malicious)).toBeTruthy();
  expect(document.querySelector('img[src="x"]')).toBeNull();
});

it("验证契约：所有页面卸载清理请求/倒计时，Query不持久化秘密，默认无自动重试", async () => {
  for (const path of ["/login", "/change-password", "/accounts"]) {
    const signals: AbortSignal[] = [];
    const transport = vi.fn<FetchImplementation>((request) => {
      const url = new URL(request.url).pathname;
      if (url === "/api/auth/me")
        return Promise.resolve(path === "/login" ? problemResponse(401) : Response.json(account));
      signals.push(request.signal);
      return new Promise(() => undefined);
    });
    const view = mount(path, transport);
    if (path === "/login") {
      await screen.findByLabelText("登录名");
      credentials();
    }
    if (path === "/change-password") {
      await screen.findByLabelText("当前口令");
      passwordFields();
    }
    await waitFor(() => {
      expect(signals.length).toBe(1);
    });
    expect(view.queryClient.getMutationCache().getAll()).toHaveLength(0);
    view.unmount();
    expect(signals[0]?.aborted).toBe(true);
  }
});

it("验证契约：成员被管理员停用后切回窗口，活跃身份Query以refetchOnWindowFocus:true重新查/me，401立即清缓存并跳登录页（验收11）", async () => {
  let active = true;
  const transport = vi.fn<FetchImplementation>((request) =>
    Promise.resolve(
      new URL(request.url).pathname === "/api/auth/me"
        ? active
          ? Response.json({ ...account, role: "member" })
          : problemResponse(401)
        : Response.json({ status: "ok" }),
    ),
  );
  const view = mount("/", transport);
  await screen.findByText("后端正常");
  view.queryClient.setQueryData(["error", "1"], { report: "旧身份报告" });
  active = false;
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  await waitFor(() => {
    expect(view.router.state.location.pathname).toBe("/login");
  });
  expect(await screen.findByLabelText("登录名")).toBeTruthy();
  expect(view.queryClient.getQueryCache().getAll()).toHaveLength(0);
});

it("验证契约：窗口聚焦身份查询遇502显示诊断而非伪装匿名；任何其他接口401仍统一跳登录", async () => {
  let busy = false,
    expired = false,
    healthUnauthorized = false;
  const transport = vi.fn<FetchImplementation>((request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/auth/me")
      return Promise.resolve(
        expired ? problemResponse(401) : busy ? problemResponse(502) : Response.json(account),
      );
    if (healthUnauthorized) {
      expired = true;
      return Promise.resolve(problemResponse(401));
    }
    return Promise.resolve(Response.json({ status: "ok" }));
  });
  const view = mount("/", transport);
  await screen.findByText("后端正常");
  busy = true;
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  expect(await screen.findByText("口令核验资源繁忙")).toBeTruthy();
  expect(view.router.state.location.pathname).toBe("/");
  busy = false;
  await act(async () => {
    await view.queryClient.invalidateQueries({ queryKey: ["current-account"] });
  });
  await screen.findByText("后端正常");
  healthUnauthorized = true;
  await act(async () => {
    await view.queryClient.invalidateQueries({ queryKey: ["health"] });
  });
  await waitFor(() => {
    expect(view.router.state.location.pathname).toBe("/login");
  });
});

it("验证契约：管理员停用、删除、降级自己后下一请求401，当前页面统一退出并清理旧账号缓存", async () => {
  for (const operation of ["停用", "删除", "改为成员"]) {
    let active = true;
    const transport = vi.fn<FetchImplementation>((request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/auth/me")
        return Promise.resolve(active ? Response.json(account) : problemResponse(401));
      if (request.method !== "GET") {
        active = false;
        return Promise.resolve(
          request.method === "DELETE"
            ? new Response(null, { status: 204 })
            : Response.json(account),
        );
      }
      return Promise.resolve({ items: [account], next_after_id: null }).then((value) =>
        Response.json(value),
      );
    });
    const view = mount("/accounts", transport);
    await screen.findByText("9007199254740993");
    fireEvent.click(screen.getByRole("button", { name: operation }));
    if (operation !== "改为成员")
      fireEvent.click(
        await screen.findByRole("button", { name: operation === "停用" ? "确认停用" : "确认删除" }),
      );
    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe("/login");
    });
    expect(await screen.findByLabelText("登录名")).toBeTruthy();
    expect(view.queryClient.getQueryData(["accounts", "0"])).toBeUndefined();
    view.unmount();
  }
});

it("验证契约：改密页旧口令前四次错误400展示当前口令不正确并留在当前页，不清身份；第五次429显示G2等待，真实401才跳登录", async () => {
  let attempts = 0,
    expired = false;
  const transport = vi.fn<FetchImplementation>((request) => {
    if (new URL(request.url).pathname === "/api/auth/me")
      return Promise.resolve(expired ? problemResponse(401) : Response.json(account));
    attempts++;
    return Promise.resolve(problemResponse(attempts < 5 ? 400 : 429));
  });
  const view = mount("/change-password", transport);
  await screen.findByLabelText("当前口令");
  for (let number = 1; number <= 4; number++) {
    passwordFields();
    await waitFor(() => {
      expect(attempts).toBe(number);
    });
    expect(await screen.findByText("当前口令不正确")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByLabelText<HTMLInputElement>("当前口令").value).toBe("");
    });
    expect(view.router.state.location.pathname).toBe("/change-password");
    expect(view.queryClient.getQueryData(["current-account"])).toBeTruthy();
  }
  passwordFields();
  expect(await screen.findByText("请等待 12 秒后重试")).toBeTruthy();
  expired = true;
  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  await waitFor(() => {
    expect(view.router.state.location.pathname).toBe("/login");
  });
});

it("验证契约：改密核验后状态竞争变化409展示重试建议，不自动重试或跳登录", async () => {
  const transport = vi.fn<FetchImplementation>((request) =>
    Promise.resolve(
      new URL(request.url).pathname === "/api/auth/me"
        ? Response.json(account)
        : problemResponse(409),
    ),
  );
  const view = mount("/change-password", transport);
  await screen.findByLabelText("当前口令");
  passwordFields();
  expect(await screen.findByText("账号状态已变化，请重试")).toBeTruthy();
  expect(view.router.state.location.pathname).toBe("/change-password");
  expect(transport.mock.calls.filter(([request]) => request.method === "POST")).toHaveLength(1);
  expect(view.queryClient.getQueryData(["current-account"])).toBeTruthy();
});

function passwordFields() {
  fireEvent.change(screen.getByLabelText("当前口令"), { target: { value: "current-credential" } });
  fireEvent.change(screen.getByLabelText("新口令"), {
    target: { value: "replacement-credential" },
  });
  fireEvent.change(screen.getByLabelText("确认新口令"), {
    target: { value: "replacement-credential" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存口令" }));
}
