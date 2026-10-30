// M1-09 页面验收：真实路由和 HTTP 边界验证。
import { describe, it, expect } from "vitest";
import { fireEvent, screen, within, waitFor } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { completedJob } from "../jobs/testSupport";
import { account } from "../accounts/testSupport";
import { queueConflict } from "./creationTestSupport";
import { repointFetch, oldPrefix, newPrefix } from "./repointTestSupport";

describe("改指向与撤回的页面契约", () => {
  // 验证详情入口、前缀表单和逐处替换预览，确认前不提交写入。
  it("详情进入改指向，展示字段计数、正文替换与原本缺失的路径", async () => {
    const requests: Request[] = [];
    const page = mountPage('/datasets?selected="按任务/libero_10"', repointFetch(requests));
    try {
      fireEvent.click(await screen.findByRole("button", { name: "改指向" }));
      expect(screen.getByRole("textbox", { name: "旧前缀" })).toHaveProperty("value", oldPrefix);
      expect(screen.getByRole("combobox", { name: "选择现有链接目标" })).toBeTruthy();
      fireEvent.change(screen.getByRole("textbox", { name: "新前缀" }), {
        target: { value: newPrefix },
      });
      fireEvent.click(screen.getByRole("button", { name: "预览改指向" }));
      const report = await screen.findByRole("region", { name: "导航写入预览差异" });
      expect(within(report).getByText("tasks[].notes[]")).toBeTruthy();
      expect(within(report).getByText("tasks[0].notes[0]")).toBeTruthy();
      expect(within(report).getByText(newPrefix)).toBeTruthy();
      expect(await screen.findByRole("region", { name: "旧位置原本不存在" })).toBeTruthy();
      expect(
        requests.filter((r) => new URL(r.url).pathname === "/api/navigation/writes"),
      ).toHaveLength(0);
      const sent = requests.find(
        (r) => new URL(r.url).pathname === "/api/datasets/repoint-previews",
      );
      expect(await sent?.clone().json()).toEqual({
        dataset_id: "dataset-14",
        old_prefix: oldPrefix,
        new_prefix: newPrefix,
      });
    } finally {
      page.close();
    }
  });
  // 验证创建同款的明确确认及新排队作业 409 再确认流程。
  it("确认改指向后进入作业详情，同数据集新排队项必须逐项确认", async () => {
    const requests: Request[] = [];
    let writes = 0;
    const page = mountPage(
      '/datasets?selected="按任务/libero_10"',
      repointFetch(requests, (request) => {
        if (new URL(request.url).pathname === "/api/navigation/writes" && writes++ === 0)
          return queueConflict(["501", "502"]);
        return undefined;
      }),
    );
    try {
      fireEvent.click(await screen.findByRole("button", { name: "改指向" }));
      fireEvent.change(screen.getByRole("textbox", { name: "新前缀" }), {
        target: { value: newPrefix },
      });
      fireEvent.click(screen.getByRole("button", { name: "预览改指向" }));
      fireEvent.click(await screen.findByRole("button", { name: "确认导航写入" }));
      const confirm = await screen.findByRole("button", { name: "确认排队并提交导航写入" });
      expect(confirm).toHaveProperty("disabled", true);
      fireEvent.click(screen.getByRole("checkbox", { name: "确认排队作业 501" }));
      expect(confirm).toHaveProperty("disabled", true);
      fireEvent.click(screen.getByRole("checkbox", { name: "确认排队作业 502" }));
      fireEvent.click(confirm);
      await waitFor(() => {
        expect(page.router.state.location.pathname).toBe("/jobs/402");
      });
      const sent = requests.filter((r) => new URL(r.url).pathname === "/api/navigation/writes");
      expect(sent).toHaveLength(2);
      expect(await sent[1]?.clone().json()).toEqual({
        preview_job_id: "301",
        acknowledged_queue_job_ids: ["501", "502"],
      });
    } finally {
      page.close();
    }
  });
  // 验证任意写导航层作业均能从作业详情和操作日志发起撤回。
  it("作业详情及操作日志中的写导航层作业显示撤回入口", async () => {
    const requests: Request[] = [];
    const page = mountPage("/jobs/401", repointFetch(requests));
    try {
      const entry = await screen.findByRole("button", { name: "撤回导航写入" });
      fireEvent.click(entry);
      expect(await screen.findByRole("heading", { name: "撤回作业 #401" })).toBeTruthy();
      expect(
        requests.filter((r) => new URL(r.url).pathname.endsWith("/revert-previews")),
      ).toHaveLength(0);
      expect(await screen.findByRole("button", { name: "预览撤回" })).toBeTruthy();
    } finally {
      page.close();
    }
    const logs = mountPage(
      "/audit/operations",
      repointFetch(requests, (request) => {
        const path = new URL(request.url).pathname;
        if (path === "/api/auth/me") return Response.json({ ...account, role: "administrator" });
        if (path === "/api/audit/retention") return Response.json({ days: 30 });
        if (path === "/api/audit/operations")
          return Response.json({
            items: [
              {
                log_id: "11",
                occurred_at: "2026-10-30T07:00:00Z",
                actor: { account_id: "1", name: "甲", deleted: false },
                target: {
                  kind: "navigation_write",
                  object_id: "401",
                  name: "写导航层 #401",
                  deleted: false,
                },
                operation: "repoint_dataset",
                result: "success",
                failure_category: null,
                request_id: null,
                source_ip: null,
                details: { version: 1, before: {}, after: { change_record_id: "401" } },
              },
              {
                log_id: "12",
                occurred_at: "2026-10-30T07:00:00Z",
                actor: { account_id: "1", name: "甲", deleted: false },
                target: {
                  kind: "navigation_write",
                  object_id: "402",
                  name: "写导航层 #402",
                  deleted: false,
                },
                operation: "edit_dataset_fields",
                result: "success",
                failure_category: null,
                request_id: null,
                source_ip: null,
                details: { version: 1, before: {}, after: { change_record_id: "402" } },
              },
            ],
            next_cursor: null,
          });
        return undefined;
      }),
    );
    try {
      const link = await screen.findByRole("link", { name: "撤回导航作业 401" });
      expect(link.getAttribute("href")).toBe("/jobs/401/revert");
      // 字段编辑（edit_dataset_fields）同属 navigation_write，同样显示通用撤回链接。
      const fieldLink = await screen.findByRole("link", { name: "撤回导航作业 402" });
      expect(fieldLink.getAttribute("href")).toBe("/jobs/402/revert");
      fireEvent.click(link);
      expect(await screen.findByRole("heading", { name: "撤回作业 #401" })).toBeTruthy();
    } finally {
      logs.close();
    }
  });
  // 验证反向差异展示及冲突诊断，失败时不能继续确认旧预览。
  it("撤回先展示反向替换，后像变化时列出差异并重新预览", async () => {
    const requests: Request[] = [];
    const page = mountPage("/jobs/401/revert", repointFetch(requests));
    try {
      fireEvent.click(await screen.findByRole("button", { name: "预览撤回" }));
      const report = await screen.findByRole("region", { name: "导航写入预览差异" });
      const cells = within(report)
        .getAllByRole("cell")
        .map((cell) => cell.textContent);
      expect(cells.indexOf(newPrefix)).toBeLessThan(cells.indexOf(oldPrefix));
      fireEvent.click(screen.getByRole("button", { name: "确认导航写入" }));
      await waitFor(() => {
        expect(page.router.state.location.pathname).toBe("/jobs/402");
      });
      const sent = requests.find((r) => new URL(r.url).pathname === "/api/navigation/writes");
      expect(await sent?.clone().json()).toEqual({
        preview_job_id: "302",
        acknowledged_queue_job_ids: [],
      });
    } finally {
      page.close();
    }
    const failed = mountPage(
      "/jobs/401/revert",
      repointFetch(requests, (request) => {
        if (new URL(request.url).pathname === "/api/jobs/302")
          return Response.json({
            ...completedJob,
            job_id: "302",
            summary: { ...completedJob.summary, outcome: "failed", aborted: true },
            diagnostics: [
              {
                source: "平台",
                rule: "NAV_CHANGES",
                total: 1,
                error_count: 1,
                warning_count: 0,
                samples: [
                  {
                    level: "error",
                    category: "conflict",
                    stage: "写导航层",
                    source: "平台",
                    rule: "NAV_CHANGES",
                    objects: [
                      {
                        key: "diff_1",
                        value: "按任务/libero_10/原始路径.json：应为sha256 aaa，现在sha256 bbb",
                      },
                    ],
                    actual: "当前状态与后像有差异",
                    expected: "与原作业后像一致",
                    consequence: "一行未写",
                    next_step: "核对差异后重新预览",
                    error_chain: [],
                  },
                ],
              },
            ],
          });
        return undefined;
      }),
    );
    try {
      fireEvent.click(await screen.findByRole("button", { name: "预览撤回" }));
      expect(await screen.findByText(/当前状态与后像有差异/)).toBeTruthy();
      expect(screen.getByText(/应为sha256 aaa，现在sha256 bbb/)).toBeTruthy();
      expect(screen.queryByRole("button", { name: "确认导航写入" })).toBeNull();
      expect(screen.getByRole("button", { name: "重新预览撤回" })).toBeTruthy();
    } finally {
      failed.close();
    }
  });
});

// 验证恢复门禁既控制详情入口，也控制直接打开的撤回页，不把未知/错误当成可写。
it("恢复失败时改指向和撤回禁用并说明原因", async () => {
  const requests: Request[] = [];
  const transport = repointFetch(requests, (request) =>
    new URL(request.url).pathname === "/api/navigation/recovery-block"
      ? Response.json({ blocked: true })
      : undefined,
  );
  const details = mountPage('/datasets?selected="按任务/libero_10"', transport);
  try {
    const button = await screen.findByRole("button", { name: "改指向" });
    expect(button).toHaveProperty("disabled", true);
    expect(
      within(screen.getByRole("region", { name: "数据集改指向" })).getByText(/恢复失败/),
    ).toBeTruthy();
  } finally {
    details.close();
  }
  const revert = mountPage("/jobs/401/revert", transport);
  try {
    const button = await screen.findByRole("button", { name: "预览撤回" });
    expect(button).toHaveProperty("disabled", true);
    expect(screen.getByRole("alert", { name: "撤回限制" }).textContent).toContain("恢复失败");
    expect(requests.filter((request) => request.method === "POST")).toHaveLength(0);
  } finally {
    revert.close();
  }
});

// 验证修改前缀后立刻丢弃旧预览，不能把新表单与旧报告一起确认。
it("修改前缀立即取消旧预览确认资格", async () => {
  const requests: Request[] = [];
  const page = mountPage('/datasets?selected="按任务/libero_10"', repointFetch(requests));
  try {
    fireEvent.click(await screen.findByRole("button", { name: "改指向" }));
    fireEvent.change(screen.getByRole("textbox", { name: "新前缀" }), {
      target: { value: newPrefix },
    });
    fireEvent.click(screen.getByRole("button", { name: "预览改指向" }));
    expect(await screen.findByRole("button", { name: "确认导航写入" })).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "新前缀" }), {
      target: { value: newPrefix + "/changed" },
    });
    expect(screen.queryByRole("button", { name: "确认导航写入" })).toBeNull();
    expect(
      requests.filter((request) => new URL(request.url).pathname === "/api/navigation/writes"),
    ).toHaveLength(0);
  } finally {
    page.close();
  }
});

// 验证按格式入口只是子集，默认和候选必须来自该数据集唯一规范入口。
it("按格式详情从规范入口加载链接目标", async () => {
  const { detail, formatEntry } = await import("./testSupport");
  const requests: Request[] = [];
  const page = mountPage(
    '/datasets?selected="按格式/lerobot/2.1/libero_10"',
    repointFetch(requests, (request) => {
      const url = new URL(request.url);
      if (
        url.pathname === "/api/datasets/detail" &&
        url.searchParams.get("entry_path") === formatEntry.entry_path
      )
        return Response.json({ ...detail, entry: formatEntry, links: [] });
      return undefined;
    }),
  );
  try {
    fireEvent.click(await screen.findByRole("button", { name: "改指向" }));
    expect(screen.getByRole("textbox", { name: "旧前缀" })).toHaveProperty("value", oldPrefix);
    expect(
      requests.some((request) => {
        const url = new URL(request.url);
        return (
          url.pathname === "/api/datasets/detail" &&
          url.searchParams.get("entry_path") === "按任务/libero_10"
        );
      }),
    ).toBe(true);
  } finally {
    page.close();
  }
});
