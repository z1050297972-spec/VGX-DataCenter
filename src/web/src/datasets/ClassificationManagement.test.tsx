// M1.5-16 管理入口的关键验收；通过真实页面和 HTTP 边界，不替换内部组件。
import { expect, it } from "vitest";
import { fireEvent, screen, within, waitFor } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { originFetch, originPreview, previewJob, writtenJob } from "./originTestSupport";
import { filters } from "./testSupport";

// 契约：成员可以管理分类；内置零计数项保留且不能删除，未标注不是可删除的值。
it("零计数场景禁删并显示内置词表说明", async () => {
  const requests: Request[] = [];
  const page = mountPage("/datasets", originFetch(requests));
  try {
    fireEvent.click(await screen.findByRole("button", { name: "管理场景/任务" }));
    const dialog = within(await screen.findByRole("dialog", { name: "管理场景/任务" }));
    const row = within(await dialog.findByRole("row", { name: /家居-厨房/ }));
    expect(row.getByText("kitchen")).toBeTruthy();
    expect(row.getByText("0")).toBeTruthy();
    expect(row.getByText("内置词表项，没有数据集在用")).toBeTruthy();
    expect(row.getByRole("button", { name: /删除/ }).hasAttribute("disabled")).toBe(true);
    expect(dialog.queryByRole("row", { name: /未标注/ })).toBeNull();
    expect(requests.filter((request) => request.method === "POST")).toHaveLength(0);
  } finally {
    page.close();
  }
});

// 契约：场景/任务删除只提交预览，审阅受影响数据集与未标注结果后显式确认，完成刷新候选。
it.each([
  { kind: "scene", tab: "场景", value: "实验室" },
  { kind: "tasks", tab: "任务", value: "洗碗" },
] as const)("删除 $tab 先预览再确认并刷新候选", async ({ kind, tab, value }) => {
  const requests: Request[] = [];
  let applied = false;
  const page = mountPage(
    "/datasets",
    originFetch(requests, {
      "/api/datasets/filters": () =>
        Response.json({
          ...filters,
          [kind === "scene" ? "scenes" : "tasks"]: applied
            ? []
            : [{ value, label: value, count: 2 }],
        }),
      "/api/navigation/classification/remove/preview": () =>
        Response.json({ ...previewJob, type_name: "nav_classification_remove_preview" }),
      "/api/navigation/previews/301": () =>
        Response.json({
          ...originPreview,
          parameters: { kind, value },
          dataset_ids: ["dataset-14", "dataset-15"],
          report: {
            ...originPreview.report,
            listed_changes: [
              {
                file: "按任务/libero_10/数据集信息.json",
                json_path: kind,
                before: JSON.stringify([value]),
                after: "[]",
              },
            ],
          },
        }),
      "/api/jobs/302": () => {
        applied = true;
        return Response.json(writtenJob);
      },
    }),
  );
  try {
    fireEvent.click(await screen.findByRole("button", { name: "管理场景/任务" }));
    const dialog = within(await screen.findByRole("dialog", { name: "管理场景/任务" }));
    fireEvent.click(dialog.getByRole("tab", { name: tab }));
    fireEvent.click(await dialog.findByRole("button", { name: `删除 ${value}` }));
    const confirm = await dialog.findByRole("button", { name: "确认字段写入" });
    expect(dialog.getByText(/dataset-14.*dataset-15/)).toBeTruthy();
    expect(dialog.getByText("删除后变成未标注")).toBeTruthy();
    const posts = requests.filter((request) => request.method === "POST");
    expect(posts).toHaveLength(1);
    expect(posts.map((request) => new URL(request.url).pathname)).toEqual([
      "/api/navigation/classification/remove/preview",
    ]);
    expect(await posts[0]?.clone().json()).toEqual({ kind, value });
    fireEvent.click(confirm);
    await screen.findByRole("region", { name: "删除场景/任务值 #302" });
    await waitFor(() => {
      expect(dialog.queryByRole("button", { name: `删除 ${value}` })).toBeNull();
    });
    const apply = requests.find(
      (request) => request.method === "POST" && new URL(request.url).pathname === "/api/jobs",
    );
    expect(await apply?.clone().json()).toEqual({
      type_name: "nav_write_apply",
      parameters: { preview_job_id: 301 },
    });
  } finally {
    page.close();
  }
});
