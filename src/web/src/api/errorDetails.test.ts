// 工单 05 详情请求与回调契约测试；传输注入内存替身，不发真实请求。
import { formatDateTime } from "../time";
import { it, expect, vi, afterEach } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { createElement } from "react";
import { render, screen, cleanup, fireEvent, act, waitFor } from "@testing-library/react";
import { createHealthClient, type FetchImplementation } from "./client";
import { fetchErrorDetails, createErrorDetailsLoader, type ErrorDetails } from "./errorDetails";
import { DiagnosticCard } from "../DiagnosticCard";
import type { RequestFailureView } from "./problems";

const id = "123456789abc4def8abc123456789abc";
const clients: QueryClient[] = [];
function queryClient(): QueryClient {
  const client = new QueryClient();
  clients.push(client);
  return client;
}
function details(changes: Partial<ErrorDetails> = {}): ErrorDetails {
  return {
    error_id: id,
    occurred_at: "2026-10-24T12:00:00.123456Z",
    category: "defect",
    summary: "安全摘要",
    report: "TypeError: 示例\n",
    source_kind: "request",
    ...changes,
  };
}
function failure(errorId = id): RequestFailureView {
  return {
    kind: "problem",
    problem: {
      type: "about:blank",
      title: "Internal Server Error",
      status: 500,
      detail: "平台内部错误",
      category: "defect",
      diagnostics: [],
      error_id: errorId,
    },
  };
}
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("验证契约：fetchErrorDetails 只用生成的 ErrorRecord 类型和相对 GET 路径，返回完整且编号相符的详情", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(details()));
  const result = await fetchErrorDetails(
    createHealthClient(transport),
    id,
    new AbortController().signal,
  );
  expect(result).toEqual(details());
  expect(transport).toHaveBeenCalledTimes(1);
  expect(transport.mock.calls[0]?.[0].url).toBe(new URL("/api/errors/" + id, location.href).href);
});
it("验证契约：请求 uuid4 hex 和规范整数作业编号均可查询，路径参数由客户端编码", async () => {
  for (const identifier of [id, "7", "9223372036854775807"]) {
    const payload = details({
      error_id: identifier,
      source_kind: identifier === id ? "request" : "job",
    });
    const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(payload));
    expect(
      await fetchErrorDetails(
        createHealthClient(transport),
        identifier,
        new AbortController().signal,
      ),
    ).toEqual(payload);
    expect(transport.mock.calls[0]?.[0].url).toContain("/api/errors/" + identifier);
  }
});
it("验证契约：非法编号或已取消信号在发送前拒绝，不产生请求", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(details()));
  const client = createHealthClient(transport);
  await expect(fetchErrorDetails(client, "../bad", new AbortController().signal)).rejects.toThrow();
  await expect(fetchErrorDetails(client, id, AbortSignal.abort())).rejects.toThrow();
  expect(transport).not.toHaveBeenCalled();
});
it("验证契约：HTTP 404 过期或未保存记录拒绝，卡片显示固定完整报错暂不可用提示", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(new Response("not found", { status: 404 }));
  render(
    createElement(DiagnosticCard, {
      failure: failure(),
      loadDetails: createErrorDetailsLoader(createHealthClient(transport), queryClient()),
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  expect(await screen.findByText("完整报错暂不可用，请按编号查询运行日志。")).toBeTruthy();
});
it("验证契约：HTTP 422、409、500、502 沿用统一客户端的安全 Error cause", async () => {
  for (const status of [422, 409, 500, 502]) {
    const transport = vi
      .fn<FetchImplementation>()
      .mockResolvedValue(new Response("unsafe", { status }));
    await expect(
      fetchErrorDetails(createHealthClient(transport), id, new AbortController().signal),
    ).rejects.toMatchObject({ message: "请求失败", cause: { kind: "unavailable" } });
  }
});
it("验证契约：空体、坏 JSON、缺字段、额外字段、非法来源/时间/类别、编号错配均拒绝", async () => {
  const invalid = [
    { ...details(), extra: true },
    { ...details(), report: undefined },
    { ...details(), category: "wrong" },
    { ...details(), source_kind: "job" },
    { ...details(), occurred_at: "2026-02-30T12:00:00Z" },
    { ...details(), error_id: "7" },
    null,
  ];
  for (const payload of invalid) {
    const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(payload));
    await expect(
      fetchErrorDetails(createHealthClient(transport), id, new AbortController().signal),
    ).rejects.toThrow();
  }
  const bad = vi.fn<FetchImplementation>().mockResolvedValue(new Response("bad json"));
  await expect(
    fetchErrorDetails(createHealthClient(bad), id, new AbortController().signal),
  ).rejects.toThrow();
});
it("验证契约：超长摘要/报告拒绝，N 字符和截断标记合法内容逐字保留", async () => {
  for (const payload of [
    details({ summary: "x".repeat(513) }),
    details({ report: "x".repeat(262145) }),
  ]) {
    const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(payload));
    await expect(
      fetchErrorDetails(createHealthClient(transport), id, new AbortController().signal),
    ).rejects.toThrow();
  }
  const payload = details({ report: "😀".repeat(262144) });
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(payload));
  expect(
    (await fetchErrorDetails(createHealthClient(transport), id, new AbortController().signal))
      .report,
  ).toBe(payload.report);
});
it("验证契约：网络失败和代理 HTML 不显示原文，卡片仅显示固定失败文案", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockRejectedValue(new Error("secret-proxy-content"));
  render(
    createElement(DiagnosticCard, {
      failure: failure(),
      loadDetails: createErrorDetailsLoader(createHealthClient(transport), queryClient()),
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  expect(await screen.findByText("完整报错暂不可用，请按编号查询运行日志。")).toBeTruthy();
  expect(screen.queryByText(/secret-proxy-content/)).toBeNull();
});
it("验证契约：createErrorDetailsLoader 创建本身无请求，首次展开才经 TanStack Query 的 query 调用一次", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(details()));
  const loader = createErrorDetailsLoader(createHealthClient(transport), queryClient());
  expect(transport).not.toHaveBeenCalled();
  render(createElement(DiagnosticCard, { failure: failure(), loadDetails: loader }));
  expect(transport).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  expect(await screen.findByText(/TypeError: 示例/)).toBeTruthy();
  expect(transport).toHaveBeenCalledTimes(1);
});
it("验证契约：详情查询 retry=false，无轮询、无隐式重试，staleTime/gcTime 为 0", async () => {
  const transport = vi.fn<FetchImplementation>().mockRejectedValue(new Error("offline"));
  const cache = queryClient();
  const loader = createErrorDetailsLoader(createHealthClient(transport), cache);
  await expect(loader(id, new AbortController().signal)).rejects.toThrow();
  expect(transport).toHaveBeenCalledTimes(1);
  expect(cache.getQueryCache().getAll()).toHaveLength(0);
});
it("验证契约：回调合并 Query 和卡片取消信号，不修改 URL、全局 fetch 或浏览器存储", async () => {
  const transport = vi.fn<FetchImplementation>(
    (request) =>
      new Promise((_resolve, reject) => {
        request.signal.addEventListener(
          "abort",
          () => {
            reject(new Error("cancelled"));
          },
          { once: true },
        );
      }),
  );
  const cache = queryClient();
  const loader = createErrorDetailsLoader(createHealthClient(transport), cache);
  const url = location.href;
  const pending = loader(id, new AbortController().signal);
  const rejection = expect(pending).rejects.toThrow();
  await cache.cancelQueries({ queryKey: ["error-details"] });
  await rejection;
  expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(true);
  expect(location.href).toBe(url);
});
it("验证契约：详情五秒超时沿用 ERROR_DETAILS_TIMEOUT_MS，清理计时器且不显示迟到内容", async () => {
  vi.useFakeTimers();
  const transport = vi.fn<FetchImplementation>(
    (request) =>
      new Promise((_resolve, reject) => {
        request.signal.addEventListener(
          "abort",
          () => {
            reject(new Error("cancelled"));
          },
          { once: true },
        );
      }),
  );
  render(
    createElement(DiagnosticCard, {
      failure: failure(),
      loadDetails: createErrorDetailsLoader(createHealthClient(transport), queryClient()),
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(screen.getByText("完整报错暂不可用，请按编号查询运行日志。")).toBeTruthy();
  expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(true);
});
it("验证契约：卸载、编号变化、客户端变化取消旧请求，旧结果不污染新卡片", async () => {
  const transport = vi.fn<FetchImplementation>(
    (request) =>
      new Promise((_resolve, reject) => {
        request.signal.addEventListener(
          "abort",
          () => {
            reject(new Error("cancelled"));
          },
          { once: true },
        );
      }),
  );
  const loader = createErrorDetailsLoader(createHealthClient(transport), queryClient());
  const view = render(createElement(DiagnosticCard, { failure: failure(), loadDetails: loader }));
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  await waitFor(() => {
    expect(transport).toHaveBeenCalledTimes(1);
  });
  view.rerender(
    createElement(DiagnosticCard, {
      failure: failure("abcdef1234564def8abc123456789abc"),
      loadDetails: loader,
    }),
  );
  expect(transport.mock.calls[0]?.[0].signal.aborted).toBe(true);
  expect(screen.queryByText("正在加载完整报错…")).toBeNull();
  view.unmount();
});
it("验证契约：不同客户端/编号查询隔离，结束后不长期缓存敏感报告", async () => {
  const first = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json(details({ report: "first" })));
  const second = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json(details({ report: "second" })));
  const cache = queryClient();
  const a = createErrorDetailsLoader(createHealthClient(first), cache);
  const b = createErrorDetailsLoader(createHealthClient(second), cache);
  const values = await Promise.all([
    a(id, new AbortController().signal),
    b(id, new AbortController().signal),
  ]);
  expect(values[0]).toContain("first");
  expect(values[1]).toContain("second");
  expect(cache.getQueryCache().getAll()).toHaveLength(0);
});
it("验证契约：返回纯文本包含本地时间和时区、类别、摘要、来源编号，report 段逐字不变", async () => {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(Response.json(details()));
  const value = await createErrorDetailsLoader(createHealthClient(transport), queryClient())(
    id,
    new AbortController().signal,
  );
  expect(value).toContain(`发生时间：${formatDateTime(details().occurred_at)}`);
  expect(value).toContain("类别：defect");
  expect(value).toContain("摘要：安全摘要");
  expect(value).toContain("来源：request " + id);
  expect(value.endsWith(details().report)).toBe(true);
});
it("验证契约：包含 HTML 的合法报告按 React 文本显示，不能执行标签", async () => {
  const transport = vi
    .fn<FetchImplementation>()
    .mockResolvedValue(Response.json(details({ report: "<img src=x>safe" })));
  render(
    createElement(DiagnosticCard, {
      failure: failure(),
      loadDetails: createErrorDetailsLoader(createHealthClient(transport), queryClient()),
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  expect(await screen.findByText(/<img src=x>safe/)).toBeTruthy();
  expect(document.querySelector("img")).toBeNull();
});
it("验证契约：回调请求失败拒绝 Promise，卡片不展示异常原文", async () => {
  const transport = vi.fn<FetchImplementation>().mockRejectedValue(new Error("secret"));
  await expect(
    createErrorDetailsLoader(createHealthClient(transport), queryClient())(
      id,
      new AbortController().signal,
    ),
  ).rejects.toMatchObject({ message: "请求失败" });
  expect(transport).toHaveBeenCalledTimes(1);
});
