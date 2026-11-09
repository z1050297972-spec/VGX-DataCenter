// M4.5-04 关键验收：真实页面、路由和 HTTP 边界验证选择、权限与转换。
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { mountPage, pageFetch } from "../scheduling/pageTestSupport";
import { account } from "../accounts/testSupport";
import { job } from "../jobs/testSupport";
import { preview, cleaningTools } from "./testSupport";

function mountReport(member = false) {
  const requests: Request[] = [];
  const fallback = pageFetch(undefined, undefined, () => ({
    ...account,
    role: member ? "member" : "administrator",
  }));
  const page = mountPage("/cleaning/42", (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/cleaning-previews/42") return Promise.resolve(Response.json(preview));
    if (path === "/api/tools") return Promise.resolve(Response.json(cleaningTools));
    if (path === "/api/cleaning-previews/42/convert") {
      requests.push(request.clone());
      return Promise.resolve(Response.json(job, { status: 201 }));
    }
    return fallback(request);
  });
  return { ...page, requests };
}

it("致命文件固定剔除并显示原因，剔除前面的文件后保留段编号前移", async () => {
  // 致命文件不能恢复；编号按最终产物从零连续计算，文件身份始终不变。
  const page = mountReport();
  try {
    const fatalSwitch = await screen.findByRole("switch", { name: "文件 broken.mcap 保留" });
    expect(fatalSwitch.hasAttribute("disabled")).toBe(true);
    expect(fatalSwitch.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText(/实际：缺少基准话题/)).toBeTruthy();
    const last = screen.getByRole("switch", { name: "文件 2 段 0 保留" }).closest("tr");
    expect(last).not.toBeNull();
    if (!last) throw new Error("缺少 episode 行");
    const numberCell = within(last).getByRole("cell", { name: "1" });
    expect(numberCell.textContent).toBe("1");
    fireEvent.click(screen.getByRole("switch", { name: "文件 first.mcap 保留" }));
    expect(numberCell.textContent).toBe("0");
    expect(screen.getByRole("switch", { name: "文件 1 段 0 保留" }).hasAttribute("disabled")).toBe(
      true,
    );
  } finally {
    page.close();
  }
});

it("切换段后更新汇总，管理员确认才发送当前选择和空间参数并跳转", async () => {
  // 默认严重段可恢复，另一个段可剔除；请求使用稳定的文件/段身份而非显示编号。
  const page = mountReport();
  try {
    fireEvent.click(await screen.findByRole("switch", { name: "文件 1 段 1 保留" }));
    fireEvent.click(screen.getByRole("switch", { name: "文件 2 段 0 保留" }));
    expect(screen.getByText("当前保留：2 个文件，2 个 episode，200 帧")).toBeTruthy();
    expect(
      screen.getByText(
        "将把 2 个文件交给工具，转换后剔除 1 个 episode，产出清洗后的 LeRobot 数据集",
      ),
    ).toBeTruthy();
    expect(screen.getByText("产物按两倍估算")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("百分比（%）"), { target: { value: "200" } });
    fireEvent.change(screen.getByLabelText("偏置（GiB）"), { target: { value: "2.5" } });
    fireEvent.click(screen.getByRole("button", { name: "进行转换" }));
    const dialog = await screen.findByRole("dialog");
    expect(page.requests).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "确认转换" }));
    await waitFor(() => {
      expect(page.router.state.location.pathname).toBe(`/jobs/${job.job_id}`);
    });
    expect(page.requests).toHaveLength(1);
    expect(await page.requests[0]?.json()).toEqual({
      output_format: "v3.0",
      space_ratio_percent: 200,
      space_reserve_gib: 2.5,
      excluded_files: [0],
      excluded_episodes: [{ file_index: 2, segment_index: 0 }],
    });
  } finally {
    page.close();
  }
});

it("成员可以阅读报告但看不到进行转换按钮", async () => {
  // 权限在真实身份响应上生效，成员仍能检查报告事实。
  const page = mountReport(true);
  try {
    expect(await screen.findByRole("heading", { name: "清洗报告 #42" })).toBeTruthy();
    expect(await screen.findByText("当前保留：2 个文件，2 个 episode，200 帧")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "进行转换" })).toBeNull();
  } finally {
    page.close();
  }
});

it.each(["文件", "episode"])("全部剔除%s时禁用转换并说明原因", async (scope) => {
  // 两种空产物必须分别拦截，不能提交空文件列表或删除全部段。
  const page = mountReport();
  try {
    await screen.findByRole("switch", { name: "文件 first.mcap 保留" });
    const names =
      scope === "文件"
        ? ["文件 first.mcap 保留", "文件 last.mcap 保留"]
        : ["文件 1 段 0 保留", "文件 2 段 0 保留"];
    for (const name of names) fireEvent.click(screen.getByRole("switch", { name }));
    expect(screen.getByRole("button", { name: "进行转换" }).hasAttribute("disabled")).toBe(true);
    expect(
      screen.getByText(
        scope === "文件" ? "没有保留的文件，无法转换。" : "没有保留的 episode，无法转换。",
      ),
    ).toBeTruthy();
  } finally {
    page.close();
  }
});
