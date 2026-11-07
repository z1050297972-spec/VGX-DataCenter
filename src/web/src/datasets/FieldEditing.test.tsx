// M1.5-10 就地编辑关键行为；通过详情页和 HTTP 请求验证，不依赖组件内部状态。
import { it, expect } from "vitest";
import { screen, fireEvent, within, waitFor } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import type { EditablePage } from "../api/fieldEditing";
import { detail } from "./testSupport";
import { repointFetch } from "./repointTestSupport";
import { originFetch, originUrl, originPreview, previewJob } from "./originTestSupport";

const information: EditablePage = {
  dataset_id: "dataset-14",
  entry_path: "按任务/libero_10",
  document: "数据集信息.json",
  original_robot_types: ["franka"],
  original_fps: [30],
  sha256: "a".repeat(64),
  offset: 0,
  limit: 20,
  total: 1,
  fields: [
    { path: ["fps"], label: "FPS", value: 30, multiple: false },
    { path: ["data_origin"], label: "数据来源", value: "未知", multiple: false },
    { path: ["title"], label: "标题", value: "原来的标题", multiple: false },
    { path: ["robot_model"], label: "机器人型号", value: "Franka", multiple: false },
    { path: ["scene"], label: "场景", value: [], multiple: true },
    { path: ["tasks"], label: "任务", value: [], multiple: true },
    { path: ["subtask_notes"], label: "子任务", value: "原子任务", multiple: false },
    {
      path: ["fields", 0, "value_markdown"],
      label: "第 6 项：任务与场景",
      value: "原来的说明",
      multiple: false,
    },
    {
      path: ["fields", 1, "value_markdown"],
      label: "第 5 项：采集机器人型号",
      value: "原型号说明",
      multiple: false,
    },
    {
      path: ["fields", 2, "value_markdown"],
      label: "第 3 项：类型与组成",
      value: "原来源说明",
      multiple: false,
    },
    {
      path: ["fields", 3, "value_markdown"],
      label: "第 8 项：FPS",
      value: "原帧率说明",
      multiple: false,
    },
  ],
};
function inlinePage(requests: Request[] = []) {
  return mountPage(
    originUrl,
    originFetch(requests, {
      "/api/datasets/detail": () =>
        Response.json({
          ...detail,
          canonical_information: {
            ...detail.information,
            content: JSON.stringify({
              title: "原来的标题",
              fields: [
                { number: 6, name: "任务与场景", value_markdown: "原来的说明" },
                { number: 5, name: "采集机器人型号", value_markdown: "原型号说明" },
                { number: 4, name: "数据大小", value_markdown: "旧大小" },
              ],
            }),
          },
        }),
      "/api/datasets/dataset-14/editable-fields": (request) =>
        Response.json(
          new URL(request.url).searchParams.get("document") === "原始路径.json"
            ? { ...information, document: "原始路径.json", fields: [], total: 0 }
            : information,
        ),
      "/api/navigation/fields/preview": () =>
        Response.json({ ...previewJob, type_name: "nav_fields_preview" }),
      "/api/navigation/previews/301": () =>
        Response.json({ ...originPreview, operation: "edit_dataset_fields" }),
    }),
  );
}

// 契约：14项紧跟页头；编辑模式只替换原行，不增加第二份信息或旧编辑器。
it("14项位于最上方且第6项原地编辑", async () => {
  const page = inlinePage();
  try {
    const informationSection = await screen.findByRole("region", { name: "14 项数据集信息" });
    const detailSection = screen.getByRole("region", { name: "数据集详情" });
    expect(detailSection.querySelector("header")?.nextElementSibling).toBe(
      informationSection.parentElement,
    );
    expect(screen.queryByRole("button", { name: "编辑导航层字段" })).toBeNull();
    fireEvent.click(within(detailSection).getByRole("button", { name: "编辑" }));
    await screen.findByRole("textbox", { name: "第 6 项：任务与场景" });
    const row = within(screen.getByRole("region", { name: "14 项数据集信息" })).getByRole("row", {
      name: /任务与场景/,
    });
    expect(within(row).getByRole("textbox", { name: "第 6 项：任务与场景" })).toBeTruthy();
    expect(within(row).getByRole("combobox", { name: "场景" })).toBeTruthy();
    expect(within(row).getByRole("combobox", { name: "任务" })).toBeTruthy();
    expect(screen.getAllByRole("region", { name: "14 项数据集信息" })).toHaveLength(1);
    expect(screen.queryByRole("combobox", { name: "选择编辑文件" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: /第 4 项/ })).toBeNull();
  } finally {
    page.close();
  }
});
// 契约：就地编辑只读取数据集信息，不展示数据块字段或请求原始路径编辑页。
it("编辑模式只读取数据集信息且没有数据块字段", async () => {
  const requests: Request[] = [];
  const page = inlinePage(requests);
  try {
    fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
    await screen.findByRole("textbox", { name: "第 6 项：任务与场景" });
    expect(
      requests
        .filter((request) => new URL(request.url).pathname.endsWith("/editable-fields"))
        .map((request) => new URL(request.url).searchParams.get("document")),
    ).toEqual(["数据集信息.json"]);
    expect(screen.queryByRole("region", { name: "数据块字段" })).toBeNull();
    expect(screen.queryByText("数据块字段")).toBeNull();
  } finally {
    page.close();
  }
});

// 契约：第3、8项的来源与FPS保留文字框，和第6项分类一起按顶层路径提交；替代独立来源编辑测试。
it("来源FPS与分类并入字段编辑并按原路径提交", async () => {
  const requests: Request[] = [];
  const page = inlinePage(requests);
  try {
    fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "第 6 项：任务与场景" }), {
      target: { value: "新的说明" },
    });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "场景" }));
    fireEvent.click(await screen.findByRole("option", { name: "桌面" }));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "场景" }));
    fireEvent.click(await screen.findByRole("option", { name: "家居-厨房" }));
    const section = within(screen.getByRole("region", { name: "14 项数据集信息" }));
    const fpsRow = within(section.getByRole("row", { name: /原文件 fps/ }));
    expect(fpsRow.getByRole("textbox", { name: "第 8 项：FPS" })).toBeTruthy();
    expect(fpsRow.getByText("原文件 fps（索引参考）：30")).toBeTruthy();
    fireEvent.change(fpsRow.getByRole("spinbutton", { name: "FPS" }), { target: { value: "50" } });
    const originRow = within(section.getByRole("row", { name: /类型与组成/ }));
    expect(originRow.getByRole("textbox", { name: "第 3 项：类型与组成" })).toBeTruthy();
    fireEvent.mouseDown(originRow.getByRole("combobox", { name: "数据来源" }));
    fireEvent.click(await screen.findByRole("option", { name: "仿真生成" }));
    expect(screen.queryByRole("region", { name: "数据来源标注" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "预览改动" }));
    await waitFor(() => {
      expect(
        requests.some(
          (request) => new URL(request.url).pathname === "/api/navigation/fields/preview",
        ),
      ).toBe(true);
    });
    const request = requests.find(
      (request) => new URL(request.url).pathname === "/api/navigation/fields/preview",
    );
    expect(await request?.clone().json()).toEqual({
      dataset_id: "dataset-14",
      changes: [
        {
          document: "数据集信息.json",
          expected_sha256: information.sha256,
          path: ["fields", 0, "value_markdown"],
          value: "新的说明",
        },
        {
          document: "数据集信息.json",
          expected_sha256: information.sha256,
          path: ["scene"],
          value: ["tabletop", "kitchen"],
        },
        {
          document: "数据集信息.json",
          expected_sha256: information.sha256,
          path: ["fps"],
          value: 50,
        },
        {
          document: "数据集信息.json",
          expected_sha256: information.sha256,
          path: ["data_origin"],
          value: "仿真生成",
        },
      ],
    });
  } finally {
    page.close();
  }
});

// 契约：取消只丢弃草稿，返回原只读内容，不提交导航写入。
it("取消就地编辑恢复原只读值", async () => {
  const requests: Request[] = [];
  const page = inlinePage(requests);
  try {
    fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "第 6 项：任务与场景" }), {
      target: { value: "不要保存的说明" },
    });
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(await screen.findByText("原来的说明")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "第 6 项：任务与场景" })).toBeNull();
    expect(screen.queryByRole("region", { name: "数据块字段" })).toBeNull();
    expect(screen.queryByText("不要保存的说明")).toBeNull();
    expect(requests.filter((request) => request.method === "POST")).toHaveLength(0);
  } finally {
    page.close();
  }
});

// 契约：字段编辑作业不再有自己的撤回按钮，走通用撤回页：先预览，确认只引用保存的反向预览。
it("字段编辑作业走通用撤回流程", async () => {
  const requests: Request[] = [];
  const page = mountPage("/jobs/401", repointFetch(requests));
  try {
    expect(screen.queryByRole("button", { name: "预览撤回导航改动" })).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "撤回导航写入" }));
    fireEvent.click(await screen.findByRole("button", { name: "预览撤回" }));
    const confirm = await screen.findByRole("button", { name: "确认导航写入" });
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(1);
    fireEvent.click(confirm);
    expect(await screen.findByRole("region", { name: "撤回导航改动 #402" })).toBeTruthy();
    expect(page.router.state.location.pathname).toBe("/jobs/401/revert");
    const posts = requests.filter((r) => r.method === "POST");
    expect(posts.map((r) => new URL(r.url).pathname)).toEqual([
      "/api/jobs/401/revert-previews",
      "/api/navigation/writes",
    ]);
    expect(await posts[1]?.clone().json()).toEqual({
      preview_job_id: "302",
      acknowledged_queue_job_ids: [],
    });
  } finally {
    page.close();
  }
});

// 契约：编辑后导航层结构化值在常规详情中显示，不要求再次打开编辑器，也不覆盖原文件标签。
it("详情展示保存的导航标题型号与分类", async () => {
  const { detail } = await import("./testSupport");
  const page = mountPage(
    originUrl,
    originFetch([], {
      "/api/datasets/detail": () =>
        Response.json({
          ...detail,
          canonical_information: {
            ...detail.information,
            content: JSON.stringify({
              title: "人工维护标题",
              robot_model: "平台型号",
              scene: "实验室",
              tasks: ["抓取", "收纳"],
              fields: [],
            }),
          },
        }),
    }),
  );
  try {
    const summary = await screen.findByRole("region", { name: "导航层结构化信息" });
    for (const text of ["人工维护标题", "平台型号", "实验室", "抓取、收纳"])
      expect(within(summary).getByText(text)).toBeTruthy();
  } finally {
    page.close();
  }
});

// 契约：详情只读规范副本的子任务，保留原始换行；空值和缺字段显示未填写。
it.each(["抓取杯子\n放到桌上\n  保留缩进", "", undefined])(
  "详情显示子任务记事本：%s",
  async (notes) => {
    const { detail } = await import("./testSupport");
    const page = mountPage(
      originUrl,
      originFetch([], {
        "/api/datasets/detail": () =>
          Response.json({
            ...detail,
            canonical_information: {
              ...detail.information,
              content: JSON.stringify({ fields: [], subtask_notes: notes }),
            },
          }),
      }),
    );
    try {
      const section = await screen.findByRole("region", { name: "子任务" });
      expect(
        within(section).getByText(notes || "未填写", { exact: true, normalizer: (text) => text })
          .textContent,
      ).toBe(notes || "未填写");
      expect(screen.queryByRole("button", { name: "打开 子任务.json" })).toBeNull();
      expect(within(section).getByRole("link", { name: "编辑子任务" }).getAttribute("href")).toBe(
        "#dataset-subtask-notes",
      );
    } finally {
      page.close();
    }
  },
);
