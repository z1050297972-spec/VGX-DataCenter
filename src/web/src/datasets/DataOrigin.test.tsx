// M1-10：通过真实 Router、Query 和 HTTP 边界验证数据来源标注，不替换内部模块。
import { describe, it, expect } from "vitest";
import { fireEvent, screen, within, waitFor, act } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { account, problemResponse } from "../accounts/testSupport";
import { detail, filters, datasets } from "./testSupport";
import { formatDateTime } from "../time";
import {
  originFetch,
  originUrl,
  originPreview,
  previewJob,
  writingJob,
  writtenJob,
} from "./originTestSupport";

describe("数据来源标注", () => {
  // 契约：六种来源可选；服务端报告给出文件和真实新旧值，未确认时绝不提交写作业。
  it("选择来源并预览新旧值", async () => {
    const requests: Request[] = [];
    const page = mountPage(originUrl, originFetch(requests));
    try {
      // 等真实路由完成初次加载，避免慢机器把动态导入耗时算进DOM查找预算。
      await page.router.load();
      const area = await screen.findByRole("region", { name: "数据来源标注" });
      fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择数据来源" }));
      for (const label of ["真机采集", "UMI 采集", "ego 采集", "仿真生成", "开源下载", "未知"])
        expect(await screen.findByRole("option", { name: label })).toBeTruthy();
      fireEvent.click(screen.getByRole("option", { name: "开源下载" }));
      fireEvent.click(within(area).getByRole("button", { name: "预览数据来源" }));
      const differences = await screen.findByRole("region", { name: "数据来源预览差异" });
      expect(within(differences).getByText("按任务/libero_10/来源.json")).toBeTruthy();
      expect(within(differences).getByText("未知")).toBeTruthy();
      expect(within(differences).getByText("开源下载")).toBeTruthy();
      expect(within(area).getByText(formatDateTime(originPreview.created_at))).toBeTruthy();
      const sent = requests.filter((request) => request.method === "POST");
      expect(sent).toHaveLength(1);
      expect(await sent[0]?.clone().json()).toEqual({
        dataset_id: "dataset-14",
        data_origin: "开源下载",
      });
      expect(page.router.state.location.pathname).toBe("/datasets");
    } finally {
      page.close();
    }
  });
  // 契约：确认仅提交一次写作业并导航；完成后详情、列表和筛选计数缓存全部失效并重新读取。
  it("确认写入后刷新来源筛选", async () => {
    const requests: Request[] = [];
    let finished = false;
    const page = mountPage(
      originUrl,
      originFetch(requests, {
        "/api/jobs/302": () => Response.json(finished ? writtenJob : writingJob),
        "/api/datasets/detail": () =>
          Response.json({
            ...detail,
            observed_at: finished ? "2026-10-30T07:15:00Z" : detail.observed_at,
            provenance: finished
              ? {
                  state: "valid",
                  data_origin: "开源下载",
                  data_origin_set_by: { account_name: "标注成员", at: "2026-10-30T07:00:00Z" },
                }
              : detail.provenance,
          }),
        "/api/datasets/filters": () =>
          Response.json(
            finished
              ? {
                  ...filters,
                  data_origins: [
                    { value: "open_source", label: "开源下载", count: 1 },
                    { value: "unknown", label: "未知", count: 1 },
                  ],
                }
              : filters,
          ),
        "/api/datasets": () => Response.json(datasets),
      }),
    );
    try {
      const area = await screen.findByRole("region", { name: "数据来源标注" });
      fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择数据来源" }));
      fireEvent.click(await screen.findByRole("option", { name: "开源下载" }));
      fireEvent.click(within(area).getByRole("button", { name: "预览数据来源" }));
      const confirm = await screen.findByRole("button", { name: "确认修改数据来源" });
      fireEvent.click(confirm);
      fireEvent.click(confirm);
      await waitFor(() => {
        expect(page.router.state.location.pathname).toBe("/jobs/302");
      });
      const writes = requests.filter(
        (request) => request.method === "POST" && new URL(request.url).pathname === "/api/jobs",
      );
      expect(writes).toHaveLength(1);
      expect(await writes[0]?.clone().json()).toEqual({
        type_name: "nav_write_apply",
        parameters: { preview_job_id: 301 },
      });
      // 模拟仍被其他视图持有的缓存；通过公开 Query 状态验证写入终态会使它们失效。
      const keys = ["detail", "list", "filters", "trees"].map((part) => [
        "datasets",
        account.account_id,
        part,
        "其他视图",
      ]);
      for (const key of keys) page.cache.setQueryData(key, { snapshot: "写入前" });
      finished = true;
      await act(async () => {
        await page.cache.invalidateQueries({ queryKey: ["jobs", "detail", "302"] });
      });
      await waitFor(() => {
        for (const key of keys) expect(page.cache.getQueryState(key)?.isInvalidated).toBe(true);
      });
      await act(async () => {
        await page.router.navigate({ to: "/datasets", search: { selected: "按任务/libero_10" } });
      });
      expect(
        await screen.findByText(formatDateTime("2026-10-30T07:15:00Z"), { exact: false }),
      ).toBeTruthy();
      // 作业完成返回详情后必须显示刚写入的当前值，不能只刷新时间而仍留下空选择框。
      expect(screen.getByText("当前：开源下载")).toBeTruthy();
      expect(
        within(screen.getByRole("region", { name: "数据来源标注" })).getByRole("button", {
          name: "预览数据来源",
        }),
      ).toHaveProperty("disabled", true);
      fireEvent.mouseDown(screen.getByRole("combobox", { name: "数据来源" }));
      expect(await screen.findByRole("option", { name: "开源下载（1）" })).toBeTruthy();
      for (const path of ["/api/datasets/detail", "/api/datasets", "/api/datasets/filters"])
        expect(
          requests.filter((request) => new URL(request.url).pathname === path).length,
        ).toBeGreaterThan(1);
    } finally {
      page.close();
    }
  });
  // 契约：409 保留服务端五段诊断，不跳转或重试写入；必须重新预览才能再次确认。
  it("冲突诊断并要求重新预览", async () => {
    const requests: Request[] = [];
    const page = mountPage(
      originUrl,
      originFetch(requests, {
        "/api/jobs": () =>
          Response.json(
            {
              type: "about:blank",
              title: "Conflict",
              status: 409,
              category: "conflict",
              detail: "预览之后来源文件变化",
              error_id: "00000000000040008000000000000000",
              diagnostics: [
                {
                  level: "error",
                  category: "conflict",
                  stage: "写导航层",
                  source: "平台",
                  objects: [{ key: "dataset_id", value: "dataset-14" }],
                  rule: "NAV_PREVIEW_STATE",
                  actual: "来源哈希已变化",
                  expected: "与预览一致",
                  consequence: "导航层一行都没写",
                  next_step: "重新预览后再提交",
                  error_chain: [],
                },
              ],
            },
            { status: 409, headers: { "Content-Type": "application/problem+json" } },
          ),
      }),
    );
    try {
      const area = await screen.findByRole("region", { name: "数据来源标注" });
      fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择数据来源" }));
      fireEvent.click(await screen.findByRole("option", { name: "开源下载" }));
      fireEvent.click(within(area).getByRole("button", { name: "预览数据来源" }));
      fireEvent.click(await screen.findByRole("button", { name: "确认修改数据来源" }));
      expect(await screen.findByText(/来源哈希已变化/)).toBeTruthy();
      expect(within(area).getByText(/dataset_id=dataset-14/)).toBeTruthy();
      expect(within(area).getByText(/导航层一行都没写/)).toBeTruthy();
      expect(within(area).getByText(/重新预览后再提交/)).toBeTruthy();
      await waitFor(() => {
        expect(within(area).getByRole("button", { name: "确认修改数据来源" })).toHaveProperty(
          "disabled",
          true,
        );
      });
      expect(page.router.state.location.pathname).toBe("/datasets");
      expect(
        requests.filter(
          (request) => request.method === "POST" && new URL(request.url).pathname === "/api/jobs",
        ),
      ).toHaveLength(1);
      expect(within(area).getByRole("button", { name: "预览数据来源" })).toHaveProperty(
        "disabled",
        false,
      );
    } finally {
      page.close();
    }
  });
  // 契约：恢复失败会禁用预览；预览后新出现标记也会禁用确认，并保留可见原因。
  it("恢复失败禁用预览和确认并说明原因", async () => {
    const requests: Request[] = [];
    let blocked = true;
    const page = mountPage(
      originUrl,
      originFetch(requests, {
        "/api/navigation/recovery-block": () =>
          Response.json(
            blocked
              ? {
                  blocked: true,
                  set_at: "2026-10-30T07:00:00Z",
                  job_ids: ["299"],
                  items: [],
                  total_items: 1,
                }
              : { blocked: false },
          ),
      }),
    );
    try {
      const area = await screen.findByRole("region", { name: "数据来源标注" });
      fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择数据来源" }));
      fireEvent.click(await screen.findByRole("option", { name: "开源下载" }));
      expect(within(area).getByRole("button", { name: "预览数据来源" })).toHaveProperty(
        "disabled",
        true,
      );
      expect(within(area).getByText(/导航层恢复失败/)).toBeTruthy();
      blocked = false;
      await act(async () => {
        await page.cache.invalidateQueries({ queryKey: ["navigation", "recovery-block"] });
      });
      fireEvent.click(within(area).getByRole("button", { name: "预览数据来源" }));
      const confirm = await screen.findByRole("button", { name: "确认修改数据来源" });
      blocked = true;
      await act(async () => {
        await page.cache.invalidateQueries({ queryKey: ["navigation", "recovery-block"] });
      });
      await waitFor(() => {
        expect(confirm).toHaveProperty("disabled", true);
      });
      fireEvent.click(confirm);
      fireEvent.click(within(area).getByRole("button", { name: "预览数据来源" }));
      expect(requests.filter((request) => request.method === "POST")).toHaveLength(1);
    } finally {
      page.close();
    }
  });
  // 契约：未确认恢复状态前不能提交；标记查询失败也不能把旧的“未阻挡”当作放行。
  it("恢复状态未读到或读取失败时不允许提交", async () => {
    const requests: Request[] = [];
    let finish: ((response: Response) => void) | undefined;
    const page = mountPage(
      originUrl,
      originFetch(requests, {
        "/api/navigation/recovery-block": () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      }),
    );
    try {
      const area = await screen.findByRole("region", { name: "数据来源标注" });
      fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择数据来源" }));
      fireEvent.click(await screen.findByRole("option", { name: "开源下载" }));
      expect(within(area).getByRole("button", { name: "预览数据来源" })).toHaveProperty(
        "disabled",
        true,
      );
      expect(within(area).getByText(/正在核对导航层恢复状态/)).toBeTruthy();
      act(() => {
        finish?.(problemResponse(502));
      });
      expect(await within(area).findByText(/无法核对导航层恢复状态/)).toBeTruthy();
      expect(within(area).getByRole("button", { name: "预览数据来源" })).toHaveProperty(
        "disabled",
        true,
      );
      expect(requests.filter((request) => request.method === "POST")).toHaveLength(0);
    } finally {
      page.close();
      finish?.(Response.json({ blocked: false }));
    }
  });
  // 契约：请求进行中不重复提交；离开详情取消等待，迟到预览不导航或出现在新页面。
  it("离开详情取消预览并忽略迟到响应", async () => {
    const requests: Request[] = [];
    let pending: Request | undefined;
    let finish: ((response: Response) => void) | undefined;
    const page = mountPage(
      originUrl,
      originFetch(requests, {
        "/api/navigation/data-origin/preview": (request) => {
          pending = request;
          return new Promise<Response>((resolve) => {
            finish = resolve;
          });
        },
      }),
    );
    try {
      const area = await screen.findByRole("region", { name: "数据来源标注" });
      fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择数据来源" }));
      fireEvent.click(await screen.findByRole("option", { name: "开源下载" }));
      const submit = within(area).getByRole("button", { name: "预览数据来源" });
      fireEvent.click(submit);
      await waitFor(() => {
        expect(pending).toBeDefined();
      });
      expect(submit).toHaveProperty("disabled", true);
      fireEvent.click(submit);
      expect(requests.filter((request) => request.method === "POST")).toHaveLength(1);
      fireEvent.click(screen.getByRole("link", { name: "作业" }));
      await waitFor(() => {
        expect(pending?.signal.aborted).toBe(true);
      });
      await act(async () => {
        finish?.(Response.json({ ...previewJob, state: "queued", summary: null }));
        await Promise.resolve();
      });
      expect(page.router.state.location.pathname).toBe("/jobs");
      expect(screen.queryByRole("region", { name: "数据来源预览差异" })).toBeNull();
      expect(
        requests.some(
          (request) => new URL(request.url).pathname === "/api/navigation/previews/301",
        ),
      ).toBe(false);
    } finally {
      page.close();
      finish?.(Response.json(previewJob));
    }
  });

  // 契约：completed 不等于成功；失败预览不能读取报告或进入确认写入。
  it("失败预览不读取报告或允许确认", async () => {
    const requests: Request[] = [];
    const page = mountPage(
      originUrl,
      originFetch(requests, {
        "/api/jobs/301": () =>
          Response.json({
            ...previewJob,
            summary: { ...previewJob.summary, outcome: "failed", aborted: true },
          }),
      }),
    );
    try {
      const area = await screen.findByRole("region", { name: "数据来源标注" });
      fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择数据来源" }));
      fireEvent.click(await screen.findByRole("option", { name: "开源下载" }));
      fireEvent.click(within(area).getByRole("button", { name: "预览数据来源" }));
      expect(await screen.findByRole("status", { name: "数据来源预览作业状态" })).toHaveProperty(
        "textContent",
        "失败",
      );
      expect(screen.queryByRole("button", { name: "确认修改数据来源" })).toBeNull();
      expect(
        requests.some(
          (request) => new URL(request.url).pathname === "/api/navigation/previews/301",
        ),
      ).toBe(false);
    } finally {
      page.close();
    }
  });
  // 评审回归：缺来源文件时明确显示未标注，默认未知且相同值不能预览。
  it("未标注显示当前未知并禁止相同值预览", async () => {
    const page = mountPage(
      originUrl,
      originFetch([], {
        "/api/datasets/detail": () =>
          Response.json({
            ...detail,
            provenance: { state: "absent", data_origin: "未知", data_origin_set_by: null },
          }),
      }),
    );
    try {
      const area = await screen.findByRole("region", { name: "数据来源标注" });
      expect(within(area).getByText("当前：未知（还没有 来源.json）")).toBeTruthy();
      expect(within(area).getByText("和当前一样")).toBeTruthy();
      expect(within(area).getByRole("button", { name: "预览数据来源" })).toHaveProperty(
        "disabled",
        true,
      );
      expect(
        within(area).getByRole("combobox", { name: "选择数据来源" }).getAttribute("aria-label"),
      ).toBe("选择数据来源");
      fireEvent.mouseDown(within(area).getByRole("combobox", { name: "选择数据来源" }));
      expect(screen.getByRole("option", { name: "未知" }).getAttribute("aria-selected")).toBe(
        "true",
      );
    } finally {
      page.close();
    }
  });

  // 评审回归：显示当前标注值、标注人和本地时间；默认值及切回当前值都禁止预览。
  it("已标注显示来源和印记并禁止相同值预览", async () => {
    const page = mountPage(
      originUrl,
      originFetch([], {
        "/api/datasets/detail": () =>
          Response.json({
            ...detail,
            provenance: {
              state: "valid",
              data_origin: "仿真生成",
              data_origin_set_by: { account_name: "标注成员", at: "2026-10-30T07:00:00Z" },
            },
          }),
      }),
    );
    try {
      const area = await screen.findByRole("region", { name: "数据来源标注" });
      expect(within(area).getByText("当前：仿真生成")).toBeTruthy();
      expect(within(area).getByText(/标注成员/)).toBeTruthy();
      expect(within(area).getByText(formatDateTime("2026-10-30T07:00:00Z"))).toBeTruthy();
      const select = within(area).getByRole("combobox", { name: "选择数据来源" });
      const preview = within(area).getByRole("button", { name: "预览数据来源" });
      expect(preview).toHaveProperty("disabled", true);
      fireEvent.mouseDown(select);
      expect(screen.getByRole("option", { name: "仿真生成" }).getAttribute("aria-selected")).toBe(
        "true",
      );
      fireEvent.click(screen.getByRole("option", { name: "开源下载" }));
      await waitFor(() => {
        expect(preview).toHaveProperty("disabled", false);
      });
      fireEvent.mouseDown(select);
      fireEvent.click(await screen.findByRole("option", { name: "仿真生成" }));
      expect(preview).toHaveProperty("disabled", true);
      expect(within(area).getByText("和当前一样")).toBeTruthy();
    } finally {
      page.close();
    }
  });
});
