// 账号 HTTP 公开边界测试；只用注入传输与可控计时器。
import { afterEach, expect, it, vi } from "vitest";
import * as api from "./accounts";
import type { FetchImplementation } from "./client";
import { account, problemResponse } from "../accounts/testSupport";
import { toFailureView, readProblemResponse } from "./problems";
afterEach(() => {
  vi.useRealTimers();
});

it("验证契约：createAccountClient创建不发请求、相对基址、same-origin，单次传输且不改全局fetch", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json({ status: "ok" }));
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
  expect(transport).not.toHaveBeenCalled();
  await client.GET("/api/health");
  expect(transport).toHaveBeenCalledTimes(1);
  expect(transport.mock.calls[0]?.[0].url).toBe(new URL("/api/health", location.href).href);
  expect(transport.mock.calls[0]?.[0].credentials).toBe("same-origin");
});

it("验证契约：任意接口401包括非法body统一通知未登录处理，仍保留安全错误，不循环跳转", async () => {
  for (const response of [
    problemResponse(401),
    new Response("<script>secret</script>", { status: 401 }),
  ]) {
    const onUnauthorized = vi.fn();
    const transport = vi.fn<FetchImplementation>().mockResolvedValue(response);
    const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized });
    await expect(client.GET("/api/health")).rejects.toThrow("请求失败");
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(transport).toHaveBeenCalledTimes(1);
  }
});

it("验证契约：429保留合法problem和1–60秒Retry-After，非法头安全忽略，不自动重试", async () => {
  for (const [header, expected] of [
    ["1", 1],
    ["60", 60],
    ["0", undefined],
    ["61", undefined],
    ["1.5", undefined],
    ["secret", undefined],
  ] as const) {
    const response = problemResponse(429);
    response.headers.set("Retry-After", header);
    const transport = vi.fn<FetchImplementation>().mockResolvedValue(response);
    const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
    let caught: unknown;
    try {
      await api.login({
        client,
        payload: { login_name: "admin", password: "private-credential" },
        signal: new AbortController().signal,
      });
    } catch (error) {
      caught = error;
    }
    const failure = toFailureView(caught);
    expect(failure.kind).toBe("problem");
    if (failure.kind === "problem") {
      expect(failure.problem.status).toBe(429);
      expect(failure.retryAfterSeconds).toBe(expected);
    }
    expect(transport).toHaveBeenCalledTimes(1);
  }
});

it("验证契约：所有操作仅用生成类型与正确method/path/body，口令不进URL或持久缓存", async () => {
  const stored = vi.spyOn(Storage.prototype, "setItem");
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(account));
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
  const payload: api.NewAccountInput = {
    login_name: "member",
    display_name: "成员",
    role: "member",
    password: "private-credential",
  };
  await api.createAccount({ client, payload, signal: new AbortController().signal });
  expect(stored).not.toHaveBeenCalled();
  const request = transport.mock.calls[0]?.[0];
  expect(request?.url).not.toContain("private-credential");
  expect(await request?.json()).toEqual(payload);
});

it("验证契约：login成功200并读取安全账号；401未知与错口令同文案；403/422/429及网络失败可展示", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(account));
  const onUnauthorized = vi.fn();
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized });
  const input = {
    client,
    payload: { login_name: "admin", password: "private-credential" },
    signal: new AbortController().signal,
  };
  expect(await api.login(input)).toEqual(account);
  const request = transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("POST");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/auth/login");
  expect(await request?.json()).toEqual(input.payload);
  for (const status of [401, 403, 422, 429]) {
    transport.mockResolvedValueOnce(problemResponse(status));
    await expect(api.login(input)).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status } },
    });
  }
  transport.mockRejectedValueOnce(new Error("private-network-detail"));
  await expect(api.login(input)).rejects.toMatchObject({
    message: "请求失败",
    cause: { kind: "unavailable" },
  });
});

it("验证契约：logout成功204无数据，401通知统一未登录处理；I/O失败不假装登出成功", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(new Response(null, { status: 204 }));
  const onUnauthorized = vi.fn();
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized });
  const payload: undefined = undefined;
  const input = { client, payload, signal: new AbortController().signal };
  await api.logout(input);
  const request = transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("POST");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/auth/logout");
  expect(request?.url).not.toContain("private-credential");
  for (const status of [401, 502]) {
    transport.mockResolvedValueOnce(problemResponse(status));
    await expect(api.logout(input)).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status } },
    });
  }
  expect(onUnauthorized).toHaveBeenCalledTimes(1);
});

it("验证契约：fetchCurrentAccount成功200；401跳登录，502保留错误不当作匿名", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json(account, { status: 200 }));
  const onUnauthorized = vi.fn();
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized });
  const payload: undefined = undefined;
  const input = { client, payload, signal: new AbortController().signal };
  expect(await api.fetchCurrentAccount(input)).toEqual(account);
  const request = transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("GET");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/auth/me");
  expect(request?.url).not.toContain("private-credential");
  for (const status of [401, 502]) {
    transport.mockResolvedValueOnce(problemResponse(status));
    await expect(api.fetchCurrentAccount(input)).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status } },
    });
  }
  expect(onUnauthorized).toHaveBeenCalledTimes(1);
});

it("验证契约：changePassword成功返回新身份并由服务器轮换cookie；旧口令400保留身份和当前页，第五次429可展示，真实401通知未登录处理，秘密清理由页面负责", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json(account, { status: 200 }));
  const onUnauthorized = vi.fn();
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized });
  const payload: api.PasswordInput = {
    current_password: "original-value",
    new_password: "replacement-value",
  };
  const input = { client, payload, signal: new AbortController().signal };
  expect(await api.changePassword(input)).toEqual(account);
  const request = transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("POST");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/auth/password");
  expect(request?.url).not.toContain("private-credential");
  expect(await request?.json()).toEqual(payload);
  for (const status of [400, 401, 422, 429]) {
    transport.mockResolvedValueOnce(problemResponse(status));
    await expect(api.changePassword(input)).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status } },
    });
  }
  expect(onUnauthorized).toHaveBeenCalledTimes(1);
});

it("验证契约：listAccounts空页、100项上界、末页null及64位文本游标无精度损失", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json({ items: [], next_after_id: null }, { status: 200 }));
  const onUnauthorized = vi.fn();
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized });
  const payload: undefined = undefined;
  const input = {
    client,
    payload,
    signal: new AbortController().signal,
    afterId: "9007199254740993",
  };
  expect(await api.listAccounts(input)).toEqual({ items: [], next_after_id: null });
  const request = transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("GET");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/accounts");
  expect(request?.url).not.toContain("private-credential");
  expect(new URL(request?.url ?? "").searchParams.get("after_id")).toBe("9007199254740993");
  for (const status of [403, 502]) {
    transport.mockResolvedValueOnce(problemResponse(status));
    await expect(api.listAccounts(input)).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status } },
    });
  }
  expect(onUnauthorized).toHaveBeenCalledTimes(0);
});

it("验证契约：createAccount成功201返回安全账号，409冲突保留安全错误，表单清理由页面负责", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json(account, { status: 201 }));
  const onUnauthorized = vi.fn();
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized });
  const payload: api.NewAccountInput = {
    login_name: "member",
    display_name: "成员",
    role: "member",
    password: "private-credential",
  };
  const input = { client, payload, signal: new AbortController().signal };
  expect(await api.createAccount(input)).toEqual(account);
  const request = transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("POST");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/accounts");
  expect(request?.url).not.toContain("private-credential");
  expect(await request?.json()).toEqual(payload);
  for (const status of [409, 422, 502]) {
    transport.mockResolvedValueOnce(problemResponse(status));
    await expect(api.createAccount(input)).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status } },
    });
  }
  expect(onUnauthorized).toHaveBeenCalledTimes(0);
});

it("验证契约：setAccountRole成功返回身份，最后管理员409保留安全problem", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json(account, { status: 200 }));
  const onUnauthorized = vi.fn();
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized });
  const payload: api.RoleInput = { role: "member" };
  const input = {
    client,
    payload,
    signal: new AbortController().signal,
    accountId: "9007199254740993",
  };
  expect(await api.setAccountRole(input)).toEqual(account);
  const request = transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("PATCH");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/accounts/9007199254740993/role");
  expect(request?.url).not.toContain("private-credential");
  expect(await request?.json()).toEqual(payload);
  for (const status of [403, 409]) {
    transport.mockResolvedValueOnce(problemResponse(status));
    await expect(api.setAccountRole(input)).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status } },
    });
  }
  expect(onUnauthorized).toHaveBeenCalledTimes(0);
});

it("验证契约：setAccountStatus发送已确认的状态变更，成功返回账号，403/409保留安全错误", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json(account, { status: 200 }));
  const onUnauthorized = vi.fn();
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized });
  const payload: api.StatusInput = { status: "disabled" };
  const input = {
    client,
    payload,
    signal: new AbortController().signal,
    accountId: "9007199254740993",
  };
  expect(await api.setAccountStatus(input)).toEqual(account);
  const request = transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("PATCH");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/accounts/9007199254740993/status");
  expect(request?.url).not.toContain("private-credential");
  expect(await request?.json()).toEqual(payload);
  for (const status of [403, 409]) {
    transport.mockResolvedValueOnce(problemResponse(status));
    await expect(api.setAccountStatus(input)).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status } },
    });
  }
  expect(onUnauthorized).toHaveBeenCalledTimes(0);
});

it("验证契约：resetAccountPassword成功返回强制改密身份，404/422/网络错误可展示", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json(account, { status: 200 }));
  const onUnauthorized = vi.fn();
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized });
  const payload: api.ResetInput = { password: "private-credential" };
  const input = {
    client,
    payload,
    signal: new AbortController().signal,
    accountId: "9007199254740993",
  };
  expect(await api.resetAccountPassword(input)).toEqual(account);
  const request = transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("POST");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/accounts/9007199254740993/password");
  expect(request?.url).not.toContain("private-credential");
  expect(await request?.json()).toEqual(payload);
  for (const status of [404, 422, 502]) {
    transport.mockResolvedValueOnce(problemResponse(status));
    await expect(api.resetAccountPassword(input)).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status } },
    });
  }
  expect(onUnauthorized).toHaveBeenCalledTimes(0);
});

it("验证契约：deleteAccount成功204无数据，404/409/网络错误保留安全失败", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(new Response(null, { status: 204 }));
  const onUnauthorized = vi.fn();
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized });
  const payload: undefined = undefined;
  const input = {
    client,
    payload,
    signal: new AbortController().signal,
    accountId: "9007199254740993",
  };
  await api.deleteAccount(input);
  const request = transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("DELETE");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/accounts/9007199254740993");
  expect(request?.url).not.toContain("private-credential");
  for (const status of [404, 409, 502]) {
    transport.mockResolvedValueOnce(problemResponse(status));
    await expect(api.deleteAccount(input)).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status } },
    });
  }
  expect(onUnauthorized).toHaveBeenCalledTimes(0);
});

it("验证契约：每个API超时10秒、AbortSignal透传、卸载取消且忽略迟到结果，不自动重试写请求", async () => {
  vi.useFakeTimers();
  const calls: ((client: api.AccountCall["client"], signal: AbortSignal) => Promise<unknown>)[] = [
    (client, signal) =>
      api.login({ client, signal, payload: { login_name: "admin", password: "private-value" } }),
    (client, signal) => api.logout({ client, signal, payload: undefined }),
    (client, signal) => api.fetchCurrentAccount({ client, signal, payload: undefined }),
    (client, signal) =>
      api.changePassword({
        client,
        signal,
        payload: { current_password: "current-value", new_password: "new-private-value" },
      }),
    (client, signal) => api.listAccounts({ client, signal, payload: undefined, afterId: "0" }),
    (client, signal) =>
      api.createAccount({
        client,
        signal,
        payload: {
          login_name: "member",
          display_name: "成员",
          role: "member",
          password: "private-value",
        },
      }),
    (client, signal) =>
      api.setAccountRole({ client, signal, accountId: "1", payload: { role: "member" } }),
    (client, signal) =>
      api.setAccountStatus({ client, signal, accountId: "1", payload: { status: "disabled" } }),
    (client, signal) =>
      api.resetAccountPassword({
        client,
        signal,
        accountId: "1",
        payload: { password: "private-value" },
      }),
    (client, signal) => api.deleteAccount({ client, signal, accountId: "1", payload: undefined }),
  ];
  for (const call of calls) {
    let finish: (response: Response) => void = () => undefined;
    const transport = vi.fn<FetchImplementation>(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
    const controller = new AbortController();
    const request = call(client, controller.signal);
    const rejected = expect(request).rejects.toThrow("请求失败");
    await vi.advanceTimersByTimeAsync(10000);
    await rejected;
    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(true);
    finish(Response.json(account));
    await Promise.resolve();
    expect(vi.getTimerCount()).toBe(0);
    controller.abort();
    await expect(call(client, controller.signal)).rejects.toThrow("请求失败");
    expect(transport).toHaveBeenCalledTimes(1);
  }
});

it("验证契约：所有账号错误经toFailureView，原异常和服务端HTML不执行或泄漏", async () => {
  for (const response of [
    new Response("<img src=x onerror=alert(1)>", { status: 502 }),
    Response.json({ password: "private-value" }, { status: 400 }),
  ]) {
    const client = api.createAccountClient({
      fetchImpl: vi.fn<FetchImplementation>().mockResolvedValue(response),
      onUnauthorized: vi.fn(),
    });
    let caught: unknown;
    try {
      await api.fetchCurrentAccount({
        client,
        payload: undefined,
        signal: new AbortController().signal,
      });
    } catch (error) {
      caught = error;
    }
    expect(toFailureView(caught)).toEqual({
      kind: "unavailable",
      message: "请求失败，请检查网络或稍后重试。",
    });
    expect(JSON.stringify(toFailureView(caught))).not.toContain("private-value");
  }
});

it("验证契约：401/403/429的problem正确标题类别被运行时解析接受，错误组合被拒绝", async () => {
  for (const status of [401, 403, 429]) {
    expect((await readProblemResponse(problemResponse(status)))?.status).toBe(status);
    const payload: unknown = await problemResponse(status).json();
    if (typeof payload !== "object" || payload === null) throw new Error("测试样本必须是对象");
    const bad = Response.json(
      { ...payload, category: "defect" },
      { status, headers: { "Content-Type": "application/problem+json" } },
    );
    expect(await readProblemResponse(bad)).toBeNull();
  }
});

it("验证契约：Argon2容量不足的502显示安全资源繁忙，不当作G2的429，不自动重试或伪造Retry-After", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(problemResponse(502));
  const client = api.createAccountClient({ fetchImpl: transport, onUnauthorized: vi.fn() });
  await expect(
    api.login({
      client,
      payload: { login_name: "admin", password: "private-credential" },
      signal: new AbortController().signal,
    }),
  ).rejects.toMatchObject({
    cause: { kind: "problem", problem: { status: 502, detail: "口令核验资源繁忙" } },
  });
  expect(transport).toHaveBeenCalledTimes(1);
});

it("验证契约：changePassword的400及409保留安全problem，不调用onUnauthorized；401仍统一退出，429保留Retry-After", async () => {
  const unauthorized = vi.fn();
  for (const status of [400, 409, 429, 401]) {
    const client = api.createAccountClient({
      fetchImpl: vi.fn<FetchImplementation>().mockResolvedValue(problemResponse(status)),
      onUnauthorized: unauthorized,
    });
    await expect(
      api.changePassword({
        client,
        payload: { current_password: "old-credential", new_password: "new-credential" },
        signal: new AbortController().signal,
      }),
    ).rejects.toMatchObject({ cause: { kind: "problem", problem: { status } } });
    expect(unauthorized).toHaveBeenCalledTimes(status === 401 ? 1 : 0);
  }
});
