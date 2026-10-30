// 页面外壳统一（M1-05）：M0 页面和数据集页面共用同一菜单，时间显示统一。
import { describe, it, expect } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { mountPage, pageFetch } from "./scheduling/pageTestSupport";
import { account } from "./accounts/testSupport";
import { formatDateTime } from "./time";
import type { FetchImplementation } from "./api/client";

// 管理员账号才能看到账号、日志页面；列表接口给空页，让各页面都能渲染。
function adminFetch(): FetchImplementation {
  const base = pageFetch(undefined, undefined, () => account);
  return (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/accounts")
      return Promise.resolve(Response.json({ items: [account], next_after_id: null }));
    return base(request);
  };
}

describe("统一外壳", () => {
  // 契约：账号、操作日志、登录日志、作业、存储根、数据集都在同一个“主菜单”里，
  // 切换页面后菜单仍是同一个，当前页带 aria-current。
  it("六个页面共用同一个主菜单，当前页高亮", async () => {
    const page = mountPage("/", adminFetch());
    try {
      const menu = await screen.findByRole("navigation", { name: "主菜单" });
      for (const name of ["账号管理", "操作日志", "登录日志", "作业", "存储根", "数据集"])
        expect(within(menu).getByRole("link", { name })).toBeTruthy();
      for (const [name, path] of [
        ["存储根", "/storage-roots"],
        ["作业", "/jobs"],
        ["账号管理", "/accounts"],
        ["数据集", "/datasets"],
      ] as const) {
        fireEvent.click(within(menu).getByRole("link", { name }));
        await screen.findByRole("main");
        expect(page.router.state.location.pathname).toBe(path);
        const current = screen.getAllByRole("navigation", { name: "主菜单" });
        expect(current).toHaveLength(1);
        expect(
          within(current[0] as HTMLElement)
            .getByRole("link", { name })
            .getAttribute("aria-current"),
        ).toBe("page");
      }
    } finally {
      page.close();
    }
  });
  // 契约：账号表的更新时间使用统一的中文格式并带时区。
  it("账号表时间使用统一格式", async () => {
    const page = mountPage("/accounts", adminFetch());
    try {
      expect(await screen.findByText(formatDateTime(account.updated_at))).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 契约：M0 页面的表格都在自己的容器里横向滚动，宽表格不撑宽整页（沿用第 04 张的做法）。
  it("M0 各页面的表格带横向滚动容器", async () => {
    for (const path of [
      "/accounts",
      "/storage-roots",
      "/jobs",
      "/scheduling",
      "/audit/logins",
      "/audit/operations",
    ]) {
      const page = mountPage(path, adminFetch());
      try {
        await screen.findByRole("main");
        await waitFor(() => {
          expect(document.querySelectorAll(".ant-table").length).toBeGreaterThan(0);
        });
        document.querySelectorAll(".ant-table").forEach((table) => {
          const scroller = table.querySelector<HTMLElement>(".ant-table-content");
          expect(scroller?.style.overflowX, path).toBe("auto");
        });
      } finally {
        page.close();
      }
    }
  });
});
