// 转换关系验收通过真实数据中心页面与 HTTP 边界，所有关系均为内存样本。
import { expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { originFetch, originPreview, originUrl, previewJob, writtenJob } from "./originTestSupport";
import { datasets, detail } from "./testSupport";

const manualInput = {
  record_id: 7,
  dataset_id: "dataset-20",
  name: "原始采集",
  entry_path: "按任务/原始采集",
  note: "人工登记说明",
  removable: true,
};
const lineage = {
  upstream: [
    manualInput,
    {
      ...manualInput,
      dataset_id: "dataset-21",
      name: "第二份输入",
      entry_path: "按任务/第二份输入",
    },
    {
      ...manualInput,
      record_id: 8,
      dataset_id: "dataset-99",
      name: null,
      entry_path: null,
      note: "工具生成",
      removable: false,
    },
  ],
  downstream: [
    {
      record_id: 3,
      dataset_id: "dataset-30",
      name: "转换产物",
      entry_path: "按任务/转换产物",
      note: "转换说明",
    },
  ],
};
const emptyLineage = { upstream: [], downstream: [] };
const preview = {
  ...originPreview,
  parameters: { dataset_id: "dataset-14", action: "add" },
  report: {
    ...originPreview.report,
    listed_changes: [
      {
        file: "按任务/libero_10/来源.json",
        json_path: "lineage",
        before: "[]",
        after: "人工转换记录",
      },
    ],
  },
};

// 契约：三种布局均展示所有记录的上下游，缺失索引显示编号，人工多输入记录只提供一次整条删除。
it.each(["A", "B", "C"])("布局 %s 展示转换关系并可跳转", async (layout) => {
  const page = mountPage(
    originUrl,
    originFetch([], {
      "/api/datasets/layout": () => Response.json({ layout, updated_at: null }),
      "/api/datasets/detail": () => Response.json({ ...detail, lineage }),
    }),
  );
  try {
    const section = within(await screen.findByRole("region", { name: "转换关系" }));
    expect(section.getByText("人工登记说明")).toBeTruthy();
    expect(section.getByText("工具生成")).toBeTruthy();
    expect(section.getByText("dataset-99（索引中不存在）")).toBeTruthy();
    expect(section.getAllByRole("button", { name: /删除转换记录/ })).toHaveLength(1);
    expect(section.queryByRole("button", { name: "删除转换记录 8" })).toBeNull();
    expect(section.getByRole("link", { name: "转换产物" })).toBeTruthy();
    fireEvent.click(section.getByRole("link", { name: "原始采集" }));
    await waitFor(() => {
      expect(page.router.state.location.search.selected).toBe("按任务/原始采集");
    });
  } finally {
    page.close();
  }
});

// 契约：跨页多选排除自己，修改草稿使旧预览失效，确认只提交审阅的预览编号，写入终态刷新关系。
it("登记多个来源先预览再确认并刷新详情", async () => {
  const requests: Request[] = [];
  let applied = false;
  const page = mountPage(
    originUrl,
    originFetch(requests, {
      "/api/datasets/detail": () =>
        Response.json({ ...detail, lineage: applied ? lineage : emptyLineage }),
      "/api/datasets": (request) =>
        Response.json(
          new URL(request.url).searchParams.get("offset") === "20"
            ? {
                ...datasets,
                offset: 20,
                total: 21,
                items: [{ ...datasets.items[1], dataset_id: "dataset-21", name: "second" }],
              }
            : { ...datasets, total: 21 },
        ),
      "/api/navigation/lineage/preview": () =>
        Response.json({ ...previewJob, type_name: "nav_lineage_preview" }),
      "/api/navigation/previews/301": () => Response.json(preview),
      "/api/jobs/302": () => {
        applied = true;
        return Response.json(writtenJob);
      },
    }),
  );
  try {
    fireEvent.click(await screen.findByRole("button", { name: "登记转换来源" }));
    // antd 测试环境的 useId 固定为 test-id，与已有下拉框冲突；布局 A 只有此对话框。
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("button", { name: "生成转换关系预览" }).hasAttribute("disabled")).toBe(
      true,
    );
    const select = await dialog.findByRole("combobox", { name: "来源数据集" });
    await waitFor(() => {
      expect(select.hasAttribute("disabled")).toBe(false);
    });
    fireEvent.mouseDown(select);
    expect(await screen.findByRole("option", { name: "other（dataset-20）" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /libero_10/ })).toBeNull();
    fireEvent.click(screen.getByRole("option", { name: "other（dataset-20）" }));
    fireEvent.keyDown(select, { key: "Escape" });
    fireEvent.click(dialog.getByRole("button", { name: "下一页来源" }));
    await waitFor(() => {
      expect(select.hasAttribute("disabled")).toBe(false);
    });
    fireEvent.mouseDown(select);
    fireEvent.click(await screen.findByRole("option", { name: "second（dataset-21）" }));
    fireEvent.keyDown(select, { key: "Escape" });
    fireEvent.change(dialog.getByRole("textbox", { name: "转换说明" }), {
      target: { value: "两次采集合并" },
    });
    fireEvent.click(dialog.getByRole("button", { name: "生成转换关系预览" }));
    await dialog.findByRole("button", { name: "确认字段写入" });
    expect(dialog.getByText("按任务/libero_10/来源.json · lineage")).toBeTruthy();
    fireEvent.change(dialog.getByRole("textbox", { name: "转换说明" }), {
      target: { value: "修正说明" },
    });
    expect(dialog.queryByRole("button", { name: "确认字段写入" })).toBeNull();
    fireEvent.click(dialog.getByRole("button", { name: "生成转换关系预览" }));
    const confirm = await dialog.findByRole("button", { name: "确认字段写入" });
    const posts = requests.filter((request) => request.method === "POST");
    expect(posts).toHaveLength(2);
    expect(
      posts.every((request) => new URL(request.url).pathname === "/api/navigation/lineage/preview"),
    ).toBe(true);
    expect(await posts[1]?.clone().json()).toEqual({
      dataset_id: "dataset-14",
      action: "add",
      input_dataset_ids: ["dataset-20", "dataset-21"],
      note: "修正说明",
    });
    fireEvent.click(confirm);
    await screen.findByRole("region", { name: "登记转换来源 #302" });
    await screen.findByRole("link", { name: "原始采集" });
    const apply = requests.find(
      (request) => request.method === "POST" && new URL(request.url).pathname === "/api/jobs",
    );
    expect(await apply?.clone().json()).toEqual({
      type_name: "nav_write_apply",
      parameters: { preview_job_id: 301 },
    });
    expect(confirm.hasAttribute("disabled")).toBe(true);
  } finally {
    page.close();
  }
});

// 契约：删除提交记录编号而非单个输入，确认前不执行，写入完成后该记录的全部输入消失。
it("删除整条人工记录经过预览确认", async () => {
  const requests: Request[] = [];
  let applied = false;
  const page = mountPage(
    originUrl,
    originFetch(requests, {
      "/api/datasets/detail": () =>
        Response.json({
          ...detail,
          lineage: applied
            ? { ...lineage, upstream: lineage.upstream.filter((item) => item.record_id !== 7) }
            : lineage,
        }),
      "/api/navigation/lineage/preview": () =>
        Response.json({ ...previewJob, type_name: "nav_lineage_preview" }),
      "/api/navigation/previews/301": () => Response.json(preview),
      "/api/jobs/302": () => {
        applied = true;
        return Response.json(writtenJob);
      },
    }),
  );
  try {
    fireEvent.click(await screen.findByRole("button", { name: "删除转换记录 7" }));
    // antd 测试环境的 useId 固定为 test-id，与已有下拉框冲突；布局 A 只有此对话框。
    const dialog = within(await screen.findByRole("dialog"));
    fireEvent.click(dialog.getByRole("button", { name: "生成转换关系预览" }));
    const confirm = await dialog.findByRole("button", { name: "确认字段写入" });
    const posts = requests.filter((request) => request.method === "POST");
    expect(posts).toHaveLength(1);
    expect(await posts[0]?.clone().json()).toEqual({
      dataset_id: "dataset-14",
      action: "remove",
      record_id: 7,
      input_dataset_ids: [],
    });
    fireEvent.click(confirm);
    await screen.findByRole("region", { name: "删除转换记录 #302" });
    await waitFor(() => {
      expect(screen.queryByRole("link", { name: "原始采集" })).toBeNull();
      expect(screen.queryByRole("link", { name: "第二份输入" })).toBeNull();
    });
    expect(screen.getByText("工具生成")).toBeTruthy();
  } finally {
    page.close();
  }
});

// 契约：恢复失败时不能创建预览，禁用原因明确可见。
it("导航恢复失败禁止转换关系写入", async () => {
  const requests: Request[] = [];
  const page = mountPage(
    originUrl,
    originFetch(requests, {
      "/api/datasets/detail": () => Response.json({ ...detail, lineage }),
      "/api/navigation/recovery-block": () => Response.json({ blocked: true }),
    }),
  );
  try {
    fireEvent.click(await screen.findByRole("button", { name: "删除转换记录 7" }));
    // antd 测试环境的 useId 固定为 test-id，与已有下拉框冲突；布局 A 只有此对话框。
    const dialog = within(await screen.findByRole("dialog"));
    expect(await dialog.findByText("导航层恢复失败，请管理员处理后再提交")).toBeTruthy();
    expect(screen.getByRole("button", { name: "生成转换关系预览" }).hasAttribute("disabled")).toBe(
      true,
    );
    expect(requests.filter((request) => request.method === "POST")).toHaveLength(0);
  } finally {
    page.close();
  }
});

// 契约：预览被服务端拒绝时展示完整诊断，不提供确认入口，也不自动重试写请求。
it("转换关系预览拒绝后显示诊断且不能确认", async () => {
  const requests: Request[] = [];
  const page = mountPage(
    originUrl,
    originFetch(requests, {
      "/api/datasets/detail": () => Response.json({ ...detail, lineage }),
      "/api/navigation/lineage/preview": () =>
        Response.json(
          {
            type: "about:blank",
            title: "Unprocessable Entity",
            status: 422,
            category: "input",
            detail: "记录不可删除",
            error_id: "00000000000040008000000000000000",
            diagnostics: [
              {
                level: "error",
                category: "input",
                stage: "预览",
                source: "平台",
                rule: "LINEAGE_NOT_MANUAL",
                objects: [{ key: "record_id", value: "7" }],
                actual: "记录由 worker 写入",
                expected: "人工补录记录",
                consequence: "未生成预览",
                next_step: "重新读取详情",
                error_chain: [],
              },
            ],
          },
          { status: 422, headers: { "content-type": "application/problem+json" } },
        ),
    }),
  );
  try {
    fireEvent.click(await screen.findByRole("button", { name: "删除转换记录 7" }));
    // antd 测试环境中对话框名称可能与下拉框 ID 冲突，布局 A 只打开一个对话框。
    const dialog = within(await screen.findByRole("dialog"));
    fireEvent.click(dialog.getByRole("button", { name: "生成转换关系预览" }));
    expect(await dialog.findByText(/记录由 worker 写入/)).toBeTruthy();
    expect(dialog.getByText(/期望：人工补录记录/)).toBeTruthy();
    expect(dialog.getByText(/未生成预览/)).toBeTruthy();
    expect(dialog.getByText(/重新读取详情/)).toBeTruthy();
    expect(dialog.queryByRole("button", { name: "确认字段写入" })).toBeNull();
    expect(requests.filter((request) => request.method === "POST")).toHaveLength(1);
  } finally {
    page.close();
  }
});
