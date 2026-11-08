// M3-04 页面契约：使用真实 Router 和 Query，仅替换 HTTP 边界，不访问真实导航层。
import { expect, it } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import { creationFetch } from "./creationTestSupport";

function transport(requests: Request[]) {
  return creationFetch(requests, {
    "/api/robots": () => Response.json({ items: [] }),
    "/api/collection-vocabulary": () =>
      Response.json({
        methods: [{ id: 1, name: "VR 遥操作", data_origin: "真机采集", status: "active" }],
        purposes: [],
      }),
  });
}
async function choose(label: string, option: string) {
  const input = await screen.findByRole("combobox", { name: label });
  await waitFor(() => {
    expect(input.hasAttribute("disabled")).toBe(false);
  });
  fireEvent.mouseDown(input);
  fireEvent.click(await screen.findByRole("option", { name: option }));
}
function previewRequests(requests: Request[]) {
  return requests.filter(
    (request) =>
      request.method === "POST" &&
      new URL(request.url).pathname === "/api/datasets/creation-previews",
  );
}

// 验证入口、默认计划中、来源带出及无链接创建沿用预览→确认；修改后必须重新预览。
it("从工具栏新建计划中的采集任务，无链接预览后确认", async () => {
  const requests: Request[] = [];
  const page = mountPage("/datasets", transport(requests));
  try {
    fireEvent.click(await screen.findByRole("button", { name: "新建采集任务" }));
    await screen.findByRole("heading", { name: "新建采集任务" });
    expect(page.router.state.location.search).toMatchObject({ mode: "collection" });
    fireEvent.change(await screen.findByLabelText("数据集名"), { target: { value: "计划采集" } });
    expect(screen.getByText("计划中", { selector: ".ant-select-content" })).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "第 2 项：地址" }), {
      target: { value: "/fake/collection/planned" },
    });
    await choose("采集方式", "VR 遥操作（真机采集）");
    expect(screen.getByText("真机采集", { selector: ".ant-select-content" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
    await screen.findByRole("heading", { name: "预览差异" });
    expect(await previewRequests(requests)[0]?.clone().json()).toMatchObject({
      link: null,
      collection: { status: "planned", method_id: 1, purpose_id: null, robot_ids: [] },
      data_origin: "真机采集",
      information: { fields: [{ number: 2, value_markdown: "/fake/collection/planned" }] },
    });
    expect(page.router.state.location.search).toMatchObject({
      mode: "collection",
      preview_job_id: "101",
    });
    fireEvent.click(screen.getByRole("button", { name: "修改参数" }));
    expect(screen.queryByRole("button", { name: "确认写入" })).toBeNull();
    expect(screen.getByText("计划中", { selector: ".ant-select-content" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
    await screen.findByRole("heading", { name: "预览差异" });
    fireEvent.click(screen.getByRole("button", { name: "确认写入" }));
    expect(await screen.findByRole("region", { name: "新增数据集 #102" })).toBeTruthy();
  } finally {
    page.close();
  }
});

// 验证地址必填包括全空白，并且来源带出后仍允许手动修改。
it("采集地址不能省略或仅为空白，带出的来源可改", async () => {
  const requests: Request[] = [];
  const page = mountPage("/datasets/new?mode=collection", transport(requests));
  try {
    fireEvent.change(await screen.findByLabelText("数据集名"), { target: { value: "计划采集" } });
    await choose("采集方式", "VR 遥操作（真机采集）");
    const address = screen.getByRole("textbox", { name: "第 2 项：地址" });
    expect(address.hasAttribute("required")).toBe(true);
    for (const value of ["", "   "]) {
      fireEvent.change(address, { target: { value } });
      expect(screen.getByRole("button", { name: "生成预览" }).hasAttribute("disabled")).toBe(true);
    }
    expect(previewRequests(requests)).toHaveLength(0);
    fireEvent.change(address, { target: { value: "/fake/collection/planned" } });
    await choose("数据来源", "仿真生成");
    fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
    await screen.findByRole("heading", { name: "预览差异" });
    expect(await previewRequests(requests)[0]?.clone().json()).toMatchObject({
      data_origin: "仿真生成",
      collection: { method_id: 1 },
    });
  } finally {
    page.close();
  }
});

// 验证切换出计划中后恢复首链接必填，半填链接也不能提交。
it.each(["采集中", "已完成", "无采集信息"])("%s 不能省略第一条链接", async (status) => {
  const requests: Request[] = [];
  const page = mountPage("/datasets/new?mode=collection", transport(requests));
  try {
    fireEvent.change(await screen.findByLabelText("数据集名"), { target: { value: "采集" } });
    fireEvent.change(screen.getByRole("textbox", { name: "第 2 项：地址" }), {
      target: { value: "/fake/collection/planned" },
    });
    await choose("数据来源", "真机采集");
    await choose("采集状态", status);
    expect(screen.getByLabelText("链接名").hasAttribute("required")).toBe(true);
    expect(screen.getByLabelText("目标路径").hasAttribute("required")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
    fireEvent.change(screen.getByLabelText("链接名"), { target: { value: "第一批" } });
    fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
    expect(previewRequests(requests)).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("目标路径"), {
      target: { value: "/fake/collection/batch" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成预览" }));
    await screen.findByRole("heading", { name: "预览差异" });
    expect(await previewRequests(requests)[0]?.clone().json()).toMatchObject({
      link: { name: "第一批", target_path: "/fake/collection/batch" },
    });
  } finally {
    page.close();
  }
});
