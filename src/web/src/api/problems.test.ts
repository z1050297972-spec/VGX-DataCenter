// 工单 04 公开契约测试；验证可观察行为，不做整段文本快照。
import { it, expect, vi } from "vitest";
import {
  readProblemResponse,
  createProblemFetch,
  toFailureView,
  type ProblemResponse,
} from "./problems";
import type { FetchImplementation } from "./client";

const id = "123456789abc4def8abc123456789abc";
const fallback = { kind: "unavailable", message: "请求失败，请检查网络或稍后重试。" };

function problem(category: ProblemResponse["category"] = "input"): ProblemResponse {
  const status = { input: 400, conflict: 409, external: 502, defect: 500 }[category];
  const title = {
    input: "Bad Request",
    conflict: "Conflict",
    external: "Bad Gateway",
    defect: "Internal Server Error",
  }[category];
  return {
    type: "about:blank",
    status,
    title,
    category,
    detail: "安全摘要",
    error_id: id,
    diagnostics:
      category === "defect"
        ? []
        : [
            {
              level: "error",
              category,
              stage: "解码",
              source: "平台",
              objects: [{ key: "file", value: "样例.mcap" }],
              rule: "有关键帧",
              actual: "0个",
              expected: "至少1个",
              consequence: "该文件失败",
              next_step: "检查码流",
              error_chain: [],
            },
          ],
  };
}

function response(
  payload: unknown = problem(),
  status = 400,
  contentType = "application/problem+json",
): Response {
  return Response.json(payload, { status, headers: { "Content-Type": contentType } });
}

it("验证契约：readProblemResponse 合法四类 problem 保持顺序并使用生成类型，状态与HTTP一致", async () => {
  for (const category of ["input", "conflict", "external", "defect"] as const) {
    const payload = problem(category);
    expect(await readProblemResponse(response(payload, payload.status))).toEqual(payload);
  }
});

it("验证契约：readProblemResponse Content-Type大小写和参数合法；非problem媒体或成功响应返回null", async () => {
  expect(
    await readProblemResponse(response(problem(), 400, "Application/Problem+Json; charset=utf-8")),
  ).toEqual(problem());
  expect(await readProblemResponse(response(problem(), 400, "application/json"))).toBeNull();
  expect(await readProblemResponse(response(problem(), 200))).toBeNull();
});

it("验证契约：readProblemResponse HTML、空体、坏JSON、已消费body及读取失败返回null，不展示原文", async () => {
  for (const body of ["<h1>proxy secret</h1>", "", "{bad"]) {
    expect(
      await readProblemResponse(
        new Response(body, {
          status: 502,
          headers: { "Content-Type": "application/problem+json" },
        }),
      ),
    ).toBeNull();
  }
  const used = response();
  await used.text();
  expect(await readProblemResponse(used)).toBeNull();
  const broken = new Response(
    new ReadableStream({
      start(controller) {
        controller.error(new Error("断流"));
      },
    }),
    { status: 400, headers: { "Content-Type": "application/problem+json" } },
  );
  expect(await readProblemResponse(broken)).toBeNull();
});

it("验证契约：readProblemResponse 缺必填字段、额外字段、未知枚举、空白文本、非法对象值/重复键返回null", async () => {
  const missing = { ...problem() };
  Reflect.deleteProperty(missing, "error_id");
  const d = problem().diagnostics[0];
  for (const payload of [
    missing,
    { ...problem(), extra: 1 },
    { ...problem(), category: "other" },
    { ...problem(), detail: " " },
    { ...problem(), diagnostics: [{ ...d, objects: [{ key: "file", value: 4 }] }] },
    {
      ...problem(),
      diagnostics: [
        {
          ...d,
          objects: [
            { key: "file", value: "a" },
            { key: "file", value: "b" },
          ],
        },
      ],
    },
  ]) {
    expect(await readProblemResponse(response(payload))).toBeNull();
  }
});

it("验证契约：readProblemResponse 非法uuid、status与类别或title不符、DEFECT含诊断均返回null", async () => {
  for (const payload of [
    { ...problem(), error_id: "bad" },
    { ...problem(), status: 401 },
    { ...problem(), category: "external" },
    { ...problem(), title: "wrong" },
    { ...problem("defect"), diagnostics: problem().diagnostics },
  ]) {
    expect(await readProblemResponse(response(payload, payload.status))).toBeNull();
  }
  expect(await readProblemResponse(response(problem(), 422))).toBeNull();
});

it("验证契约：readProblemResponse 只读克隆，原Response仍可读取，不发新请求或记录日志", async () => {
  const original = response();
  expect(await readProblemResponse(original)).toEqual(problem());
  expect(await original.json()).toEqual(problem());
});

it("验证契约：createProblemFetch 创建不发送请求、不改全局fetch，不同包装器互不影响", () => {
  const transport = vi.fn<FetchImplementation>();
  const a = createProblemFetch(transport),
    b = createProblemFetch(transport);
  expect(a).not.toBe(b);
  expect(transport).not.toHaveBeenCalled();
});

it("验证契约：createProblemFetch 每次调用传输一次，2xx/3xx返回原Response且保留body/headers", async () => {
  for (const status of [200, 302]) {
    const original = new Response("成功", { status, headers: { "X-Test": "kept" } });
    const transport = vi.fn<FetchImplementation>().mockResolvedValue(original);
    const request = new Request("http://localhost/api/health");
    expect(await createProblemFetch(transport)(request)).toBe(original);
    expect(transport).toHaveBeenCalledExactlyOnceWith(request);
    expect(await original.text()).toBe("成功");
  }
});

it("验证契约：createProblemFetch 4xx/5xx合法problem拒绝Error且cause含原载荷，message为固定请求失败", async () => {
  const payload = problem("external");
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(response(payload, 502));
  await expect(
    createProblemFetch(transport)(new Request("http://localhost/api/health")),
  ).rejects.toMatchObject({
    message: "请求失败",
    cause: { kind: "problem", problem: payload },
  });
  expect(transport).toHaveBeenCalledTimes(1);
});

it("验证契约：createProblemFetch 网络拒绝/超时/取消转为固定不可用提示，不把异常原文放入cause", async () => {
  for (const original of [
    new TypeError("network secret"),
    new DOMException("abort secret", "AbortError"),
    new Error("timeout"),
  ]) {
    const transport = vi.fn<FetchImplementation>().mockRejectedValue(original);
    await expect(
      createProblemFetch(transport)(new Request("http://localhost/api/health")),
    ).rejects.toMatchObject({ message: "请求失败", cause: fallback });
  }
});

it("验证契约：createProblemFetch 代理HTML/坏problem使用不可用提示，只保留合法X-Request-ID，不伪造编号", async () => {
  for (const header of [id, "bad"]) {
    const transport = vi
      .fn<FetchImplementation>()
      .mockResolvedValue(
        new Response("<h1>秘密</h1>", { status: 502, headers: { "X-Request-ID": header } }),
      );
    await expect(
      createProblemFetch(transport)(new Request("http://localhost/api/health")),
    ).rejects.toMatchObject({
      message: "请求失败",
      cause: { ...fallback, ...(header === id ? { errorId: id } : {}) },
    });
  }
});

it("验证契约：createProblemFetch 透传Request及AbortSignal，不增加重试或计时器", async () => {
  const controller = new AbortController();
  const request = new Request("http://localhost/api/health", { signal: controller.signal });
  const transport = vi.fn<FetchImplementation>().mockResolvedValue(new Response("ok"));
  await createProblemFetch(transport)(request);
  expect(transport).toHaveBeenCalledExactlyOnceWith(request);
  controller.abort();
  expect(request.signal.aborted).toBe(true);
});

it("验证契约：toFailureView 合法Error.cause的problem和unavailable保持内容与编号", () => {
  for (const cause of [
    { kind: "problem", problem: problem() },
    { ...fallback, errorId: id },
  ]) {
    expect(toFailureView(new Error("不使用", { cause }))).toEqual(cause);
  }
});

it("验证契约：toFailureView null/undefined/原始JSON/任意异常/恶意getter均返回固定无编号兜底", () => {
  const hostile = new Error("敏感");
  Object.defineProperty(hostile, "cause", {
    get() {
      throw new Error("getter");
    },
  });
  for (const value of [null, undefined, problem(), new Error("<h1>敏感</h1>"), hostile]) {
    expect(toFailureView(value)).toEqual(fallback);
  }
});

it("验证契约：toFailureView 不显示error.message或HTML，不改输入或页面URL，不发请求或记日志", () => {
  const url = location.href;
  const error = new Error("<script>secret</script>");
  expect(toFailureView(error)).toEqual(fallback);
  expect(error.message).toBe("<script>secret</script>");
  expect(location.href).toBe(url);
});

it("验证契约：readProblemResponse 省略type/diagnostics/expected时补齐后端默认值，不把可省略字段误判为必填", async () => {
  const payload = { ...problem() };
  Reflect.deleteProperty(payload, "type");
  Reflect.deleteProperty(payload, "diagnostics");
  expect(await readProblemResponse(response(payload))).toEqual({
    ...payload,
    type: "about:blank",
    diagnostics: [],
  });
  const original = problem();
  const diagnostic = original.diagnostics[0];
  if (!diagnostic) throw new Error("测试缺诊断");
  Reflect.deleteProperty(diagnostic, "expected");
  expect((await readProblemResponse(response(original)))?.diagnostics[0]?.expected).toBeNull();
});

it("验证契约：D1错误链只收非空白文本数组，默认空数组且工具不能报冲突", async () => {
  const d = problem().diagnostics[0];
  for (const error_chain of [null, "bad", [" "], [3]]) {
    expect(
      await readProblemResponse(response({ ...problem(), diagnostics: [{ ...d, error_chain }] })),
    ).toBeNull();
  }
  const missing = { ...d };
  Reflect.deleteProperty(missing, "error_chain");
  expect(
    (await readProblemResponse(response({ ...problem(), diagnostics: [missing] })))?.diagnostics[0]
      ?.error_chain,
  ).toEqual([]);
  expect(
    await readProblemResponse(
      response(
        { ...problem("conflict"), diagnostics: [{ ...d, category: "conflict", source: "工具" }] },
        409,
      ),
    ),
  ).toBeNull();
});
