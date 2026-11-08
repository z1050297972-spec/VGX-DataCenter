// M3-01/02 关键验收：真实路由和页面，替身只位于 HTTP 边界，不访问机器人或数据盘。
import { expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { mountPage, pageFetch } from "../scheduling/pageTestSupport";
import type { FetchImplementation } from "../api/client";
import type {
  Method,
  MethodInput,
  Purpose,
  PurposeInput,
  Robot,
  RobotInput,
} from "../api/collection";

const metadata = {
  status: "active" as const,
  reference_count: 0,
  created_by: { account_id: null, name: "系统", deleted: false },
  updated_by: { account_id: "7", name: "张三", deleted: true },
  created_at: "2026-11-08T10:00:00Z",
  updated_at: "2026-11-08T11:00:00Z",
};
const robot: Robot = {
  ...metadata,
  robot_id: 1,
  name: "一号机器人",
  robot_model: "R1",
  serial_number: null,
  macs: [],
  address: null,
  ssh_port: 22,
  ssh_user: null,
};
const method: Method = { ...metadata, id: 1, name: "主从臂遥操作", data_origin: "真机采集" };
const purpose: Purpose = { ...metadata, id: 1, name: "训练" };

// 身份及外壳接口沿用现有页面样本；本次接口保留可观察的请求和服务端快照。
function registryFetch(
  options: { referenced?: boolean; writes?: Request[] } = {},
): FetchImplementation {
  const references = options.referenced ? 2 : 0;
  let robots = [{ ...robot, reference_count: references }];
  const methods = [{ ...method, reference_count: references }];
  const purposes = [{ ...purpose, reference_count: references }];
  const fallback = pageFetch();
  const writes = options.writes ?? [];
  return async (request) => {
    const path = new URL(request.url).pathname;
    if (request.method !== "GET") writes.push(request.clone());
    if (path === "/api/robots/model-options") return Response.json({ items: ["R1", "R2"] });
    if (path === "/api/robots") {
      if (request.method === "POST") {
        const values = (await request.json()) as RobotInput;
        const created = { ...metadata, ...values, robot_id: 2 };
        robots = [...robots, created];
        return Response.json(created, { status: 201 });
      }
      return Response.json({ items: robots });
    }
    if (path === "/api/collection-vocabulary") return Response.json({ methods, purposes });
    if (path === "/api/collection-vocabulary/methods" && request.method === "POST") {
      const values = (await request.json()) as MethodInput;
      const created = { ...metadata, ...values, id: 2 };
      methods.push(created);
      return Response.json(created, { status: 201 });
    }
    if (path === "/api/collection-vocabulary/purposes" && request.method === "POST") {
      const values = (await request.json()) as PurposeInput;
      const created = { ...metadata, ...values, id: 2 };
      purposes.push(created);
      return Response.json(created, { status: 201 });
    }
    return fallback(request);
  };
}

// 契约：成员从主菜单进入机器人，新建支持自由型号、多网卡和默认 SSH 端口，成功刷新列表。
it("新建机器人后显示新行和历史修改人", async () => {
  const writes: Request[] = [];
  const page = mountPage("/", registryFetch({ writes }));
  try {
    fireEvent.click(await screen.findByRole("link", { name: "机器人" }));
    await screen.findByRole("row", { name: /一号机器人/ });
    expect(screen.getByText("张三（已删除）")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "新建机器人" }));
    const dialog = within(await screen.findByRole("dialog", { name: "新建机器人" }));
    fireEvent.change(dialog.getByLabelText("名称"), { target: { value: "二号机器人" } });
    fireEvent.change(dialog.getByLabelText("型号"), { target: { value: "新型号" } });
    fireEvent.click(dialog.getByRole("button", { name: "添加网卡" }));
    fireEvent.change(dialog.getByLabelText("MAC"), { target: { value: "AA-BB-CC-DD-EE-FF" } });
    fireEvent.click(dialog.getByRole("button", { name: "保存机器人" }));
    expect(await screen.findByRole("row", { name: /二号机器人.*新型号/ })).toBeTruthy();
    expect(await writes[0]?.json()).toEqual({
      name: "二号机器人",
      robot_model: "新型号",
      serial_number: null,
      macs: [{ interface: null, mac: "AA-BB-CC-DD-EE-FF" }],
      address: null,
      ssh_port: 22,
      ssh_user: null,
    });
  } finally {
    page.close();
  }
});

// 契约：两个词表均可新增；采集方式必须带用户选择的来源，用途只提交名称。
it.each([
  { tab: "methods", label: "采集方式", name: "新采集方式" },
  { tab: "purposes", label: "用途", name: "新用途" },
] as const)("新增 $label 后列表出现新项", async ({ tab, label, name }) => {
  const writes: Request[] = [];
  const page = mountPage(`/collection-vocabulary?tab=${tab}`, registryFetch({ writes }));
  try {
    fireEvent.click(await screen.findByRole("button", { name: `新增${label}` }));
    const dialog = within(await screen.findByRole("dialog", { name: `新增${label}` }));
    fireEvent.change(dialog.getByLabelText("名称"), { target: { value: name } });
    if (tab === "methods") {
      fireEvent.mouseDown(dialog.getByRole("combobox", { name: "对应数据来源" }));
      fireEvent.click(
        screen.getByText("UMI 采集", { selector: ".ant-select-item-option-content" }),
      );
    }
    fireEvent.click(dialog.getByRole("button", { name: `保存${label}` }));
    expect(await screen.findByRole("row", { name: new RegExp(name) })).toBeTruthy();
    expect(await writes[0]?.json()).toEqual(
      tab === "methods" ? { name, data_origin: "UMI 采集" } : { name },
    );
  } finally {
    page.close();
  }
});

// 契约：机器人及两种词表的被引用项都禁删，并解释只能停用。
it.each([
  { path: "/robots", name: "一号机器人" },
  { path: "/collection-vocabulary?tab=methods", name: "主从臂遥操作" },
  { path: "/collection-vocabulary?tab=purposes", name: "训练" },
])("$path 被引用项不可删除", async ({ path, name }) => {
  const page = mountPage(path, registryFetch({ referenced: true }));
  try {
    const row = within(await screen.findByRole("row", { name: new RegExp(name) }));
    const button = row.getByRole("button", { name: "删除" });
    expect(button).toHaveProperty("disabled", true);
    fireEvent.mouseOver(button.parentElement ?? button);
    expect(await screen.findByRole("tooltip")).toHaveProperty(
      "textContent",
      "已被数据集引用，只能停用",
    );
  } finally {
    page.close();
  }
});

// 契约：主菜单进入采集词表，页签反映 URL；从用途直达也能显示相同内容。
it("词表页签切换写入 URL，刷新可保留用途页", async () => {
  const page = mountPage("/robots", registryFetch());
  try {
    fireEvent.click(await screen.findByRole("link", { name: "采集词表" }));
    fireEvent.click(await screen.findByRole("tab", { name: "用途" }));
    await waitFor(() => {
      expect(page.router.state.location.search).toEqual({ tab: "purposes" });
    });
    expect(await screen.findByRole("row", { name: /训练/ })).toBeTruthy();
  } finally {
    page.close();
  }
  const reopened = mountPage("/collection-vocabulary?tab=purposes", registryFetch());
  try {
    expect(await screen.findByRole("tab", { name: "用途" })).toHaveProperty("ariaSelected", "true");
    expect(await screen.findByRole("row", { name: /训练/ })).toBeTruthy();
  } finally {
    reopened.close();
  }
});

// 契约：编辑保持平台编号，PUT 只提交可编辑字段，成功后显示修改后的登记。
it("编辑机器人提交完整可编辑字段并刷新原行", async () => {
  let current = robot;
  let submitted: unknown;
  const fallback = registryFetch();
  const page = mountPage("/robots", async (request) => {
    const path = new URL(request.url).pathname;
    if (request.method === "PUT" && path === "/api/robots/1") {
      const values = (await request.json()) as RobotInput;
      submitted = values;
      current = { ...robot, ...values };
      return Response.json(current);
    }
    if (path === "/api/robots") return Response.json({ items: [current] });
    return fallback(request);
  });
  try {
    const row = within(await screen.findByRole("row", { name: /一号机器人/ }));
    fireEvent.click(row.getByRole("button", { name: "编辑" }));
    const dialog = within(await screen.findByRole("dialog", { name: "编辑机器人" }));
    fireEvent.change(dialog.getByLabelText("名称"), { target: { value: "改名后的机器人" } });
    fireEvent.click(dialog.getByRole("button", { name: "保存机器人" }));
    expect(await screen.findByRole("row", { name: /改名后的机器人/ })).toBeTruthy();
    expect(submitted).toEqual({
      name: "改名后的机器人",
      robot_model: "R1",
      serial_number: null,
      macs: [],
      address: null,
      ssh_port: 22,
      ssh_user: null,
    });
  } finally {
    page.close();
  }
});
