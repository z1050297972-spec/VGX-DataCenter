// M4.5-04 关键验收：真实页面、路由和 HTTP 边界验证选择、权限与转换。
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { mountPage, pageFetch } from "../scheduling/pageTestSupport";
import { account } from "../accounts/testSupport";
import { job } from "../jobs/testSupport";
import type { CleaningPreview } from "../api/cleaning";
import { preview, cleaningTools } from "./testSupport";

function mountReport(member = false, snapshot: CleaningPreview = preview) {
  const requests: Request[] = [];
  const fallback = pageFetch(undefined, undefined, () => ({
    ...account,
    role: member ? "member" : "administrator",
  }));
  const page = mountPage("/cleaning/42", (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/cleaning-previews/42") return Promise.resolve(Response.json(snapshot));
    if (path === "/api/tools") return Promise.resolve(Response.json(cleaningTools));
    if (path === "/api/cleaning-previews/42/convert") {
      requests.push(request.clone());
      return Promise.resolve(Response.json(job, { status: 201 }));
    }
    return fallback(request);
  });
  return { ...page, requests };
}

it("清洗流程默认展示六步，并使用报告的文件数和规则数值", async () => {
  // 非默认阈值与手算总大小验证流程说明来自报告；不展开规则说明也能读到六步。
  const page = mountReport();
  try {
    const process = await screen.findByRole("region", { name: "清洗流程" });
    for (const title of [
      "读取文件",
      "时间对齐",
      "判坏帧、切段",
      "文件级检查",
      "段内质量检查",
      "选择与转换",
    ]) {
      expect(within(process).getByText(title)).toBeTruthy();
    }
    expect(within(process).getByText(/本次 3 个 MCAP 文件[，、]共 130.81 GB/)).toBeTruthy();
    expect(within(process).getByText(/基准：以话题 \/camera.*10 帧\/秒/)).toBeTruthy();
    expect(within(process).getByText(/坏帧：.*默认 17.000 毫秒/)).toBeTruthy();
    expect(within(process).getByText(/切段：.*相邻基准帧间隔超过 270.000 毫秒/)).toBeTruthy();
    expect(within(process).getByText(/丢弃：短于 73 帧的段丢弃/)).toBeTruthy();
    expect(within(process).getByText("默认剔除（严重）")).toBeTruthy();
    expect(within(process).getByText("非有限值、整段静止")).toBeTruthy();
    expect(within(process).getByText("只提示（默认保留）")).toBeTruthy();
    expect(within(process).getByText(/连续静止至少 4.50 秒/)).toBeTruthy();
    expect(within(process).getByText(/相机冻结至少 2.25 秒/)).toBeTruthy();
    expect(within(process).getByText(/每 0.75 秒 抽一帧/)).toBeTruthy();
    const conversion = within(process).getByRole("list", { name: "进行转换后的六个步骤" });
    expect(within(conversion).getAllByRole("listitem")).toHaveLength(6);
  } finally {
    page.close();
  }
});

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

// 规则说明必须使用报告快照；可变的严重检查列表以及 null 阈值不能被前端默认值覆盖。
it.each([{ severe_checks: ["non_finite", "frozen_image"] }, { severe_checks: [] }])(
  "规则说明展示快照阈值，严重检查按 $severe_checks 显示",
  async ({ severe_checks }) => {
    const snapshot: CleaningPreview = {
      ...preview,
      report: {
        ...preview.report,
        rules: {
          ...preview.report.rules,
          checks: { ...preview.report.rules.checks, severe_checks },
        },
      },
    };
    const page = mountReport(false, snapshot);
    try {
      fireEvent.click(await screen.findByText("规则说明"));
      expect(await screen.findByText("17.000 毫秒")).toBeTruthy();
      expect(screen.getByText("2.7 倍 / 270.000 毫秒")).toBeTruthy();
      expect(screen.getByText("73 帧")).toBeTruthy();
      for (const text of [
        "observation.state",
        "action",
        "4.50 秒",
        "2.25 秒",
        "0.75 秒",
        "平均亮度 < 12",
        "平均亮度 > 238",
      ]) {
        expect(screen.getByText(text)).toBeTruthy();
      }
      const source = screen.getByRole("row", { name: /state 0[.]002 0[.]7/ });
      expect(within(source).getByText("第 1 维：[-1.2, 1.3]")).toBeTruthy();
      const gripper = screen.getByRole("row", { name: /gripper 0[.]2/ });
      expect(within(gripper).getByText("不检查")).toBeTruthy();
      expect(within(gripper).getByText("未配置")).toBeTruthy();
      const unchecked = screen.getByRole("row", { name: /unchecked/ });
      expect(within(unchecked).getAllByText("不检查")).toHaveLength(2);
      const severeRow = screen.getByText("严重检查（默认剔除）").closest("tr");
      if (!severeRow) throw new Error("缺少严重检查说明");
      expect(within(severeRow).queryByText("frozen_image") !== null).toBe(
        severe_checks.includes("frozen_image"),
      );
      if (!severe_checks.length) expect(within(severeRow).getByText("无")).toBeTruthy();
      expect(screen.queryByText(/报告未提供/)).toBeNull();
    } finally {
      page.close();
    }
  },
);
