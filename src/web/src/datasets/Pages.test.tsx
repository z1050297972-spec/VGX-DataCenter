// M1-04 通过真实 Router、Query 和 HTTP 边界验证可见浏览行为。
import { describe, it, expect } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { completedJob } from "../jobs/testSupport";
import { datasetFetch, taskEntry, formatEntry } from "./testSupport";

describe("数据集布局 A", () => {
  // 契约：登录成员通过菜单进入，看到两棵树的入口及按永久编号去重的列表数量。
  it("菜单进入数据集页面，显示两棵树和列表数量", async () => {
    const page = mountPage("/", datasetFetch());
    try {
      fireEvent.click(await screen.findByRole("link", { name: "数据集" }));
      expect(await screen.findByRole("heading", { name: "数据集浏览" })).toBeTruthy();
      // 先读布局偏好再画布局，页面标题出现时树还没出现。
      expect(await screen.findByRole("tab", { name: "按格式" })).toBeTruthy();
      expect(screen.getByRole("tab", { name: "按任务" })).toBeTruthy();
      expect(await screen.findByText("共 2 个数据集")).toBeTruthy();
      expect(screen.getByRole("button", { name: "打开 libero_10" })).toBeTruthy();
      expect(screen.getAllByText(/10-12 记录/).length).toBeGreaterThan(0);
      expect(page.router.state.location.pathname).toBe("/datasets");
    } finally {
      page.close();
    }
  });
  // 契约：空型号表默认显示型号标签，选择条件写入 URL，并由服务端筛选列表及两棵树。
  it("型号标签筛选写入路由并更新数量", async () => {
    const requests: Request[] = [];
    const page = mountPage("/datasets", datasetFetch(requests));
    try {
      fireEvent.mouseDown(await screen.findByRole("combobox", { name: "型号标签" }));
      fireEvent.click(await screen.findByRole("option", { name: "franka（1）" }));
      expect(await screen.findByText("共 1 个数据集")).toBeTruthy();
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({ robot_type: "franka" });
      });
      expect(
        requests.some(
          (request) =>
            new URL(request.url).pathname === "/api/datasets/trees" &&
            new URL(request.url).searchParams.get("robot_type") === "franka",
        ),
      ).toBe(true);
      expect(screen.queryByRole("button", { name: "打开 other" })).toBeNull();
    } finally {
      page.close();
    }
  });
  // 契约：Router 会将 fps=20 解码为 number；直达与交互更改均按整数 FPS 发请求。
  it("数字 FPS URL 和交互筛选都保留正确数量", async () => {
    const requests: Request[] = [];
    const page = mountPage("/datasets?fps=20", datasetFetch(requests));
    try {
      expect(await screen.findByText("共 1 个数据集")).toBeTruthy();
      expect(screen.getByRole("button", { name: "打开 libero_10" })).toBeTruthy();
      fireEvent.mouseDown(screen.getByRole("combobox", { name: "FPS" }));
      fireEvent.click(await screen.findByRole("option", { name: "30（1）" }));
      expect(await screen.findByRole("button", { name: "打开 other" })).toBeTruthy();
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({ fps: 30 });
      });
      expect(
        requests.some((request) => new URL(request.url).searchParams.get("fps") === "30"),
      ).toBe(true);
    } finally {
      page.close();
    }
  });

  // 契约：非法 URL 条件留在可修正页面，不请求后端，不把错误条件悄悄变成全量结果。
  it("非法 FPS 参数显示提示而不发数据请求", async () => {
    const requests: Request[] = [];
    const page = mountPage("/datasets?fps=-1", datasetFetch(requests));
    try {
      expect(await screen.findByText("数据集筛选参数不合法")).toBeTruthy();
      expect(
        requests.filter((request) => new URL(request.url).pathname.startsWith("/api/datasets")),
      ).toHaveLength(0);
      fireEvent.click(screen.getByRole("button", { name: "重置筛选" }));
      expect(await screen.findByText("共 2 个数据集")).toBeTruthy();
    } finally {
      page.close();
    }
  });

  // 契约：打开详情不预取子任务，跨视图定位保持永久身份与筛选，统计值与快照值分别标注。
  it("打开详情并跨视图跳转，保留筛选且不预取子任务", async () => {
    const requests: Request[] = [];
    const page = mountPage("/datasets?robot_type=franka", datasetFetch(requests));
    try {
      fireEvent.click(await screen.findByRole("button", { name: "打开 libero_10" }));
      expect(await screen.findByRole("heading", { name: "libero_10" })).toBeTruthy();
      expect(await screen.findByText("dataset-14")).toBeTruthy();
      expect(screen.getByText("统计大小：未统计")).toBeTruthy();
      expect(screen.getByText("10-12 记录：2.0 KiB")).toBeTruthy();
      expect(
        requests.filter((request) => new URL(request.url).pathname === "/api/datasets/subtasks"),
      ).toHaveLength(0);
      expect(page.router.state.location.search).toMatchObject({ selected: taskEntry.entry_path });
      fireEvent.click(screen.getByRole("button", { name: `跳转到 ${formatEntry.entry_path}` }));
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({
          selected: formatEntry.entry_path,
          tree_view: "format",
          robot_type: "franka",
        });
      });
      await waitFor(() => {
        expect(
          requests
            .filter((request) => new URL(request.url).pathname === "/api/datasets/detail")
            .some(
              (request) =>
                new URL(request.url).searchParams.get("entry_path") === formatEntry.entry_path,
            ),
        ).toBe(true);
      });
    } finally {
      page.close();
    }
  });

  // 契约：面板分四组两级，完整计数独立于有界样例，样例沿用统一五段诊断。
  it("一致性面板显示四组两级及聚合样例", async () => {
    const page = mountPage("/datasets", datasetFetch());
    try {
      fireEvent.click(await screen.findByRole("button", { name: "一致性面板" }));
      expect(await screen.findByRole("heading", { name: "JSON 本身" })).toBeTruthy();
      for (const name of ["两个视图之间", "JSON 和磁盘之间", "存储状况"])
        expect(screen.getByRole("heading", { name })).toBeTruthy();
      expect(screen.getAllByText("需要处理")).toHaveLength(4);
      expect(screen.getAllByText("提示")).toHaveLength(4);
      expect(screen.getByText("TOP_LEVEL_UNREGISTERED · 共 7 条（展示 1 条）")).toBeTruthy();
      expect(screen.getByText(/VGX_video/)).toBeTruthy();
      expect(screen.getByText(/核对是否需要登记/)).toBeTruthy();
    } finally {
      page.close();
    }
  });

  // 契约：重新检查只提交选中永久编号的扫描，成功后进入真实作业页并显示完成状态。
  it("重新检查提交单数据集扫描并跳到已完成作业", async () => {
    const requests: Request[] = [];
    const fallback = datasetFetch(requests);
    const page = mountPage(
      `/datasets?selected=${encodeURIComponent(taskEntry.entry_path)}`,
      (request) => {
        const path = new URL(request.url).pathname;
        if (request.method === "POST" || path === `/api/jobs/${completedJob.job_id}`) {
          requests.push(request);
          return Promise.resolve(
            Response.json(completedJob, { status: request.method === "POST" ? 201 : 200 }),
          );
        }
        return fallback(request);
      },
    );
    try {
      fireEvent.click(await screen.findByRole("button", { name: "重新检查" }));
      await waitFor(() => {
        expect(page.router.state.location.pathname).toBe(`/jobs/${completedJob.job_id}`);
      });
      expect(await screen.findByText("成功")).toBeTruthy();
      const submissions = requests.filter((request) => request.method === "POST");
      expect(submissions).toHaveLength(1);
      expect(new URL(submissions[0]?.url ?? "").pathname).toBe("/api/datasets/dataset-14/rescan");
    } finally {
      page.close();
    }
  });
  // 契约：树节点名字单行显示，放不下用省略号，悬停给全名；大小是人读单位，悬停给精确字节，保留出处标记。
  it("树节点名字带省略号 class 和全名提示，大小换算并带精确字节提示", async () => {
    const page = mountPage("/datasets", datasetFetch());
    try {
      expect(await screen.findByText("共 2 个数据集")).toBeTruthy();
      const root = document.querySelector<HTMLElement>('.dataset-tree-name[title="按格式"]');
      expect(root).not.toBeNull();
      expect(root?.textContent).toBe("按格式");
      const meta = root?.parentElement?.querySelector<HTMLElement>(".dataset-tree-meta");
      expect(meta?.textContent).toBe("1 个 · 2.0 KiB · 含 10-12 记录");
      expect(meta?.getAttribute("title")).toBe("2,048 B");
      expect(document.body.textContent).not.toMatch(/2,048 B(?! )/);
    } finally {
      page.close();
    }
  });
  // 契约：详情页里所有表格在自己的容器里横向滚动，不撑宽整页。
  it("详情页每张表格都带横向滚动容器", async () => {
    const page = mountPage("/datasets", datasetFetch());
    try {
      fireEvent.click(await screen.findByRole("button", { name: "打开 libero_10" }));
      expect(await screen.findByRole("heading", { name: "libero_10" })).toBeTruthy();
      await screen.findByRole("region", { name: "链接状态" });
      const main = document.querySelector("main") as HTMLElement;
      const tables = main.querySelectorAll(".ant-table");
      expect(tables.length).toBeGreaterThanOrEqual(2);
      tables.forEach((table) => {
        const scroller = table.querySelector<HTMLElement>(".ant-table-content");
        expect(scroller?.style.overflowX).toBe("auto");
      });
    } finally {
      page.close();
    }
  });
});
