// 08传输契约：真实defaultFetch的浏览器this绑定回归，其他请求用账号感知客户端。
import { expect, it, vi } from "vitest";
import { createAccountClient } from "./accounts";
import { defaultFetch } from "./client";
import { listJobs } from "./jobs";

it.skip("规范7.1：默认传输保持浏览器原生fetch的this，成员通过账号感知客户端GET作业", async () => {
  vi.stubGlobal("fetch", function (this: unknown) {
    if (this !== globalThis) throw new TypeError("Illegal invocation");
    return Promise.resolve(Response.json({ items: [], next_cursor: null }));
  });
  try {
    const client = createAccountClient({ fetchImpl: defaultFetch, onUnauthorized: vi.fn() });
    const page = await listJobs({ client, payload: {}, signal: new AbortController().signal });
    expect(page).toEqual({ items: [], next_cursor: null });
  } finally {
    vi.unstubAllGlobals();
  }
});

it.skip("HTTP契约：提交/取消/重提使用生成路径与同源Origin，201/200后才显示成功，不重试POST", () => {
  throw new Error("未实现");
});
it.skip("HTTP契约：401清缓存，409保留诊断，422不回显载荷，超时或取消不声称数据库已回滚", () => {
  throw new Error("未实现");
});
it.skip("分页契约：state/limit/cursor传输不改原值，文本编号超过JS安全整数仍无损", () => {
  throw new Error("未实现");
});
it.skip("资源契约：卸载取消AbortSignal并忽略迟到响应，不持久化参数或身份", () => {
  throw new Error("未实现");
});
