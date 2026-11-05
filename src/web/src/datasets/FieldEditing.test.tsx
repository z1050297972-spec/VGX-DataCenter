// M1.5-02：经真实路由、查询和HTTP边界验证编辑，不替换内部组件。
import { it, expect } from "vitest";
import { fireEvent, screen, within, waitFor } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import type { components } from "../api/schema";
import { filters } from "./testSupport";
import { repointFetch } from "./repointTestSupport";
import { originFetch, originUrl, originPreview, previewJob, writingJob } from "./originTestSupport";

// 冷启动要加载数据集路由和编辑器两层动态模块；等待有界，与创建页的冷加载预算一致。
const EDITOR_LOAD_TIMEOUT_MS = 2500;

const information: components["schemas"]["EditableFieldsPage"] = {
  dataset_id: "dataset-14",
  entry_path: "按任务/libero_10",
  document: "数据集信息.json",
  original_robot_types: [],
  sha256: "a".repeat(64),
  offset: 0,
  limit: 20,
  total: 1,
  fields: [
    { path: ["title"], label: "标题", value: "原来的标题", multiple: false },
    { path: ["robot_model"], label: "机器人型号", value: "unknown", multiple: false },
    { path: ["scene"], label: "场景", value: "", multiple: false },
    { path: ["tasks"], label: "任务", value: [], multiple: true },
    {
      path: ["fields", 5, "value_markdown"],
      label: "第 6 项：任务场景",
      value: "原来的说明",
      multiple: false,
    },
  ],
};

// 契约：表单只提交实际变更，逐字段显示服务端差异，用户确认后仅引用已查看的预览。
it("编辑信息并预览确认", async () => {
  const requests: Request[] = [];
  const page = mountPage(
    originUrl,
    originFetch(requests, {
      "/api/datasets/dataset-14/editable-fields": () => Response.json(information),
      "/api/navigation/fields/preview": () =>
        Response.json({ ...previewJob, type_name: "nav_fields_preview" }, { status: 201 }),
      "/api/navigation/previews/301": () =>
        Response.json({
          ...originPreview,
          operation: "edit_dataset_fields",
          report: {
            ...originPreview.report,
            listed_changes: [
              {
                file: "按任务/libero_10/数据集信息.json",
                json_path: "robot_model",
                before: '"unknown"',
                after: '"Franka"',
              },
            ],
          },
        }),
      "/api/navigation/fields/previews/301/apply": () => Response.json(writingJob, { status: 201 }),
    }),
  );
  try {
    fireEvent.click(
      await screen.findByRole(
        "button",
        { name: "编辑导航层字段" },
        { timeout: EDITOR_LOAD_TIMEOUT_MS },
      ),
    );
    const editor = await screen.findByRole("region", { name: "导航层字段编辑" });
    fireEvent.change(await within(editor).findByRole("textbox", { name: "机器人型号" }), {
      target: { value: "Franka" },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "预览字段改动" }));
    const diff = await screen.findByRole("region", { name: "字段预览差异" });
    expect(within(diff).getByText('"unknown"')).toBeTruthy();
    expect(within(diff).getByText('"Franka"')).toBeTruthy();
    const post = requests.find((r) => new URL(r.url).pathname === "/api/navigation/fields/preview");
    expect(await post?.clone().json()).toEqual({
      dataset_id: "dataset-14",
      changes: [
        {
          document: "数据集信息.json",
          expected_sha256: "a".repeat(64),
          path: ["robot_model"],
          value: "Franka",
        },
      ],
    });
    expect(requests.filter((r) => new URL(r.url).pathname.endsWith("/apply"))).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "确认字段写入" }));
    expect(await screen.findByRole("region", { name: "修改字段 #302" })).toBeTruthy();
    expect(page.router.state.location.pathname).toBe("/datasets");
    expect(requests.filter((r) => new URL(r.url).pathname.endsWith("/apply"))).toHaveLength(1);
  } finally {
    page.close();
  }
});

// 契约：原文件型号参考与导航型号有区别时提示；场景只选一个，任务允许多个；改动使旧预览失效。
it("型号参考和分类编辑后清除旧预览", async () => {
  const requests: Request[] = [];
  const page = mountPage(
    originUrl,
    originFetch(requests, {
      "/api/datasets/dataset-14/editable-fields": () =>
        Response.json({ ...information, original_robot_types: ["franka"] }),
      "/api/navigation/fields/preview": () =>
        Response.json({ ...previewJob, type_name: "nav_fields_preview" }),
      "/api/navigation/previews/301": () =>
        Response.json({ ...originPreview, operation: "edit_dataset_fields" }),
    }),
  );
  try {
    fireEvent.click(
      await screen.findByRole(
        "button",
        { name: "编辑导航层字段" },
        { timeout: EDITOR_LOAD_TIMEOUT_MS },
      ),
    );
    expect(await screen.findByText("原文件 robot_type（索引参考）：franka")).toBeTruthy();
    expect(screen.getByText("导航型号与原文件型号不同")).toBeTruthy();
    const scene = screen.getByRole("combobox", { name: "场景" });
    fireEvent.mouseDown(scene);
    fireEvent.click(await screen.findByRole("option", { name: "家居-厨房" }));
    const tasks = screen.getByRole("combobox", { name: "任务" });
    fireEvent.mouseDown(tasks);
    fireEvent.click(await screen.findByRole("option", { name: "抓取放置" }));
    fireEvent.click(await screen.findByRole("option", { name: "收纳整理" }));
    fireEvent.click(screen.getByRole("button", { name: "预览字段改动" }));
    await screen.findByRole("button", { name: "确认字段写入" });
    const posted = requests.find(
      (r) => new URL(r.url).pathname === "/api/navigation/fields/preview",
    );
    expect(await posted?.clone().json()).toMatchObject({
      changes: [
        {
          document: "数据集信息.json",
          expected_sha256: information.sha256,
          path: ["scene"],
          value: "kitchen",
        },
        {
          document: "数据集信息.json",
          expected_sha256: information.sha256,
          path: ["tasks"],
          value: ["pick_place", "tidy"],
        },
      ],
    });
    fireEvent.change(screen.getByRole("textbox", { name: "机器人型号" }), {
      target: { value: "修改草稿" },
    });
    expect(screen.queryByRole("button", { name: "确认字段写入" })).toBeNull();
  } finally {
    page.close();
  }
});

// 契约：翻页保留局部草稿；任一页观察到同文件哈希变化，切换文件也不能恢复旧草稿的确认资格。
it("分页保留草稿并锁住过期编辑", async () => {
  const requests: Request[] = [];
  const page = mountPage(
    originUrl,
    originFetch(requests, {
      "/api/datasets/dataset-14/editable-fields": (request) => {
        const params = new URL(request.url).searchParams;
        if (params.get("document") === "数据集信息.json") return Response.json(information);
        const next = params.get("offset") === "20";
        return Response.json({
          ...information,
          document: "原始路径.json",
          sha256: next ? "b".repeat(64) : information.sha256,
          total: 21,
          offset: next ? 20 : 0,
          fields: [
            {
              path: ["sources", next ? 20 : 0, "notes"],
              label: next ? "第21个数据块备注" : "第1个数据块备注",
              value: "原描述",
              multiple: false,
            },
          ],
        });
      },
    }),
  );
  try {
    fireEvent.click(
      await screen.findByRole(
        "button",
        { name: "编辑导航层字段" },
        { timeout: EDITOR_LOAD_TIMEOUT_MS },
      ),
    );
    await screen.findByRole("textbox", { name: "机器人型号" });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择编辑文件" }));
    fireEvent.click(await screen.findByRole("option", { name: "原始路径.json" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "第1个数据块备注" }), {
      target: { value: "人工描述" },
    });
    fireEvent.click(screen.getByRole("button", { name: "编辑下一页" }));
    await screen.findByRole("textbox", { name: "第21个数据块备注" });
    expect(screen.getByText("文件已变化，请取消编辑后重新加载")).toBeTruthy();
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择编辑文件" }));
    fireEvent.click(await screen.findByRole("option", { name: "数据集信息.json" }));
    await screen.findByRole("textbox", { name: "机器人型号" });
    expect(screen.getByRole("button", { name: "预览字段改动" }).hasAttribute("disabled")).toBe(
      true,
    );
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(0);
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

// 契约：分类支持回车新建或选取平台已有自定义值，提交保持场景单值、任务多值及去首尾空格。
it.each(["新建", "已有"])("编辑器提交%s自定义分类", async (mode) => {
  const requests: Request[] = [];
  const page = mountPage(
    originUrl,
    originFetch(requests, {
      "/api/datasets/dataset-14/editable-fields": () => Response.json(information),
      "/api/datasets/filters": () =>
        Response.json({
          ...filters,
          scenes: [...filters.scenes, { value: "共享场景", label: "共享场景" }],
          tasks: [...filters.tasks, { value: "共享任务", label: "共享任务" }],
        }),
      "/api/navigation/fields/preview": () =>
        Response.json({ ...previewJob, type_name: "nav_fields_preview" }),
      "/api/navigation/previews/301": () =>
        Response.json({ ...originPreview, operation: "edit_dataset_fields" }),
    }),
  );
  try {
    fireEvent.click(
      await screen.findByRole(
        "button",
        { name: "编辑导航层字段" },
        { timeout: EDITOR_LOAD_TIMEOUT_MS },
      ),
    );
    const editor = await screen.findByRole("region", { name: "导航层字段编辑" });
    const scene = await within(editor).findByRole("combobox", { name: "场景" });
    const tasks = within(editor).getByRole("combobox", { name: "任务" });
    if (mode === "新建") {
      fireEvent.change(scene, { target: { value: "  自定义实验区  " } });
      fireEvent.keyDown(scene, { key: "Enter", code: "Enter", keyCode: 13 });
      for (const value of ["  自定义搬运  ", "自定义巡查"]) {
        fireEvent.change(tasks, { target: { value } });
        fireEvent.keyDown(tasks, { key: "Enter", code: "Enter", keyCode: 13 });
        fireEvent.keyUp(tasks, { key: "Enter", code: "Enter", keyCode: 13 });
      }
    } else {
      fireEvent.mouseDown(scene);
      expect(within(editor).queryByRole("option", { name: "未标注" })).toBeNull();
      fireEvent.click(await within(editor).findByRole("option", { name: "共享场景" }));
      fireEvent.mouseDown(tasks);
      expect(within(editor).getAllByRole("option", { name: "抓取放置" })).toHaveLength(1);
      fireEvent.click(await within(editor).findByRole("option", { name: "共享任务" }));
    }
    expect(within(editor).queryByText(/不在词表/)).toBeNull();
    fireEvent.click(within(editor).getByRole("button", { name: "预览字段改动" }));
    await waitFor(() => {
      expect(
        requests.some((r) => new URL(r.url).pathname === "/api/navigation/fields/preview"),
      ).toBe(true);
    });
    const posted = requests.find(
      (r) => new URL(r.url).pathname === "/api/navigation/fields/preview",
    );
    expect(await posted?.clone().json()).toMatchObject({
      changes: [
        { path: ["scene"], value: mode === "新建" ? "自定义实验区" : "共享场景" },
        { path: ["tasks"], value: mode === "新建" ? ["自定义搬运", "自定义巡查"] : ["共享任务"] },
      ],
    });
  } finally {
    page.close();
  }
});

// 契约：子任务使用多行纯文本，提交顶层路径，编辑文件选项不再提供子任务.json。
it("子任务记事本保留换行并提交标量路径", async () => {
  const requests: Request[] = [];
  const page = mountPage(
    originUrl,
    originFetch(requests, {
      "/api/datasets/dataset-14/editable-fields": () =>
        Response.json({
          ...information,
          fields: [{ path: ["subtask_notes"], label: "子任务", value: "", multiple: false }],
        }),
      "/api/navigation/fields/preview": () =>
        Response.json({ ...previewJob, type_name: "nav_fields_preview" }),
      "/api/navigation/previews/301": () =>
        Response.json({ ...originPreview, operation: "edit_dataset_fields" }),
    }),
  );
  try {
    fireEvent.click(
      await screen.findByRole(
        "button",
        { name: "编辑导航层字段" },
        { timeout: EDITOR_LOAD_TIMEOUT_MS },
      ),
    );
    const input = await screen.findByRole("textbox", { name: "子任务" });
    expect(input.tagName).toBe("TEXTAREA");
    expect(input.getAttribute("placeholder")).toBe("每行一个子任务，例如：抓取杯子");
    const notes = "抓取杯子\n放到桌上\n  保留缩进";
    fireEvent.change(input, { target: { value: notes } });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择编辑文件" }));
    expect(screen.queryByRole("option", { name: "子任务.json" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "预览字段改动" }));
    await waitFor(() => {
      expect(
        requests.some((r) => new URL(r.url).pathname === "/api/navigation/fields/preview"),
      ).toBe(true);
    });
    const post = requests.find((r) => new URL(r.url).pathname === "/api/navigation/fields/preview");
    expect(await post?.clone().json()).toMatchObject({
      changes: [{ document: "数据集信息.json", path: ["subtask_notes"], value: notes }],
    });
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
        "#dataset-field-editor",
      );
    } finally {
      page.close();
    }
  },
);
