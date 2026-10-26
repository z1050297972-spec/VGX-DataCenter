// 日志传输公开边界；注入HTTP替身和假时钟，不启动服务器、不保留浏览器全局修改。
import { afterEach, expect, it, vi } from "vitest";
import * as audit from "./audit";
import { createAccountClient } from "./accounts";
import { defaultFetch, type FetchImplementation } from "./client";
import { problemResponse } from "../accounts/testSupport";

const empty = { items: [], next_cursor: null };
function setup(response: Response = Response.json(empty)) {
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(response);
  const unauthorized = vi.fn();
  const client = createAccountClient({ fetchImpl: transport, onUnauthorized: unauthorized });
  return { transport, unauthorized, client, signal: new AbortController().signal };
}
function calls(input: ReturnType<typeof setup>): Array<() => Promise<unknown>> {
  return [
    () => audit.listOperationLogs({ ...input, payload: {} }),
    () => audit.listLoginLogs({ ...input, payload: {} }),
    () => audit.getAuditRetention({ ...input, payload: undefined }),
    () => audit.setAuditRetention({ ...input, payload: { days: 7 } }),
  ];
}
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("验收1：列表只调用相对路径GET并按生成query类型发送游标，不提供单条编辑删除函数", async () => {
  const input = setup();
  await audit.listOperationLogs({
    ...input,
    payload: { cursor: "cursor-value", limit: 7, operation: "set_role" },
  });
  const request = input.transport.mock.calls[0]?.[0];
  expect(request?.method).toBe("GET");
  expect(new URL(request?.url ?? "").pathname).toBe("/api/audit/operations");
  expect(new URL(request?.url ?? "").searchParams.get("cursor")).toBe("cursor-value");
  expect(Object.keys(audit).some((key) => /delete|updateOperation/u.test(key))).toBe(false);
});
it("验收1：操作日志和登录日志空页及next_cursor=null正确返回，不自动全量翻页", async () => {
  for (const method of [audit.listOperationLogs, audit.listLoginLogs]) {
    const input = setup();
    expect(await method({ ...input, payload: {} })).toEqual(empty);
    expect(input.transport).toHaveBeenCalledTimes(1);
  }
});
it("验收4：编号大于2^53仍保持文本，不回传口令、令牌、cookie或未知登录名", async () => {
  const input = setup();
  await audit.listLoginLogs({
    ...input,
    payload: { account_id: "9007199254740993", result: "account_missing" },
  });
  const request = input.transport.mock.calls[0]?.[0];
  expect(new URL(request?.url ?? "").searchParams.get("account_id")).toBe("9007199254740993");
  expect(request?.body).toBeNull();
  expect(request?.headers.has("Cookie")).toBe(false);
});
it("验收5：读取保留期失败不伪造30天，PUT仅发送严格整数days", async () => {
  const input = setup(Response.json({ days: 7 }));
  expect(await audit.setAuditRetention({ ...input, payload: { days: 7 } })).toEqual({ days: 7 });
  expect(input.transport.mock.calls[0]?.[0].method).toBe("PUT");
  expect(await input.transport.mock.calls[0]?.[0].json()).toEqual({ days: 7 });
  input.transport.mockResolvedValueOnce(problemResponse(502));
  await expect(audit.getAuditRetention({ ...input, payload: undefined })).rejects.toThrow(
    "请求失败",
  );
});
it("验收5：写保留期成功才失效缓存，超时不宣称服务端已经回滚或自动重试", async () => {
  vi.useFakeTimers();
  const input = setup();
  input.transport.mockImplementation(() => new Promise<Response>(() => undefined));
  const pending = audit.setAuditRetention({ ...input, payload: { days: 7 } });
  const rejected = expect(pending).rejects.toThrow("请求失败");
  await vi.advanceTimersByTimeAsync(10000);
  await rejected;
  expect(input.transport).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});
it("验收6：两个日志接口及设置的401走账号感知客户端清缓存并导航登录", async () => {
  const input = setup();
  for (const invoke of calls(input)) {
    input.transport.mockResolvedValueOnce(problemResponse(401));
    await expect(invoke()).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status: 401 } },
    });
  }
  expect(input.unauthorized).toHaveBeenCalledTimes(4);
});
it("验收6：403保持统一诊断，502不误判为未登录，422不回显输入值", async () => {
  const input = setup();
  for (const status of [403, 502, 422]) {
    input.transport.mockResolvedValueOnce(problemResponse(status));
    await expect(audit.listOperationLogs({ ...input, payload: {} })).rejects.toMatchObject({
      cause: { kind: "problem", problem: { status } },
    });
  }
  expect(input.unauthorized).not.toHaveBeenCalled();
});
it("传输回归：沿用defaultFetch和createAccountClient，不把原生fetch存为对象方法导致Illegal invocation", async () => {
  const native = vi.fn(function (this: unknown) {
    if (this !== undefined && this !== globalThis) throw new TypeError("Illegal invocation");
    return Promise.resolve(Response.json(empty));
  });
  vi.stubGlobal("fetch", native);
  const client = createAccountClient({ fetchImpl: defaultFetch, onUnauthorized: vi.fn() });
  expect(
    await audit.listOperationLogs({ client, payload: {}, signal: new AbortController().signal }),
  ).toEqual(empty);
  expect(native).toHaveBeenCalledTimes(1);
});
it("时间契约：所有四种请求最多10000毫秒，超时和取消释放计时器且忽略迟到结果", async () => {
  vi.useFakeTimers();
  for (let index = 0; index < 4; index++) {
    const input = setup();
    input.transport.mockImplementation(() => new Promise<Response>(() => undefined));
    const invoke = calls(input)[index];
    if (!invoke) throw new Error("测试调用缺失");
    const pending = invoke();
    const failed = expect(pending).rejects.toThrow("请求失败");
    await vi.advanceTimersByTimeAsync(9999);
    expect(input.transport.mock.calls[0]?.[0].signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await failed;
    expect(vi.getTimerCount()).toBe(0);
  }
  const input = setup();
  const controller = new AbortController();
  let finish: ((response: Response) => void) | undefined;
  input.transport.mockImplementation(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  const pending = audit.listOperationLogs({ ...input, signal: controller.signal, payload: {} });
  const failed = expect(pending).rejects.toThrow("请求失败");
  controller.abort();
  await failed;
  finish?.(Response.json(empty));
  expect(vi.getTimerCount()).toBe(0);
});
it("诊断契约：畸形响应、网络错误和取消统一用toFailureView，不展示原始异常或HTML", async () => {
  const input = setup(Response.json({ secret: "不能展示" }));
  await expect(audit.listOperationLogs({ ...input, payload: {} })).rejects.toThrow("请求失败");
  input.transport.mockRejectedValueOnce(new Error("秘密网络详情"));
  await expect(audit.getAuditRetention({ ...input, payload: undefined })).rejects.toMatchObject({
    message: "请求失败",
    cause: { kind: "unavailable" },
  });
  const controller = new AbortController();
  controller.abort();
  await expect(
    audit.listLoginLogs({ ...input, signal: controller.signal, payload: {} }),
  ).rejects.toThrow("请求失败");
});
it("Origin契约：保留期PUT是同源请求并由浏览器携带Origin，不读取HttpOnly cookie", async () => {
  const input = setup(Response.json({ days: 30 }));
  await audit.setAuditRetention({ ...input, payload: { days: 30 } });
  const request = input.transport.mock.calls[0]?.[0];
  expect(request?.credentials).toBe("same-origin");
  expect(new URL(request?.url ?? "").origin).toBe(location.origin);
  expect(request?.headers.has("Cookie")).toBe(false);
});
it("修订7：OperationSearch由OpenAPI生成，account_id和target_account_id作为两个独立字符串query发送，64位编号不转Number", async () => {
  const input = setup();
  await audit.listOperationLogs({
    ...input,
    payload: { account_id: "9007199254740993", target_account_id: "9007199254740995" },
  });
  const query = new URL(input.transport.mock.calls[0]?.[0].url ?? "").searchParams;
  expect(query.get("account_id")).toBe("9007199254740993");
  expect(query.get("target_account_id")).toBe("9007199254740995");
});
it("修订7：只传对象账号可查询谁动过该账号，同时传操作人取交集，不把设置对象当账号对象", async () => {
  const input = setup();
  await audit.listOperationLogs({ ...input, payload: { target_account_id: "11" } });
  const query = new URL(input.transport.mock.calls[0]?.[0].url ?? "").searchParams;
  expect(query.get("target_account_id")).toBe("11");
  expect(query.has("account_id")).toBe(false);
});
