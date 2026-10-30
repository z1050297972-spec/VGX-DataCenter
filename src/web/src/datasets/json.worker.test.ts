// Worker 的消息边界验收；在独立 self 替身加载真实入口，不直接调用内部解析函数。
import { it, expect, vi, afterEach } from "vitest";
import type { JsonPage, JsonRequest } from "./jsonProtocol";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

// 契约：完整 14 MB 文件可解析，但每条响应有界；所有原文字节对应的字符仍能逐页取回。
it("Worker 解析 14 MB 原文并返回有界页面，末页不丢失", async () => {
  const scope = {
    onmessage: null as ((event: MessageEvent<JsonRequest>) => void) | null,
    postMessage: vi.fn<(value: JsonPage) => void>(),
  };
  vi.stubGlobal("self", scope);
  await import("./json.worker");
  const text = '{"large":"' + "x".repeat(14 * 1024 * 1024) + '","tail":"保留尾部"}';
  scope.onmessage?.(new MessageEvent("message", { data: { type: "load", text } }));
  const first = scope.postMessage.mock.calls[0]?.[0];
  if (!first) throw new Error("没有收到 Worker 响应");
  expect(first.valid).toBe(true);
  expect(first.text).toBe(text.slice(0, 20_000));
  expect(first.text.length).toBeLessThanOrEqual(20_000);
  scope.onmessage?.(
    new MessageEvent("message", { data: { type: "page", page: first.totalPages - 1 } }),
  );
  const last = scope.postMessage.mock.calls[1]?.[0];
  if (!last) throw new Error("没有收到末页响应");
  expect(last.text.endsWith('"tail":"保留尾部"}')).toBe(true);
  expect(last.page).toBe(first.totalPages - 1);
  expect(last.text).toBe(text.slice((first.totalPages - 1) * 20_000));
});

// 契约：坏 JSON 仍可查看原文，同时明确标记无法解析；不能悄悄显示为空对象。
it("Worker 对坏 JSON 保留原文并标记无效", async () => {
  const scope = {
    onmessage: null as ((event: MessageEvent<JsonRequest>) => void) | null,
    postMessage: vi.fn<(value: JsonPage) => void>(),
  };
  vi.stubGlobal("self", scope);
  await import("./json.worker");
  scope.onmessage?.(new MessageEvent("message", { data: { type: "load", text: '{"broken":' } }));
  expect(scope.postMessage).toHaveBeenCalledWith({
    text: '{"broken":',
    page: 0,
    totalPages: 1,
    valid: false,
  });
});

// M1.5契约：可选格式化在Worker内进行，分页保留大整数、指数和字符串内容；原文模式仍不变。
it("原文件JSON格式化保留数字原词法并分页", async () => {
  const scope = {
    onmessage: null as ((event: MessageEvent<JsonRequest>) => void) | null,
    postMessage: vi.fn<(value: JsonPage) => void>(),
  };
  vi.stubGlobal("self", scope);
  await import("./json.worker");
  scope.onmessage?.(
    new MessageEvent("message", {
      data: {
        type: "load",
        text: '{"n":9007199254740993,"e":1e30,"s":"a,b","empty":[]}',
        format: true,
      },
    }),
  );
  expect(scope.postMessage).toHaveBeenCalledWith({
    text: '{\n  "n": 9007199254740993,\n  "e": 1e30,\n  "s": "a,b",\n  "empty": []\n}',
    page: 0,
    totalPages: 1,
    valid: true,
  });
});
