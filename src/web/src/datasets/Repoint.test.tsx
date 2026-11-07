// M1-09 页面验收：真实路由和 HTTP 边界验证。
import { describe, it, expect } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { account } from "../accounts/testSupport";
import { queueConflict } from "./creationTestSupport";
import { repointFetch, oldPrefix, newPrefix } from "./repointTestSupport";

describe("改指向与移除撤回入口的页面契约", () => {
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
  it("确认改指向后留在原页显示卡片，同数据集新排队项必须逐项确认", async () => {
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
      expect(await screen.findByRole("region", { name: "修改指向 #402" })).toBeTruthy();
      expect(page.router.state.location.pathname).toBe("/datasets");
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
  // 验证契约：写导航层作业详情和操作日志保留记录，但不再提供撤回入口。
  it("作业详情及操作日志中的写导航层作业没有撤回入口", async () => {
    const requests: Request[] = [];
    const page = mountPage("/jobs/401", repointFetch(requests));
    try {
      expect(await screen.findByRole("heading", { name: "写导航层 #401" })).toBeTruthy();
      expect(screen.queryByRole("button", { name: /撤回/ })).toBeNull();
      expect(screen.queryByRole("link", { name: /撤回/ })).toBeNull();
      expect(requests.filter((request) => request.method === "POST")).toHaveLength(0);
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
      expect(await screen.findByText("写导航层 #401")).toBeTruthy();
      expect(screen.getByText("写导航层 #402")).toBeTruthy();
      expect(screen.queryByRole("link", { name: /撤回/ })).toBeNull();
      expect(screen.queryByRole("button", { name: /撤回/ })).toBeNull();
    } finally {
      logs.close();
    }
  });
});

// 验证契约：移除撤回后仍保留改指向的恢复门禁，恢复失败时不得提交写入。
it("恢复失败时改指向禁用并说明原因", async () => {
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
    expect(requests.filter((request) => request.method === "POST")).toHaveLength(0);
  } finally {
    details.close();
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
