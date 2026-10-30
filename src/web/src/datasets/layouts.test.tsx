// M1-05 布局 A、B、C：共用状态的行为在三种布局下相同；切换保留状态并按账号保存。
import { describe, it, expect } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { problemResponse } from "../accounts/testSupport";
import type { FetchImplementation } from "../api/client";
import { datasetFetch, formatEntry, taskEntry, type LayoutStore } from "./testSupport";

type Layout = LayoutStore["layout"];
const LAYOUTS: Layout[] = ["A", "B", "C"];
const store = (layout: Layout): LayoutStore => ({ layout, updated_at: null });
// 每种布局独有的区域；共用状态的测试先确认确实渲染了该布局，不能被另一种布局蒙混过关。
const MARKER: Record<Layout, [role: "complementary" | "region", name: string]> = {
  A: ["complementary", "视图树"],
  B: ["region", "树形表格"],
  C: ["region", "目录分栏"],
};
async function expectLayout(layout: Layout): Promise<void> {
  const [role, name] = MARKER[layout];
  expect(await screen.findByRole(role, { name })).toBeTruthy();
}
const selectedUrl = `/datasets?robot_type=franka&selected=${encodeURIComponent(taskEntry.entry_path)}`;

describe.each(LAYOUTS)("布局 %s 共用状态", (layout) => {
  // 契约：该布局下，布局切换器标出当前布局。
  it("切换器标出当前布局", async () => {
    const page = mountPage("/datasets", datasetFetch([], store(layout)));
    try {
      await expectLayout(layout);
      const radio = await screen.findByRole("radio", { name: `布局 ${layout}` });
      expect((radio as HTMLInputElement).checked).toBe(true);
    } finally {
      page.close();
    }
  });
  // 契约：URL 带入的筛选和选中项，在该布局下都生效：筛选框显示所选值，详情打开所选数据集。
  it("URL 带入的筛选与选中项都生效", async () => {
    const page = mountPage(selectedUrl, datasetFetch([], store(layout)));
    try {
      await expectLayout(layout);
      expect(await screen.findByRole("heading", { name: "libero_10", level: 3 })).toBeTruthy();
      expect(screen.getByText("franka（1）")).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 契约：筛选写入 URL，并且树按同一条件向服务端重新请求。
  it("筛选写入 URL 并同时过滤树", async () => {
    const requests: Request[] = [];
    const page = mountPage("/datasets", datasetFetch(requests, store(layout)));
    try {
      await expectLayout(layout);
      fireEvent.mouseDown(await screen.findByRole("combobox", { name: "型号标签" }));
      fireEvent.click(await screen.findByRole("option", { name: "franka（1）" }));
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({ robot_type: "franka" });
      });
      await waitFor(() => {
        expect(
          requests.some(
            (request) =>
              new URL(request.url).pathname === "/api/datasets/trees" &&
              new URL(request.url).searchParams.get("robot_type") === "franka",
          ),
        ).toBe(true);
      });
    } finally {
      page.close();
    }
  });
  // 契约：关闭详情只清除选中项，筛选条件保留。
  it("返回列表后筛选保留", async () => {
    const page = mountPage(selectedUrl, datasetFetch([], store(layout)));
    try {
      await expectLayout(layout);
      fireEvent.click(await screen.findByRole("button", { name: "返回列表" }));
      await waitFor(() => {
        expect(page.router.state.location.search.selected).toBeUndefined();
      });
      expect(page.router.state.location.search).toMatchObject({ robot_type: "franka" });
    } finally {
      page.close();
    }
  });
  // 契约：一致性面板在该布局下可以打开，内容是同一份四组两级发现。
  it("一致性面板可打开", async () => {
    const page = mountPage("/datasets", datasetFetch([], store(layout)));
    try {
      await expectLayout(layout);
      fireEvent.click(await screen.findByRole("button", { name: "一致性面板" }));
      expect(await screen.findByRole("heading", { name: "JSON 本身" })).toBeTruthy();
    } finally {
      page.close();
    }
  });
});

describe("布局切换与保存", () => {
  // 契约：A→B→C 切换时 URL 里的筛选和选中项不变，详情仍打开；每次切换向接口保存所选布局。
  it("切换保留筛选与选中项，并保存所选布局", async () => {
    const requests: Request[] = [];
    const saved = store("A");
    const page = mountPage(selectedUrl, datasetFetch(requests, saved));
    try {
      await screen.findByRole("heading", { name: "libero_10", level: 3 });
      const before = page.router.state.location.search;
      for (const next of ["B", "C"] as const) {
        fireEvent.click(screen.getByRole("radio", { name: `布局 ${next}` }));
        await waitFor(() => {
          expect(saved.layout).toBe(next);
        });
        expect(await screen.findByRole("heading", { name: "libero_10", level: 3 })).toBeTruthy();
        expect(screen.getByText("franka（1）")).toBeTruthy();
        expect(page.router.state.location.search).toEqual(before);
      }
      const puts = requests.filter((request) => request.method === "PUT");
      expect(puts).toHaveLength(2);
      expect(
        puts.every((request) => new URL(request.url).pathname === "/api/datasets/layout"),
      ).toBe(true);
    } finally {
      page.close();
    }
  });
  // 契约：切换布局不重新请求列表、树，已加载内容不闪。
  it("切换布局不重新请求列表和树", async () => {
    const requests: Request[] = [];
    const page = mountPage("/datasets", datasetFetch(requests, store("A")));
    try {
      expect(await screen.findByText("共 2 个数据集")).toBeTruthy();
      const count = () =>
        requests.filter((request) => /\/datasets(\/trees)?$/.test(new URL(request.url).pathname))
          .length;
      const loaded = count();
      fireEvent.click(screen.getByRole("radio", { name: "布局 B" }));
      await screen.findByRole("region", { name: "树形表格" });
      expect(count()).toBe(loaded);
    } finally {
      page.close();
    }
  });
  // 契约：布局按账号保存：账号 1 保存 C，重新打开页面是 C；账号 2 没有偏好，仍是 A。
  it("重新打开恢复上次布局，另一个账号不受影响", async () => {
    const first = mountPage("/datasets", datasetFetch([], store("C")));
    try {
      expect(await screen.findByRole("region", { name: "目录分栏" })).toBeTruthy();
    } finally {
      first.close();
    }
    const second = mountPage("/datasets", datasetFetch([], store("A")));
    try {
      expect(await screen.findByRole("complementary", { name: "视图树" })).toBeTruthy();
      expect(screen.queryByRole("region", { name: "目录分栏" })).toBeNull();
    } finally {
      second.close();
    }
  });
  // 契约：保存失败时显示统一诊断，已经切换的布局本次会话内保持，不静默回退。
  it("保存布局失败显示诊断且保持所选布局", async () => {
    const inner = datasetFetch([], store("A"));
    const failing: FetchImplementation = (request) =>
      request.method === "PUT" ? Promise.resolve(problemResponse(502)) : inner(request);
    const page = mountPage("/datasets", failing);
    try {
      fireEvent.click(await screen.findByRole("radio", { name: "布局 B" }));
      expect(await screen.findByRole("region", { name: "树形表格" })).toBeTruthy();
      expect(await screen.findByText("布局偏好未能保存")).toBeTruthy();
      expect(screen.getByRole<HTMLInputElement>("radio", { name: "布局 B" }).checked).toBe(true);
    } finally {
      page.close();
    }
  });
  // 契约：读取偏好失败时退回布局 A 并给出诊断，数据集仍可浏览。
  it("读取布局偏好失败时用布局 A 并提示", async () => {
    const inner = datasetFetch([], store("C"));
    const failing: FetchImplementation = (request) =>
      new URL(request.url).pathname === "/api/datasets/layout"
        ? Promise.resolve(problemResponse(502))
        : inner(request);
    const page = mountPage("/datasets", failing);
    try {
      expect(await screen.findByRole("complementary", { name: "视图树" })).toBeTruthy();
      expect(await screen.findByText("布局偏好未能读取")).toBeTruthy();
      expect(await screen.findByText("共 2 个数据集")).toBeTruthy();
    } finally {
      page.close();
    }
  });
});

describe("布局 B", () => {
  // 契约：树形表格显示当前视图的目录和入口；点入口名在抽屉里打开详情，选中项写入 URL，列表仍在背景。
  it("点击入口在抽屉打开详情", async () => {
    const page = mountPage("/datasets", datasetFetch([], store("B")));
    try {
      const table = await screen.findByRole("region", { name: "树形表格" });
      fireEvent.click(await within(table).findByRole("button", { name: "打开 libero_10" }));
      // 测试环境里 antd 的 useId 固定为 test-id，对话框名字不可靠；页面里只有这一个对话框。
      const drawer = await screen.findByRole("dialog");
      expect(
        await within(drawer).findByRole("heading", { name: "libero_10", level: 3 }),
      ).toBeTruthy();
      expect(page.router.state.location.search).toMatchObject({
        selected: formatEntry.entry_path,
      });
      expect(screen.getByRole("region", { name: "树形表格" })).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 契约：视图切换（按格式/按任务）写入 URL，表格换成另一棵树；名字带省略号和全名提示，表格在自己的容器里横向滚动。
  it("视图切换换树，名字省略，表格自带横向滚动", async () => {
    const page = mountPage("/datasets", datasetFetch([], store("B")));
    try {
      const table = await screen.findByRole("region", { name: "树形表格" });
      await within(table).findByRole("button", { name: "打开 libero_10" });
      const name = table.querySelector<HTMLElement>('.dataset-tree-name[title="libero_10"]');
      expect(name).not.toBeNull();
      expect(table.querySelector<HTMLElement>(".ant-table-content")?.style.overflowX).toBe("auto");
      fireEvent.click(screen.getByRole("radio", { name: "按任务" }));
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({ tree_view: "task" });
      });
      fireEvent.click(await within(table).findByRole("button", { name: "打开 libero_10" }));
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({
          selected: taskEntry.entry_path,
        });
      });
    } finally {
      page.close();
    }
  });
});

describe("布局 C", () => {
  // 契约：逐级进入目录，选入口后右侧文件预览显示详情；路径栏逐级显示，选中项写入 URL。
  it("逐级进入目录并在预览区查看详情", async () => {
    const page = mountPage("/datasets?robot_type=franka", datasetFetch([], store("C")));
    try {
      const columns = await screen.findByRole("region", { name: "目录分栏" });
      expect(screen.getByText("从目录开始浏览")).toBeTruthy();
      fireEvent.click(within(columns).getByRole("button", { name: "进入 按任务" }));
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({
          entry_path: "按任务",
          tree_view: "task",
          robot_type: "franka",
        });
      });
      fireEvent.click(await within(columns).findByRole("button", { name: "打开 libero_10" }));
      const preview = await screen.findByRole("region", { name: "文件预览" });
      expect(
        await within(preview).findByRole("heading", { name: "libero_10", level: 3 }),
      ).toBeTruthy();
      expect(page.router.state.location.search).toMatchObject({ selected: taskEntry.entry_path });
      const path = screen.getByRole("navigation", { name: "当前路径" });
      expect(within(path).getByRole("button", { name: "按任务" })).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 契约：点路径栏的上一级，回到该目录并清除选中项，筛选保留。
  it("点路径栏上级回到目录并保留筛选", async () => {
    const page = mountPage(selectedUrl, datasetFetch([], store("C")));
    try {
      await screen.findByRole("heading", { name: "libero_10", level: 3 });
      const path = screen.getByRole("navigation", { name: "当前路径" });
      fireEvent.click(within(path).getByRole("button", { name: "按任务" }));
      await waitFor(() => {
        expect(page.router.state.location.search.selected).toBeUndefined();
      });
      expect(page.router.state.location.search).toMatchObject({
        robot_type: "franka",
        entry_path: "按任务",
      });
      expect(screen.getByText("从目录开始浏览")).toBeTruthy();
    } finally {
      page.close();
    }
  });
  // 契约：进入一个视图的目录后，根列里另一个视图的数量和大小仍是真实值，不能因目录筛选变成 0；
  // 并且能从“按格式”进入、打开入口并预览。
  it("进入按任务后根列按格式仍显示真实数量，且能从按格式打开入口", async () => {
    const requests: Request[] = [];
    const page = mountPage("/datasets", datasetFetch(requests, store("C")));
    try {
      const columns = await screen.findByRole("region", { name: "目录分栏" });
      fireEvent.click(await within(columns).findByRole("button", { name: "进入 按任务" }));
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({ entry_path: "按任务" });
      });
      const format = await within(columns).findByRole("button", { name: "进入 按格式" });
      expect(format.textContent).toContain("1 个");
      expect(format.textContent).not.toContain("0 个");
      expect(
        requests
          .filter((request) => new URL(request.url).pathname === "/api/datasets/trees")
          .every((request) => !new URL(request.url).searchParams.has("entry_path")),
      ).toBe(true);
      fireEvent.click(format);
      await waitFor(() => {
        expect(page.router.state.location.search).toMatchObject({ entry_path: "按格式" });
      });
      fireEvent.click(await within(columns).findByRole("button", { name: "打开 libero_10" }));
      const preview = await screen.findByRole("region", { name: "文件预览" });
      expect(
        await within(preview).findByRole("heading", { name: "libero_10", level: 3 }),
      ).toBeTruthy();
      expect(page.router.state.location.search).toMatchObject({ selected: formatEntry.entry_path });
    } finally {
      page.close();
    }
  });
});
