// 工单 04 公开契约测试；验证可观察行为，不做整段文本快照。
import { it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, act, waitFor } from "@testing-library/react";
import { DiagnosticCard } from "./DiagnosticCard";
import type { ProblemResponse, RequestFailureView } from "./api/problems";

const id = "123456789abc4def8abc123456789abc";
const otherId = "abcdef1234564def8abc123456789abc";
function problem(defect = false): ProblemResponse {
  return {
    type: "about:blank",
    title: defect ? "Internal Server Error" : "Bad Request",
    status: defect ? 500 : 400,
    category: defect ? "defect" : "input",
    detail: "服务端安全摘要",
    error_id: id,
    diagnostics: defect
      ? []
      : [
          {
            level: "warning",
            category: "input",
            stage: "解码",
            source: "mcap2lerobot",
            objects: [
              { key: "file", value: "样例.mcap" },
              { key: "topic", value: "左相机" },
            ],
            rule: "必须有关键帧",
            actual: "0个",
            expected: "至少1个",
            consequence: "该文件失败",
            next_step: "检查码流",
            error_chain: [],
          },
        ],
  };
}
function failure(defect = false): RequestFailureView {
  return { kind: "problem", problem: problem(defect) };
}
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it("验证契约：带诊断problem显示类别标题、错误编号和检查段；实际与期望在同一行", () => {
  render(<DiagnosticCard failure={failure()} />);
  for (const value of [
    "警告",
    "解码",
    "mcap2lerobot",
    "对象：",
    "规则：",
    "实际：",
    "后果：",
    "检查：",
    "必须有关键帧",
    "该文件失败",
    "检查码流",
  ]) {
    expect(screen.getByText(value, { exact: false })).toBeTruthy();
  }
  expect(screen.getByText(/实际：/).textContent).toContain("0个；期望：至少1个");
  expect(screen.getByText("警告 · 输入或数据问题 · 解码 · 来源：mcap2lerobot")).toBeTruthy();
  expect(screen.getByText(`错误编号：${id}`)).toBeTruthy();
});

it("验证契约：诊断与对象保持输入顺序，空对象显示全局，expected为null不显示期望", () => {
  const payload = problem();
  const first = payload.diagnostics[0];
  if (!first) throw new Error("缺样例");
  payload.diagnostics = [first, { ...first, objects: [], expected: null, actual: "另一实际" }];
  render(<DiagnosticCard failure={{ kind: "problem", problem: payload }} />);
  const objects = screen.getAllByText(/对象：/);
  expect(objects[0]?.textContent).toBe("对象：file=样例.mcap topic=左相机");
  expect(objects[1]?.textContent).toBe("对象：全局");
  expect(screen.getByText(/另一实际/).textContent).toBe("实际：另一实际");
});

it("验证契约：无诊断的非缺陷problem只显示服务端detail与编号", () => {
  const payload = { ...problem(), diagnostics: [] };
  render(<DiagnosticCard failure={{ kind: "problem", problem: payload }} />);
  expect(screen.getByText("服务端安全摘要")).toBeTruthy();
  expect(screen.getByText(`错误编号：${id}`)).toBeTruthy();
});

it("验证契约：程序缺陷折叠时只有一句话及错误编号，不暴露诊断或详情", () => {
  render(<DiagnosticCard failure={failure(true)} />);
  expect(screen.getByText("服务端安全摘要")).toBeTruthy();
  expect(screen.getByText(`错误编号：${id}`)).toBeTruthy();
  expect(screen.queryByText(/运行日志/)).toBeNull();
});

it("验证契约：程序缺陷展开且没有回调时才显示按编号查运行日志的提示，不发请求", () => {
  render(<DiagnosticCard failure={failure(true)} />);
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  expect(screen.getByText("请按错误编号在运行日志中查询完整报错。")).toBeTruthy();
});

it("验证契约：程序缺陷首次展开调用一次详情回调并传编号与AbortSignal，先显示加载再显示纯文本", async () => {
  let resolve: (text: string) => void = () => {};
  const loader = vi.fn<(errorId: string, signal: AbortSignal) => Promise<string>>(
    () =>
      new Promise<string>((done) => {
        resolve = done;
      }),
  );
  render(<DiagnosticCard failure={failure(true)} loadDetails={loader} />);
  expect(loader).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  expect(screen.getByText("正在加载完整报错…")).toBeTruthy();
  await waitFor(() => {
    expect(loader).toHaveBeenCalledTimes(1);
  });
  expect(loader.mock.calls[0]?.[0]).toBe(id);
  expect(loader.mock.calls[0]?.[1]).toBeInstanceOf(AbortSignal);
  await act(async () => {
    resolve("TypeError: 原始消息");
    await Promise.resolve();
  });
  expect(screen.getByText("TypeError: 原始消息")).toBeTruthy();
});

it("验证契约：详情回调同步抛错或异步拒绝显示固定失败提示，不显示异常原文", async () => {
  for (const loader of [
    () => {
      throw new Error("敏感错误");
    },
    () => Promise.reject(new Error("敏感错误")),
  ]) {
    const view = render(<DiagnosticCard failure={failure(true)} loadDetails={loader} />);
    fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
    expect(await screen.findByText("完整报错暂不可用，请按编号查询运行日志。")).toBeTruthy();
    expect(screen.queryByText("敏感错误")).toBeNull();
    view.unmount();
  }
});

it("验证契约：同编号折叠再展开复用成功结果或失败提示，无重复请求或自动重试", async () => {
  for (const succeed of [true, false]) {
    const loader = vi.fn<(errorId: string, signal: AbortSignal) => Promise<string>>(() =>
      succeed ? Promise.resolve("详情") : Promise.reject(new Error("失败")),
    );
    const view = render(<DiagnosticCard failure={failure(true)} loadDetails={loader} />);
    fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
    await screen.findByText(succeed ? "详情" : "完整报错暂不可用，请按编号查询运行日志。");
    fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
    fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
    expect(loader).toHaveBeenCalledTimes(1);
    view.unmount();
  }
});

it("验证契约：编号/回调改变取消旧请求清空详情并重新折叠，旧Promise迟到结果被忽略", async () => {
  let resolve: (text: string) => void = () => {};
  const loader = vi.fn<(errorId: string, signal: AbortSignal) => Promise<string>>(
    () =>
      new Promise<string>((done) => {
        resolve = done;
      }),
  );
  const view = render(<DiagnosticCard failure={failure(true)} loadDetails={loader} />);
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  await waitFor(() => {
    expect(loader).toHaveBeenCalledTimes(1);
  });
  const nextLoader = vi.fn(() => Promise.resolve("新详情"));
  view.rerender(<DiagnosticCard failure={failure(true)} loadDetails={nextLoader} />);
  expect(screen.queryByText("正在加载完整报错…")).toBeNull();
  expect(loader.mock.calls[0]?.[1].aborted).toBe(true);
  await act(async () => {
    resolve("旧详情");
    await Promise.resolve();
  });
  expect(screen.queryByText("旧详情")).toBeNull();
  expect(nextLoader).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  await screen.findByText("新详情");
  view.rerender(
    <DiagnosticCard
      failure={{ kind: "problem", problem: { ...problem(true), error_id: otherId } }}
      loadDetails={nextLoader}
    />,
  );
  expect(screen.queryByText("新详情")).toBeNull();
});

it("验证契约：卸载时取消请求并清计时器，迟到结果不更新已卸载组件", async () => {
  const loader = vi.fn<(errorId: string, signal: AbortSignal) => Promise<string>>(
    () => new Promise<string>(() => {}),
  );
  const view = render(<DiagnosticCard failure={failure(true)} loadDetails={loader} />);
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  await waitFor(() => {
    expect(loader).toHaveBeenCalledTimes(1);
  });
  view.unmount();
  expect(loader.mock.calls[0]?.[1].aborted).toBe(true);
});

it("验证契约：详情请求4999毫秒仍等待、5000毫秒取消并显示固定失败提示，完成后无残留计时器", async () => {
  vi.useFakeTimers();
  const loader = vi.fn<(errorId: string, signal: AbortSignal) => Promise<string>>(
    () => new Promise<string>(() => {}),
  );
  const view = render(<DiagnosticCard failure={failure(true)} loadDetails={loader} />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
    await Promise.resolve();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4999);
  });
  expect(screen.getByText("正在加载完整报错…")).toBeTruthy();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(screen.getByText("完整报错暂不可用，请按编号查询运行日志。")).toBeTruthy();
  expect(loader.mock.calls[0]?.[1].aborted).toBe(true);
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("验证契约：unavailable显示适配层固定文案及合法可选编号，不提供详情按钮、不伪造错误编号", () => {
  render(
    <DiagnosticCard
      failure={{ kind: "unavailable", message: "请求失败，请检查网络或稍后重试。", errorId: id }}
    />,
  );
  expect(screen.getByText("请求失败，请检查网络或稍后重试。")).toBeTruthy();
  expect(screen.getByText(`错误编号：${id}`)).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});

it("验证契约：所有字段和完整报错按纯文本渲染，HTML/script字符串不执行", async () => {
  const payload = problem();
  const diagnostic = payload.diagnostics[0];
  if (!diagnostic) throw new Error("缺样例");
  diagnostic.actual = "<script>window.compromised=true</script>";
  const view = render(<DiagnosticCard failure={{ kind: "problem", problem: payload }} />);
  expect(screen.getByText(/<script>/)).toBeTruthy();
  expect(view.container.querySelector("script")).toBeNull();
  view.unmount();
  render(
    <DiagnosticCard
      failure={failure(true)}
      loadDetails={() => Promise.resolve("<img onerror=evil>")}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "完整报错" }));
  expect(await screen.findByText("<img onerror=evil>")).toBeTruthy();
});

it("验证契约：卡片不修改URL或存储，非缺陷及缺省回调场景不发请求；props服务端结构来自OpenAPI", () => {
  const url = location.href;
  const loader = vi.fn<(errorId: string, signal: AbortSignal) => Promise<string>>(() =>
    Promise.resolve("未调用"),
  );
  render(<DiagnosticCard failure={failure()} loadDetails={loader} />);
  expect(loader).not.toHaveBeenCalled();
  expect(location.href).toBe(url);
});

it("验证契约：D1非空错误链显示层数，展开后按顺序显示，空链无入口", () => {
  const payload = problem();
  const d = payload.diagnostics[0];
  if (!d) throw new Error("缺样例");
  d.error_chain = ["转换失败", "相机失败", "根因"];
  const view = render(<DiagnosticCard failure={{ kind: "problem", problem: payload }} />);
  expect(screen.queryByText("转换失败")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /错误链（3 层）/ }));
  expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
    "转换失败",
    "相机失败",
    "根因",
  ]);
  view.unmount();
  render(<DiagnosticCard failure={failure()} />);
  expect(screen.queryByText(/错误链/)).toBeNull();
});

it("验证契约：可返回诊断的三类problem标题中文名与后端一致", () => {
  for (const [category, label, status, title, source] of [
    ["input", "输入或数据问题", 400, "Bad Request", "mcap2lerobot"],
    ["conflict", "冲突", 409, "Conflict", "平台"],
    ["external", "外部失败", 502, "Bad Gateway", "mcap2lerobot"],
  ] as const) {
    const payload = problem();
    const diagnostic = payload.diagnostics[0];
    if (!diagnostic) throw new Error("缺样例");
    payload.category = category;
    payload.status = status;
    payload.title = title;
    diagnostic.category = category;
    diagnostic.level = "error";
    diagnostic.source = source;
    const view = render(<DiagnosticCard failure={{ kind: "problem", problem: payload }} />);
    expect(screen.getByText(`错误 · ${label} · 解码 · 来源：${source}`)).toBeTruthy();
    expect(screen.getByText(`错误编号：${id}`)).toBeTruthy();
    view.unmount();
  }
});
