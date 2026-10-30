// M1-10 API 边界：通用作业参数要求 JSON 整数，不能把长编号舍入后提交给另一份预览。
import { describe, it, expect } from "vitest";
import { createAccountClient } from "./accounts";
import { applyNavigationPreview } from "./dataOrigin";
import { originFetch } from "../datasets/originTestSupport";

describe("数据来源请求编号", () => {
  // 契约：超过 JavaScript 安全整数的预览编号明确拒绝，不能产生写请求。
  it("超出安全整数的预览编号不舍入也不发送", async () => {
    const requests: Request[] = [];
    const client = createAccountClient({
      fetchImpl: originFetch(requests),
      onUnauthorized: () => undefined,
    });
    await expect(
      applyNavigationPreview({
        client,
        payload: "9007199254740993",
        signal: new AbortController().signal,
      }),
    ).rejects.toThrow("安全整数范围");
    expect(requests).toHaveLength(0);
  });
});
