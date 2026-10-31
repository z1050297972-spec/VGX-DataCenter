// 分类通过真实 Router、Query 与 HTTP 边界验证，期望编码独立取自工单词表。
import { it, expect } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { datasetFetch, detail } from "./testSupport";
import { originFetch } from "./originTestSupport";

// 契约：场景单选、任务多选显示计数；URL 恢复任务数组，列表和树都按重复参数传任务交集。
it("分类条件往返 URL 并同时传给列表与树", async () => {
  const requests: Request[] = [];
  const page = mountPage(
    "/datasets?scene=tabletop&tasks=%5B%22pick_place%22%5D",
    datasetFetch(requests),
  );
  try {
    expect(await screen.findByRole("combobox", { name: "筛选场景" })).toBeTruthy();
    expect(screen.getByText("桌面（1）")).toBeTruthy();
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "筛选任务" }));
    fireEvent.click(await screen.findByRole("option", { name: "收纳整理（1）" }));
    await waitFor(() => {
      expect(page.router.state.location.search).toMatchObject({
        scene: "tabletop",
        tasks: ["pick_place", "tidy"],
      });
      for (const path of ["/api/datasets", "/api/datasets/trees"]) {
        expect(
          requests.some((request) => {
            const url = new URL(request.url);
            return (
              url.pathname === path &&
              url.searchParams.get("scene") === "tabletop" &&
              url.searchParams.getAll("tasks").join(",") === "pick_place,tidy"
            );
          }),
        ).toBe(true);
      }
    });
    // 未标注与具体任务不可能同时满足；选择它应清掉原来的具体任务。
    fireEvent.click(await screen.findByRole("option", { name: "未标注（1）" }));
    await waitFor(() => {
      expect(page.router.state.location.search.tasks).toEqual(["unlabeled"]);
    });
  } finally {
    page.close();
  }
});

// 契约：三种布局都可进入场景组；入口仍打开规范路径，虚拟路径只用于浏览分组。
it.each(["A", "B", "C"] as const)("布局 %s 按场景分组浏览", async (layout) => {
  const page = mountPage("/datasets", datasetFetch([], { layout, updated_at: null }));
  try {
    if (layout === "A") {
      fireEvent.click(await screen.findByRole("tab", { name: "按场景" }));
      const tree = screen.getByRole("complementary", { name: "视图树" });
      expect(await within(tree).findByText("桌面")).toBeTruthy();
      fireEvent.click(within(tree).getByText("libero_10"));
    } else if (layout === "B") {
      fireEvent.click(await screen.findByRole("radio", { name: "按场景" }));
      const table = screen.getByRole("region", { name: "树形表格" });
      expect(await within(table).findByText("桌面")).toBeTruthy();
      fireEvent.click(within(table).getByRole("button", { name: "打开 libero_10" }));
    } else {
      const columns = await screen.findByRole("region", { name: "目录分栏" });
      fireEvent.click(await within(columns).findByRole("button", { name: "进入 按场景" }));
      fireEvent.click(await within(columns).findByRole("button", { name: "进入 桌面" }));
      fireEvent.click(await within(columns).findByRole("button", { name: "打开 libero_10" }));
    }
    await waitFor(() => {
      expect(page.router.state.location.search).toMatchObject({
        tree_view: "scene",
        selected: "按任务/libero_10",
      });
    });
    expect(await screen.findByRole("heading", { name: "libero_10", level: 3 })).toBeTruthy();
  } finally {
    page.close();
  }
});

// 契约：列表与现场详情从同一个服务端词表取得中文名，导航型号与原始型号标签分别显示。
it("列表和详情显示分类中文名称", async () => {
  const page = mountPage(
    "/datasets",
    originFetch([], {
      "/api/datasets/detail": () =>
        Response.json({
          ...detail,
          canonical_information: {
            ...detail.information,
            content: JSON.stringify({
              title: "人工标题",
              robot_model: "Franka",
              scene: "tabletop",
              tasks: ["pick_place", "tidy"],
              fields: [],
            }),
          },
        }),
    }),
  );
  try {
    const list = await screen.findByRole("region", { name: "数据集列表" });
    expect(await within(list).findByText(/场景：桌面/)).toBeTruthy();
    expect(within(list).getByText(/任务：抓取放置、收纳整理/)).toBeTruthy();
    fireEvent.click(within(list).getByRole("button", { name: "打开 libero_10" }));
    const summary = await screen.findByRole("region", { name: "导航层结构化信息" });
    expect(await within(summary).findByText("桌面")).toBeTruthy();
    expect(within(summary).getByText("抓取放置、收纳整理")).toBeTruthy();
    expect(within(summary).getByText("Franka")).toBeTruthy();
  } finally {
    page.close();
  }
});
