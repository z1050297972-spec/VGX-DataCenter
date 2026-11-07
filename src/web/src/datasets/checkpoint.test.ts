// M1-04 后半段验收：真实 Router 和 HTTP 边界替身验证用户可见行为，不访问真实数据。
import { formatDateTime } from "../time";
import { describe, it, expect } from "vitest";
import { screen, within, fireEvent, waitFor, act } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { completedJob } from "../jobs/testSupport";
import { datasetFetch, detail, panel, taskEntry, filters, datasets } from "./testSupport";
import type { FetchImplementation } from "../api/client";
import type { DatasetDetail } from "../api/datasets";

const selectedUrl = `/datasets?selected=${encodeURIComponent(taskEntry.entry_path)}`;
const offlineLink: DatasetDetail["links"][number] = {
  name: "data",
  ordinal: 0,
  derived_entry_path: "按任务/libero_10/data",
  source_path: "/fake/disk/data",
  source_type: "directory",
  observed_target: "/fake/disk/data",
  storage_root_name: "disk",
  status: "offline",
  checked_at: "2026-10-29T12:00:00Z",
  size_bytes: 4096,
  size_checked_at: "2026-10-28T12:00:00Z",
};

// 仅替换 HTTP 响应；客户端、查询生命周期和真实路由照常执行。
function transport(
  overrides: Record<string, (request: Request) => Response | Promise<Response>>,
  requests: Request[] = [],
): FetchImplementation {
  const fallback = datasetFetch(requests);
  return (request) => {
    const handler = overrides[new URL(request.url).pathname];
    if (!handler) return fallback(request);
    requests.push(request);
    return Promise.resolve(handler(request));
  };
}

describe("数据集后半段验收", () => {
  // 验收3：离线状态由索引明确提供；旧统计值及原统计时间保留，不能误报断链。
  it("存储根离线时顶部提示、链接标存储根离线并保留旧大小", async () => {
    const page = mountPage(
      selectedUrl,
      transport({
        "/api/datasets/panel": () =>
          Response.json({
            ...panel,
            storage_roots: [
              {
                name: "disk",
                path: "/fake/disk",
                online: false,
                reason: "timeout",
                checked_at: "2026-10-29T12:00:00Z",
              },
            ],
          }),
        "/api/datasets/detail": () =>
          Response.json({
            ...detail,
            links: [offlineLink],
            dataset_size: {
              ...detail.dataset_size,
              size_bytes: 4096,
              size_checked_at: "2026-10-28T12:00:00Z",
              display_bytes: 4096,
              display_source: "measured",
            },
          }),
      }),
    );
    try {
      expect(
        await screen.findByText("存储根 disk 离线：访问超时；其下磁盘检查已跳过"),
      ).toBeTruthy();
      const links = await screen.findByRole("region", { name: "链接状态" });
      expect(within(links).getByText("存储根离线")).toBeTruthy();
      expect(within(links).queryByText("断链")).toBeNull();
      expect(
        screen.getByText(/统计大小：4.10 KB · LeRobot 只计 parquet、mp4 和 meta/),
      ).toBeTruthy();
      expect(screen.getByText(`统计时间：${formatDateTime("2026-10-28T12:00:00Z")}`)).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 验收4：详情指纹使页面过期；重扫只用永久编号。
  it("详情发现索引过期时显示重新扫描并提交单数据集作业", async () => {
    const requests: Request[] = [];
    const page = mountPage(
      selectedUrl,
      transport(
        {
          "/api/datasets/detail": () => Response.json({ ...detail, index_stale: true }),
          "/api/datasets/dataset-14/rescan": () => Response.json(completedJob, { status: 201 }),
        },
        requests,
      ),
    );
    try {
      await screen.findByRole("heading", { name: "libero_10" });
      expect(await screen.findByText("索引过期")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "重新扫描" }));
      expect(
        await screen.findByRole("region", { name: `重新检查 #${completedJob.job_id}` }),
      ).toBeTruthy();
      expect(page.router.state.location.pathname).toBe("/datasets");
      expect(
        requests
          .filter((request) => request.method === "POST")
          .map((request) => new URL(request.url).pathname),
      ).toEqual(["/api/datasets/dataset-14/rescan"]);
    } finally {
      page.close();
    }
  });
  // 第15张验收：只有一个型号下拉，候选含计数与未标注；真实路由和请求使用 robot_model。
  it("型号筛选统一使用导航信息，显示说明并支持未标注", async () => {
    const requests: Request[] = [];
    const page = mountPage(
      "/datasets?offset=20",
      transport(
        {
          "/api/datasets/filters": () =>
            Response.json({
              ...filters,
              robot_models: [
                { value: "R1 Lite", label: "R1 Lite", count: 1 },
                { value: "unlabeled", label: "未标注", count: 1 },
              ],
            }),
        },
        requests,
      ),
    );
    try {
      const select = await screen.findByRole("combobox", { name: "机器人型号" });
      expect(screen.getAllByRole("combobox", { name: "机器人型号" })).toHaveLength(1);
      expect(screen.queryByRole("combobox", { name: "型号标签" })).toBeNull();
      expect(screen.queryByRole("button", { name: "更多筛选" })).toBeNull();
      expect(
        screen.getByText(
          "筛选以导航层的数据集信息为准，不读原数据文件。与原文件不一致的地方见一致性面板，正式使用数据集前请核对。",
        ),
      ).toBeTruthy();
      for (const [label, value] of [
        ["R1 Lite（1）", "R1 Lite"],
        ["未标注（1）", "unlabeled"],
      ]) {
        fireEvent.mouseDown(select);
        fireEvent.click(await screen.findByRole("option", { name: label }));
        await waitFor(() => {
          expect(page.router.state.location.search).toMatchObject({ robot_model: value });
          expect(page.router.state.location.search.offset).toBeUndefined();
          for (const path of ["/api/datasets", "/api/datasets/trees"]) {
            expect(
              requests.some((request) => {
                const url = new URL(request.url);
                return url.pathname === path && url.searchParams.get("robot_model") === value;
              }),
            ).toBe(true);
          }
        });
      }
      expect(
        requests.every((request) => {
          const params = new URL(request.url).searchParams;
          return !params.has("robot_type") && !params.has("robot_model_id");
        }),
      ).toBe(true);
    } finally {
      page.close();
    }
  });
  // 范围筛选：来源和未知值同时进入 URL/API；翻页和目录选择不得丢失条件。
  it("数据来源与未知值筛选可分享，分页和目录定位保持筛选", async () => {
    const first = datasets.items[0];
    if (!first) throw new Error("缺少测试样本");
    const rows = Array.from({ length: 21 }, (_, index) => ({
      ...first,
      dataset_id: `item-${String(index)}`,
      name: `item-${String(index)}`,
      robot_model: null,
      fps: [null],
    }));
    const requests: Request[] = [];
    const page = mountPage(
      "/datasets?fps=unknown&robot_model=unlabeled",
      transport(
        {
          "/api/datasets": (request) => {
            const offset = Number(new URL(request.url).searchParams.get("offset") ?? 0);
            return Response.json({
              ...datasets,
              offset,
              total: 21,
              items: rows.slice(offset, offset + 20),
            });
          },
        },
        requests,
      ),
    );
    try {
      fireEvent.mouseDown(await screen.findByRole("combobox", { name: "数据来源" }));
      fireEvent.click(await screen.findByRole("option", { name: "未知（2）" }));
      await screen.findByText("共 21 个数据集");
      fireEvent.click(await screen.findByTitle("Next Page"));
      expect(await screen.findByRole("button", { name: "打开 item-20" })).toBeTruthy();
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({
          data_origin: "unknown",
          fps: "unknown",
          robot_model: "unlabeled",
          offset: 20,
        });
      });
      fireEvent.click(screen.getByRole("tab", { name: "按任务" }));
      await waitFor(() => {
        expect(document.querySelector('.dataset-tree-name[title="按任务"]')).not.toBeNull();
      });
      fireEvent.click(document.querySelector('.dataset-tree-name[title="按任务"]') as Element);
      await waitFor(() => {
        expect(
          requests.some((request) => {
            const url = new URL(request.url);
            return (
              url.pathname === "/api/datasets" &&
              url.searchParams.get("entry_path") === "按任务" &&
              url.searchParams.get("data_origin") === "unknown" &&
              url.searchParams.get("fps") === "unknown" &&
              url.searchParams.get("robot_model") === "unlabeled"
            );
          }),
        ).toBe(true);
      });
      expect(page.router.state.location.search.offset).toBeUndefined();
    } finally {
      page.close();
    }
  });
  // 11 Q12：业务信息来自规范副本，Markdown只渲染；未知HTML作为文字，不解析其中的业务值。
  it("规范副本的14项按Markdown渲染，缺失规范副本明确提示", async () => {
    const fields = Array.from({ length: 14 }, (_, index) => ({
      number: index + 1,
      name: `字段${String(index + 1)}`,
      value_markdown:
        index === 0
          ? "**规范副本**、`robot_type`\n\n[资料](https://example.invalid/data) 与 [数据路径](</fake/data>)\n\n<img src=x onerror=alert(1)>"
          : `原文${String(index + 1)}`,
    }));
    const page = mountPage(
      selectedUrl,
      transport({
        "/api/datasets/detail": () =>
          Response.json({
            ...detail,
            canonical_information: {
              ...detail.information,
              content: JSON.stringify({
                dataset_id: "dataset-14",
                snapshot_date: "2026-10-12",
                fields,
              }),
            },
          }),
      }),
    );
    try {
      const info = await screen.findByRole("region", { name: "14 项数据集信息" });
      expect(within(info).getAllByRole("row")).toHaveLength(15);
      expect(within(info).getByText("规范副本").tagName).toBe("STRONG");
      expect(within(info).getByText("robot_type").tagName).toBe("CODE");
      expect(within(info).getByRole("link", { name: "资料" }).getAttribute("href")).toBe(
        "https://example.invalid/data",
      );
      expect(within(info).queryByRole("link", { name: "数据路径" })).toBeNull();
      expect(within(info).getByText("/fake/data")).toBeTruthy();
      expect(within(info).queryByRole("img")).toBeNull();
      expect(within(info).getByText("原文14")).toBeTruthy();
    } finally {
      page.close();
    }
    const missing = mountPage(selectedUrl, datasetFetch());
    try {
      expect(await screen.findByText("规范副本不可用，无法展示14项数据集信息")).toBeTruthy();
    } finally {
      missing.close();
    }
  });
  // 契约：详情保留链接状态和检查时间，移除数据块、观察指向及两处原文按钮，保留子任务入口。
  it("详情隐藏数据块和原文按钮，保留链接状态与子任务", async () => {
    const page = mountPage(
      selectedUrl,
      transport({
        "/api/datasets/detail": () =>
          Response.json({
            ...detail,
            links: [{ ...offlineLink, status: "broken" }],
            sources: [
              {
                ordinal: 0,
                source_id: "source-17",
                original_path: "/fake/old",
                direct_path: "/fake/current",
                derived_entry_path: "按任务/libero_10/data",
                format: "lerobot",
                version: "3.0",
                validation_status: "legacy_custom",
                validation_status_label: "未识别（保留原值）",
              },
            ],
          }),
      }),
    );
    try {
      const links = await screen.findByRole("region", { name: "链接状态" });
      expect(within(links).getByText("断链")).toBeTruthy();
      expect(within(links).getByText(formatDateTime("2026-10-29T12:00:00Z"))).toBeTruthy();
      expect(screen.queryByRole("region", { name: "数据块" })).toBeNull();
      expect(within(links).queryByRole("columnheader", { name: "观察到的指向" })).toBeNull();
      for (const name of ["名称", "登记指向", "存储根", "状态", "检查时间"])
        expect(within(links).getByRole("columnheader", { name })).toBeTruthy();
      expect(screen.queryByRole("button", { name: "打开 数据集信息.json" })).toBeNull();
      expect(screen.queryByRole("button", { name: "打开 原始路径.json" })).toBeNull();
      expect(screen.queryByRole("button", { name: "打开 子任务.json" })).toBeNull();
    } finally {
      page.close();
    }
  });
  // 手动统计只发送当前数据集编号；等待响应期间重复点击不能生成第二个作业。
  it("统计大小按钮提交单数据集作业且不重复提交", async () => {
    let finish: ((response: Response) => void) | undefined;
    const requests: Request[] = [];
    const page = mountPage(
      selectedUrl,
      transport(
        {
          "/api/datasets/sizing": () =>
            new Promise<Response>((resolve) => {
              finish = resolve;
            }),
        },
        requests,
      ),
    );
    try {
      const button = await screen.findByRole("button", { name: "统计大小" });
      fireEvent.click(button);
      await waitFor(() => {
        expect(button).toHaveProperty("disabled", true);
      });
      fireEvent.click(button);
      const sent = requests.filter((request) => request.method === "POST");
      expect(sent).toHaveLength(1);
      expect(await sent[0]?.clone().json()).toEqual({ dataset_id: "dataset-14" });
      await act(async () => {
        finish?.(Response.json(completedJob, { status: 201 }));
        await Promise.resolve();
      });
      expect(
        await screen.findByRole("region", { name: `统计大小 #${completedJob.job_id}` }),
      ).toBeTruthy();
      expect(page.router.state.location.pathname).toBe("/datasets");
    } finally {
      page.close();
      finish?.(Response.json(completedJob));
    }
  });
});
