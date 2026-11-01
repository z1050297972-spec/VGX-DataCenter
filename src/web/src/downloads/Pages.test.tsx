// 下载页面使用真实内存 Router 和注入传输，不访问网络或存储根。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createAppRouter } from "../router";
import { account } from "../accounts/testSupport";
import { completedJob, onlineWorker } from "../jobs/testSupport";
import type { FetchImplementation } from "../api/client";

beforeEach(() => {
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) => computed(element));
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    },
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function mount(path: string, fetchImpl: FetchImplementation) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createAppRouter({
    queryClient,
    history: createMemoryHistory({ initialEntries: [path] }),
    fetchImpl,
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return {
    router,
    close: () => {
      view.unmount();
      queryClient.clear();
      router.history.destroy();
    },
  };
}

const preview = {
  commit: "a".repeat(40),
  created_at: "2026-11-01T00:00:00Z",
  file_count: 10,
  sufficient: true,
  dataset: {
    episodes: 3,
    frames: 42,
    fps: 30,
    robot_type: "robot",
    codebase_version: "v2.1",
    cameras: ["front", "side"],
  },
  capacity: {
    selected_bytes: 1000,
    complete_bytes: 100,
    remaining_bytes: 900,
    available_bytes: 5000,
    reserve_bytes: 1000,
  },
};
function transport(request: Request): Promise<Response> {
  const path = new URL(request.url).pathname;
  if (path === "/api/auth/me")
    return Promise.resolve(Response.json({ ...account, role: "member" }));
  if (path === "/api/worker/status") return Promise.resolve(Response.json(onlineWorker));
  if (path === "/api/storage-roots")
    return Promise.resolve(
      Response.json({
        items: [
          {
            name: "read",
            writable: false,
            online: true,
            reason: null,
            path: "/test/read",
            checked_at: preview.created_at,
          },
          {
            name: "write",
            writable: true,
            online: true,
            reason: null,
            path: "/test/write",
            checked_at: preview.created_at,
          },
        ],
        checked_at: preview.created_at,
      }),
    );
  if (path === "/api/jobs/download-staging-scan" && request.method === "POST")
    return Promise.resolve(
      Response.json(
        { ...completedJob, job_id: "43", type_name: "download_staging_scan" },
        { status: 201 },
      ),
    );
  if (path === "/api/jobs/43")
    return Promise.resolve(
      Response.json({ ...completedJob, job_id: "43", type_name: "download_staging_scan" }),
    );
  if (path === "/api/jobs/43/download-staging")
    return Promise.resolve(
      Response.json({
        created_at: preview.created_at,
        items: [
          {
            storage_root: "write",
            repo_type: "dataset",
            repo_id: "org/repo",
            commit_prefix: "bbbbbbbbbbbb",
            size_bytes: 123,
            modified_at: preview.created_at,
            in_use: true,
          },
        ],
      }),
    );
  if (path === "/api/jobs/42/download-preview") return Promise.resolve(Response.json(preview));
  if (path === "/api/jobs/42")
    return Promise.resolve(
      Response.json({ ...completedJob, job_id: "42", type_name: "download_preview" }),
    );
  return Promise.resolve(Response.json({}));
}

it("表单默认隐藏高级参数，展开后显示默认值和范围", async () => {
  let sent: unknown = null;
  let download: unknown = null;
  let attempts = 0;
  const view = mount("/downloads", async (request) => {
    if (
      new URL(request.url).pathname === "/api/jobs/download-preview" &&
      request.method === "POST"
    ) {
      sent = await request.json();
      attempts += 1;
      if (attempts === 1)
        return Response.json(
          {
            type: "about:blank",
            title: "Unprocessable Entity",
            status: 422,
            detail: "请求参数不符合要求，请查看诊断。",
            category: "input",
            error_id: "00000000000040008000000000000000",
            diagnostics: [
              {
                level: "error",
                category: "input",
                stage: "请求校验",
                source: "平台",
                objects: [{ key: "field", value: "body.max_connection_per_server" }],
                rule: "请求字段必须满足接口声明",
                actual: "字段缺失或格式不符合要求（原值不回显）",
                expected: "符合接口声明的类型和约束",
                consequence: "请求被拒绝，操作未执行",
                next_step: "对照接口字段定义修正后重试",
                error_chain: [],
              },
            ],
          },
          { status: 422, headers: { "Content-Type": "application/problem+json" } },
        );
      return Response.json(
        { ...completedJob, job_id: "42", type_name: "download_preview" },
        { status: 201 },
      );
    }
    if (new URL(request.url).pathname === "/api/jobs/download" && request.method === "POST") {
      download = await request.json();
      return Response.json(
        { ...completedJob, job_id: "43", type_name: "download" },
        { status: 201 },
      );
    }
    return transport(request);
  });
  try {
    expect(await screen.findByRole("heading", { name: "下载" })).toBeTruthy();
    expect(screen.queryByLabelText("同时下几个文件")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "高级参数" }));
    expect(screen.getByLabelText("同时下几个文件")).toHaveProperty("value", "4");
    expect(screen.getByLabelText("每服务器连接数")).toHaveProperty("value", "4");
    expect(screen.getByLabelText("每文件分段数")).toHaveProperty("value", "4");
    expect(screen.getByLabelText("最小分段大小（MiB）")).toHaveProperty("value", "20");
    expect(screen.getByLabelText("重试次数")).toHaveProperty("value", "5");
    expect(screen.getByLabelText("重试间隔（秒）")).toHaveProperty("value", "10");
    expect(screen.getAllByText(/1–16/).length).toBe(3);
    expect(screen.getByText(/1–1024 MiB/)).toBeTruthy();
    expect(screen.getByText(/1–20/)).toBeTruthy();
    expect(screen.getByText(/0–600 秒/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "高级参数" }));
    fireEvent.change(screen.getByLabelText("仓库编号"), { target: { value: "lerobot/pusht" } });
    fireEvent.mouseDown(screen.getByLabelText("目标存储根"));
    fireEvent.click(await screen.findByTitle("write"));
    fireEvent.click(screen.getByRole("button", { name: "预览" }));
    expect(await screen.findByText("服务器校验未通过，请检查范围。")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("每服务器连接数"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "预览" }));
    await waitFor(() => {
      expect(attempts).toBe(2);
      expect(sent).toMatchObject({
        repo_id: "lerobot/pusht",
        storage_root: "write",
        min_split_size_bytes: 20971520,
        max_concurrent_downloads: 4,
        max_overall_download_limit_bytes_per_s: 0,
      });
    });
    expect(await screen.findByText(/aaaaaaaaaaaaaaaa/)).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "确认下载" })).toHaveProperty("disabled", false);
    });
    fireEvent.click(screen.getByRole("button", { name: "确认下载" }));
    await waitFor(() => {
      expect(download).toEqual(sent);
    });
  } finally {
    view.close();
  }
});

it("预览展示版本、数据集元数据和容量快照", async () => {
  const view = mount('/downloads?preview_job_id="42"', transport);
  try {
    expect(await screen.findByText(/aaaaaaaaaaaaaaaa/)).toBeTruthy();
    expect(screen.getByText(/episode：3/)).toBeTruthy();
    expect(screen.getByText(/帧数：42/)).toBeTruthy();
    expect(screen.getByText(/FPS：30/)).toBeTruthy();
    expect(screen.getByText(/已完整下载（续传中的不计）：100/)).toBeTruthy();
    expect(screen.getByText(/剩余空间：5000/)).toBeTruthy();
    expect(screen.getByText("front")).toBeTruthy();
    // 刷新必须先提交 worker 扫描，再读取数据库快照，保留预览 search。
    fireEvent.click(screen.getByRole("button", { name: "刷新暂存列表" }));
    expect(await screen.findByText("org/repo")).toBeTruthy();
    expect(screen.getByText("bbbbbbbbbbbb")).toBeTruthy();
    expect(screen.getByText("使用中")).toBeTruthy();
    expect(screen.getByText(/生成时间/)).toBeTruthy();
    expect(view.router.state.location.search.preview_job_id).toBe("42");
    expect(view.router.state.location.search.staging_job_id).toBe("43");
  } finally {
    view.close();
  }
});

it("真实 Router 解析 preview_job_id 并按编号读取预览", async () => {
  const requests: string[] = [];
  const view = mount('/downloads?preview_job_id="42"', (request) => {
    requests.push(new URL(request.url).pathname);
    return transport(request);
  });
  try {
    expect(await screen.findByText(/aaaaaaaaaaaaaaaa/)).toBeTruthy();
    expect(requests).toContain("/api/jobs/42/download-preview");
    expect(view.router.state.location.pathname).toBe("/downloads");
  } finally {
    view.close();
  }
});

it("管理员删除暂存前必须确认，取消不发送请求，使用中目录不能删除", async () => {
  // 删除行为必须以实际 worker 作业返回为准，不能乐观删除快照行。
  const deletes: unknown[] = [];
  const view = mount('/downloads?staging_job_id="43"', async (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/auth/me") return Response.json({ ...account, role: "administrator" });
    if (path === "/api/jobs/43/download-staging")
      return Response.json({
        created_at: preview.created_at,
        items: [
          {
            storage_root: "write",
            repo_type: "dataset",
            repo_id: "org/busy",
            commit_prefix: "aaaaaaaaaaaa",
            size_bytes: 9,
            modified_at: preview.created_at,
            in_use: true,
          },
          {
            storage_root: "write",
            repo_type: "dataset",
            repo_id: "org/free",
            commit_prefix: "bbbbbbbbbbbb",
            size_bytes: 123,
            modified_at: preview.created_at,
            in_use: false,
          },
        ],
      });
    if (path === "/api/jobs/download-staging-delete" && request.method === "POST") {
      deletes.push(await request.json());
      return Response.json(
        { ...completedJob, job_id: "44", type_name: "download_staging_delete" },
        { status: 201 },
      );
    }
    return transport(request);
  });
  try {
    expect(await screen.findByText("org/free")).toBeTruthy();
    expect(screen.getByRole("button", { name: "删除 org/busy" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "删除 org/free" }));
    expect(await screen.findByText("确认删除暂存目录？")).toBeTruthy();
    expect(deletes).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "取消删除" }));
    expect(deletes).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "删除 org/free" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认删除" }));
    await waitFor(() => {
      expect(deletes).toEqual([
        {
          storage_root: "write",
          repo_type: "dataset",
          repo_id: "org/free",
          commit_prefix: "bbbbbbbbbbbb",
        },
      ]);
    });
    expect(await screen.findByText("已提交清理作业，目录是否删除以作业结果为准。")).toBeTruthy();
    expect(screen.getByText("org/free")).toBeTruthy();
    expect(screen.getByRole("link", { name: "查看清理作业 #44" }).getAttribute("href")).toBe(
      "/jobs/44",
    );
  } finally {
    view.close();
  }
  // 成员可查看快照，但页面不暴露删除入口；服务端仍独立鉴权。
  const member = mount('/downloads?staging_job_id="43"', transport);
  try {
    expect(await screen.findByText("org/repo")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "删除 org/repo" })).toBeNull();
  } finally {
    member.close();
  }
});

it("成功的数据集下载可入库，预览的名字和同根位置可改，确认后进入写入作业", async () => {
  // 验收 5：通过真实路由和请求边界检查入库入口、worker 预览和重新预览后的确认。
  const sent: unknown[] = [];
  const download = {
    ...completedJob,
    job_id: "50",
    type_name: "download",
    display_name: "下载",
    parameters: { repo_type: "dataset", repo_id: "org/repo", storage_root: "write" },
  };
  function staticResponse(path: string): Response | null {
    if (path === "/api/jobs/50") return Response.json(download);
    if (path.endsWith("/log"))
      return Response.json({ tail: { status: "cleared", lines: [], truncated: false } });
    if (path === "/api/jobs/50/download-adjustment")
      return Response.json({
        requested_version: 0,
        applied_version: 0,
        requested: { max_concurrent_downloads: 4, max_overall_download_limit_bytes_per_s: 0 },
        effective: { max_concurrent_downloads: 4, max_overall_download_limit_bytes_per_s: 0 },
        speed_bytes_per_s: 0,
        total_files: 2,
        completed_files: 2,
        failed_files: 0,
        skipped_files: 0,
      });
    return null;
  }
  const view = mount("/jobs/50", async (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/jobs/50/download-ingest-preview" && request.method === "POST") {
      sent.push(await request.json());
      return Response.json(
        { ...completedJob, job_id: "82", type_name: "download_ingest_preview" },
        { status: 201 },
      );
    }
    if (path === "/api/jobs/82")
      return Response.json({ ...completedJob, job_id: "82", type_name: "download_ingest_preview" });
    if (path === "/api/jobs/82/download-ingest-preview")
      return Response.json({
        preview_job_id: "82",
        parameters: {
          download_job_id: 50,
          dataset_name: sent.length > 1 ? "入库样本" : "repo",
          target_subdir: sent.length > 1 ? "正式/样本" : "下载/org/repo@aaaaaaaaaaaa",
          format_entries: [{ format: "lerobot", version: "3.0" }],
        },
        fields: { 数据集标识: "org/repo", FPS: "30", 类型与组成: "" },
        checks: ["清单文件齐全且大小一致"],
        notices: ["部分下载：排除了视频"],
        format_entry_options: [{ format: "lerobot", version: "3.0" }],
      });
    if (path === "/api/jobs/download-ingest")
      return Response.json(
        { ...completedJob, job_id: "83", type_name: "download_ingest_apply" },
        { status: 201 },
      );
    if (path === "/api/jobs/83")
      return Response.json({ ...completedJob, job_id: "83", type_name: "download_ingest_apply" });
    return staticResponse(path) ?? transport(request);
  });
  try {
    fireEvent.click(await screen.findByRole("button", { name: "入库" }));
    fireEvent.click(await screen.findByRole("button", { name: "预览入库" }));
    expect(await screen.findByText("清单文件齐全且大小一致")).toBeTruthy();
    expect(screen.getByText("部分下载：排除了视频")).toBeTruthy();
    const name = screen.getByLabelText("入库数据集名");
    const location = screen.getByLabelText("入库存放位置");
    expect(name).toHaveProperty("value", "repo");
    expect(location).toHaveProperty("value", "下载/org/repo@aaaaaaaaaaaa");
    fireEvent.change(name, { target: { value: "入库样本" } });
    fireEvent.change(location, { target: { value: "正式/样本" } });
    expect(screen.getByRole("button", { name: "确认入库" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "预览入库" }));
    await waitFor(() => {
      expect(sent).toHaveLength(2);
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "确认入库" })).toHaveProperty("disabled", false);
    });
    fireEvent.click(screen.getByRole("button", { name: "确认入库" }));
    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe("/jobs/83");
    });
    expect(sent[1]).toMatchObject({ dataset_name: "入库样本", target_subdir: "正式/样本" });
  } finally {
    view.close();
  }
});
