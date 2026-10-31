// M1.5-01：真实Router、Query与HTTP边界验证目录导航和原生视频，不替换内部组件。
import { it, expect, vi } from "vitest";
import { fireEvent, screen, within, waitFor } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { datasetFetch, detail, taskEntry } from "./testSupport";
import type { DatasetDetail } from "../api/datasets";

const viewerDetail: DatasetDetail = {
  ...detail,
  links: [
    {
      ordinal: 0,
      name: "原始数据",
      source_path: "/temporary/roots/data",
      source_type: "directory",
      derived_entry_path: "按任务/libero_10/原始数据",
      observed_target: "/temporary/roots/data",
      storage_root_name: "dataset1",
      status: "available",
      checked_at: "2026-10-30T08:00:00Z",
      size_bytes: null,
      size_checked_at: null,
    },
  ],
};

// 契约：打开后先选登记链接，逐级浏览再预览；视频用同源src和controls，由浏览器请求Range。
it("从详情选择链接、浏览目录并播放视频", async () => {
  const requests: Request[] = [];
  const fallback = datasetFetch(requests);
  const page = mountPage(
    `/datasets?selected=${encodeURIComponent(taskEntry.entry_path)}`,
    async (request) => {
      const url = new URL(request.url);
      if (url.pathname === "/api/datasets/detail") return Response.json(viewerDetail);
      if (url.pathname.endsWith("/files")) {
        requests.push(request);
        return Response.json({
          items: [
            {
              name: url.searchParams.get("path") ? "clip.mp4" : "videos",
              kind: url.searchParams.get("path") ? "file" : "directory",
              size_bytes: 10,
              modified_at: "2026-10-30T08:00:00Z",
            },
          ],
          offset: 0,
          limit: 100,
          has_more: false,
        });
      }
      return fallback(request);
    },
  );
  try {
    fireEvent.click(await screen.findByRole("button", { name: "查看原文件" }));
    const area = await screen.findByRole("region", { name: "原文件查看器" });
    expect(
      requests.filter((request) => new URL(request.url).pathname.endsWith("/files")),
    ).toHaveLength(0);
    fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择原文件链接" }));
    fireEvent.click(await screen.findByRole("option", { name: "原始数据" }));
    fireEvent.click(await within(area).findByRole("button", { name: "打开目录 videos" }));
    fireEvent.click(await within(area).findByRole("button", { name: "预览文件 clip.mp4" }));
    await waitFor(() => {
      expect(within(area).getByLabelText("原文件视频")).toBeTruthy();
    });
    const video = within(area).getByLabelText("原文件视频");
    expect(video.tagName).toBe("VIDEO");
    expect(video.hasAttribute("controls")).toBe(true);
    const src = new URL(video.getAttribute("src") ?? "", "http://localhost");
    expect(src.pathname).toBe("/api/datasets/dataset-14/file");
    expect(src.searchParams.get("path")).toBe("videos/clip.mp4");
    expect(src.searchParams.get("link_name")).toBe("原始数据");
    fireEvent.click(within(area).getByRole("button", { name: "原文件上一级" }));
    expect(await within(area).findByRole("button", { name: "打开目录 videos" })).toBeTruthy();
    expect(within(area).queryByLabelText("原文件视频")).toBeNull();
  } finally {
    page.close();
  }
});

// 契约：文本保留换行，JSON按原文交Worker格式化，图片使用同源原字节URL；不发写请求。
it("文本、JSON和图片分别使用只读预览", async () => {
  const requests: Request[] = [];
  const messages: unknown[] = [];
  vi.stubGlobal(
    "Worker",
    class {
      onmessage: ((event: MessageEvent) => void) | null = null;
      terminate() {
        /* 测试边界无后台资源。 */
      }
      postMessage(message: unknown) {
        messages.push(message);
        queueMicrotask(() =>
          this.onmessage?.(
            new MessageEvent("message", {
              data: { text: '{\n  "x": 1\n}', page: 0, totalPages: 1, valid: true },
            }),
          ),
        );
      }
    },
  );
  const fallback = datasetFetch(requests);
  const page = mountPage(
    `/datasets?selected=${encodeURIComponent(taskEntry.entry_path)}`,
    async (request) => {
      const url = new URL(request.url);
      if (url.pathname === "/api/datasets/detail") return Response.json(viewerDetail);
      if (url.pathname.endsWith("/files")) {
        requests.push(request);
        return Response.json({
          items: ["note.txt", "info.json", "photo.png"].map((name) => ({
            name,
            kind: "file",
            size_bytes: 10,
            modified_at: "2026-10-30T08:00:00Z",
          })),
          offset: 0,
          limit: 100,
          has_more: false,
        });
      }
      if (url.pathname.endsWith("/file")) {
        requests.push(request);
        return new Response(
          url.searchParams.get("path") === "info.json" ? '{"x":1}' : "首行\n末行",
        );
      }
      return fallback(request);
    },
  );
  try {
    fireEvent.click(await screen.findByRole("button", { name: "查看原文件" }));
    const area = await screen.findByRole("region", { name: "原文件查看器" });
    fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择原文件链接" }));
    fireEvent.click(await screen.findByRole("option", { name: "原始数据" }));
    fireEvent.click(await within(area).findByRole("button", { name: "预览文件 note.txt" }));
    expect((await within(area).findByText("首行 末行")).textContent).toBe("首行\n末行");
    fireEvent.click(within(area).getByRole("button", { name: "预览文件 info.json" }));
    await within(area).findByRole("region", { name: "原文件 JSON" });
    await waitFor(() => {
      expect(messages).toEqual([{ type: "load", text: '{"x":1}', format: true }]);
    });
    fireEvent.click(within(area).getByRole("button", { name: "预览文件 photo.png" }));
    const image = within(area).getByRole("img", { name: "原文件图片" });
    expect(image.getAttribute("src")).toContain("path=photo.png");
    expect(requests.every((request) => request.method === "GET")).toBe(true);
  } finally {
    page.close();
    vi.unstubAllGlobals();
  }
});

// 契约：原生媒体控件失败后用有界Range探针取得接口诊断，离线不能只显示浏览器的无详情失败。
it("视频读取失败展示服务端五段诊断", async () => {
  const requests: Request[] = [];
  const fallback = datasetFetch(requests);
  const page = mountPage(
    `/datasets?selected=${encodeURIComponent(taskEntry.entry_path)}`,
    async (request) => {
      const url = new URL(request.url);
      if (url.pathname === "/api/datasets/detail") return Response.json(viewerDetail);
      if (url.pathname.endsWith("/files"))
        return Response.json({
          items: [
            { name: "clip.mp4", kind: "file", size_bytes: 10, modified_at: "2026-10-30T08:00:00Z" },
          ],
          offset: 0,
          limit: 100,
          has_more: false,
        });
      if (url.pathname.endsWith("/video")) {
        requests.push(request);
        return Response.json(
          {
            type: "about:blank",
            title: "Bad Gateway",
            status: 502,
            category: "external",
            detail: "外部服务或工具失败，请查看诊断。",
            error_id: "00000000000040008000000000000000",
            diagnostics: [
              {
                level: "error",
                category: "external",
                stage: "原文件只读查看",
                source: "平台",
                objects: [],
                rule: "FILE_VIEWER_STORAGE",
                actual: "fixture-storage-timeout",
                expected: "存储在线",
                consequence: "读取停止",
                next_step: "恢复挂载后重试",
                error_chain: [],
              },
            ],
          },
          { status: 502, headers: { "Content-Type": "application/problem+json" } },
        );
      }
      return fallback(request);
    },
  );
  try {
    fireEvent.click(await screen.findByRole("button", { name: "查看原文件" }));
    const area = await screen.findByRole("region", { name: "原文件查看器" });
    fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择原文件链接" }));
    fireEvent.click(await screen.findByRole("option", { name: "原始数据" }));
    fireEvent.click(await within(area).findByRole("button", { name: "预览文件 clip.mp4" }));
    fireEvent.error(within(area).getByLabelText("原文件视频"));
    fireEvent.error(within(area).getByLabelText("原文件视频"));
    expect(await within(area).findByText(/fixture-storage-timeout/)).toBeTruthy();
    expect(within(area).getByText(/恢复挂载后重试/)).toBeTruthy();
    expect(requests.some((request) => new URL(request.url).pathname.endsWith("/video"))).toBe(true);
  } finally {
    page.close();
  }
});

// 契约：AV1能力探测不支持或原生播放失败时自动切转码，并按60秒分段跳转。
it.each(["unsupported", "error"])("视频%s自动转码并按段跳转", async (reason) => {
  const capability = vi
    .spyOn(HTMLMediaElement.prototype, "canPlayType")
    .mockReturnValue(reason === "unsupported" ? "" : "probably");
  const requests: Request[] = [];
  const fallback = datasetFetch(requests);
  const page = mountPage(
    `/datasets?selected=${encodeURIComponent(taskEntry.entry_path)}`,
    async (request) => {
      const url = new URL(request.url);
      if (url.pathname === "/api/datasets/detail") return Response.json(viewerDetail);
      if (url.pathname.endsWith("/files"))
        return Response.json({
          items: [
            { name: "clip.mp4", kind: "file", size_bytes: 10, modified_at: "2026-10-30T08:00:00Z" },
          ],
          offset: 0,
          limit: 100,
          has_more: false,
        });
      if (url.pathname.endsWith("/video-info"))
        return Response.json({ codec: "av1", duration_s: 150 });
      return fallback(request);
    },
  );
  try {
    fireEvent.click(await screen.findByRole("button", { name: "查看原文件" }));
    const area = await screen.findByRole("region", { name: "原文件查看器" });
    fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择原文件链接" }));
    fireEvent.click(await screen.findByRole("option", { name: "原始数据" }));
    fireEvent.click(await within(area).findByRole("button", { name: "预览文件 clip.mp4" }));
    if (reason === "error") fireEvent.error(within(area).getByLabelText("原文件视频"));
    await waitFor(() => {
      expect(within(area).getByLabelText("原文件视频").getAttribute("src")).toContain("/video?");
    });
    expect(await within(area).findByText(/av1.*150/)).toBeTruthy();
    expect(within(area).getByText(/转码播放/)).toBeTruthy();
    fireEvent.click(within(area).getByRole("button", { name: "视频下一段" }));
    expect(within(area).getByLabelText("原文件视频").getAttribute("src")).toContain("start_s=60");
    fireEvent.click(within(area).getByRole("button", { name: "视频上一段" }));
    expect(within(area).getByLabelText("原文件视频").getAttribute("src")).toContain("start_s=0");
    expect(within(area).getByRole("slider", { name: "视频起点" })).toBeTruthy();
  } finally {
    page.close();
    capability.mockRestore();
  }
});

// 契约：parquet先展示结构与计数，按200行翻页，截断单元格明确标注，宽表自带滚动容器。
it("parquet显示表结构、截断标记并分页", async () => {
  const requests: Request[] = [];
  const fallback = datasetFetch(requests);
  const page = mountPage(
    `/datasets?selected=${encodeURIComponent(taskEntry.entry_path)}`,
    async (request) => {
      const url = new URL(request.url);
      if (url.pathname === "/api/datasets/detail") return Response.json(viewerDetail);
      if (url.pathname.endsWith("/files"))
        return Response.json({
          items: [
            {
              name: "data.parquet",
              kind: "file",
              size_bytes: 10,
              modified_at: "2026-10-30T08:00:00Z",
            },
          ],
          offset: 0,
          limit: 100,
          has_more: false,
        });
      if (url.pathname.endsWith("/parquet")) {
        requests.push(request);
        const offset = Number(url.searchParams.get("offset"));
        return Response.json({
          columns: [
            { name: "value", type: "int64" },
            { name: "note", type: "string" },
          ],
          total_rows: 201,
          row_groups: 3,
          offset,
          limit: 200,
          rows: [
            [
              { text: offset ? "201" : "17", truncated: false },
              { text: "nested-value", truncated: true },
            ],
          ],
          has_more: offset === 0,
          schema_only: false,
        });
      }
      return fallback(request);
    },
  );
  try {
    fireEvent.click(await screen.findByRole("button", { name: "查看原文件" }));
    const area = await screen.findByRole("region", { name: "原文件查看器" });
    fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择原文件链接" }));
    fireEvent.click(await screen.findByRole("option", { name: "原始数据" }));
    fireEvent.click(await within(area).findByRole("button", { name: "预览文件 data.parquet" }));
    const preview = await within(area).findByRole("region", { name: "parquet预览" });
    expect(await within(preview).findByText("int64")).toBeTruthy();
    expect(within(preview).getByText(/总行数：201.*行组：3/)).toBeTruthy();
    expect(within(preview).getByText(/nested-value.*已截断/)).toBeTruthy();
    expect(within(preview).getByRole("region", { name: "parquet数据表格" })).toBeTruthy();
    fireEvent.click(within(preview).getByRole("button", { name: "parquet下一页" }));
    await waitFor(() => {
      expect(
        requests.some((request) => new URL(request.url).searchParams.get("offset") === "200"),
      ).toBe(true);
    });
    expect(
      requests
        .filter((request) => new URL(request.url).pathname.endsWith("/parquet"))
        .every((request) => new URL(request.url).searchParams.get("limit") === "200"),
    ).toBe(true);
  } finally {
    page.close();
  }
});
