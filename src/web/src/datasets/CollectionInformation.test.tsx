// M3-03 关键页面契约：只替换 HTTP 边界，真实 Router、Query 和字段预览链共同验证。
import { expect, it } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { mountPage } from "../scheduling/pageTestSupport";
import type { CollectionValue, CollectionDetail } from "../api/collection";
import type { EditablePage } from "../api/fieldEditing";
import type { Method, Purpose, Robot } from "../api/collection";
import { detail, filters } from "./testSupport";
import { originFetch, originUrl, type OriginHandlers } from "./originTestSupport";

const metadata = {
  status: "active" as const,
  reference_count: 1,
  created_by: { account_id: null, name: "系统", deleted: false },
  updated_by: { account_id: null, name: "系统", deleted: false },
  created_at: "2026-11-08T10:00:00Z",
  updated_at: "2026-11-08T10:00:00Z",
};
const method: Method = { ...metadata, id: 1, name: "VR 遥操作", data_origin: "真机采集" };
const purpose: Purpose = { ...metadata, id: 1, name: "训练" };
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
const original: CollectionValue = {
  status: "planned",
  method_id: 2,
  purpose_id: 2,
  robot_ids: [2],
};
const collection: CollectionDetail = {
  status: "planned",
  method: { id: 2, name: "旧方式", data_origin: "UMI 采集", status: "retired" },
  purpose: { id: 2, name: "旧用途", status: "retired" },
  robots: [
    { robot_id: 2, name: "旧机器人", status: "retired" },
    { robot_id: 99, name: null, status: "missing" },
  ],
};
function handlers(value: CollectionValue | null = original, origin = "未知"): OriginHandlers {
  const information: EditablePage = {
    dataset_id: "dataset-14",
    entry_path: "按任务/libero_10",
    document: "数据集信息.json",
    sha256: "a".repeat(64),
    offset: 0,
    limit: 20,
    total: 1,
    original_robot_types: [],
    original_fps: [],
    fields: [
      { path: ["collection"], label: "采集信息", multiple: false, value },
      { path: ["data_origin"], label: "数据来源", multiple: false, value: origin },
    ],
  };
  return {
    "/api/datasets/detail": () =>
      Response.json({ ...detail, collection: value ? collection : null }),
    "/api/datasets/dataset-14/editable-fields": () => Response.json(information),
    "/api/collection-vocabulary": () =>
      Response.json({
        methods: [
          method,
          { ...method, id: 2, name: "旧方式", status: "retired", data_origin: "UMI 采集" },
          { ...method, id: 3, name: "不可选方式", status: "retired" },
        ],
        purposes: [
          purpose,
          { ...purpose, id: 2, name: "旧用途", status: "retired" },
          { ...purpose, id: 3, name: "不可选用途", status: "retired" },
        ],
      }),
    "/api/robots": () =>
      Response.json({
        items: [
          robot,
          { ...robot, robot_id: 2, name: "旧机器人", status: "retired" },
          { ...robot, robot_id: 3, name: "不可选机器人", status: "retired" },
        ],
      }),
  };
}
async function choose(label: string, option: string) {
  // 数据来源在筛选栏和编辑区各有一个；编辑动作必须限定在详情内。
  const scope = label.startsWith("筛选")
    ? screen
    : within(screen.getByRole("region", { name: "数据集详情" }));
  const input = await scope.findByRole("combobox", { name: label });
  await waitFor(() => {
    expect(input.hasAttribute("disabled")).toBe(false);
  });
  fireEvent.mouseDown(input);
  fireEvent.click(await screen.findByRole("option", { name: option }));
}
async function preview(requests: Request[]) {
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
  if (!request) throw new Error("预览请求缺失");
  const payload: unknown = await request.clone().json();
  return payload;
}

// 契约：选择使用中的方式只补齐未知或空来源；已填写来源不覆盖，原停用引用仍随草稿保留。
it.each(["未知", "", "开源下载"])("采集方式按当前来源 %s 生成同一份字段预览", async (origin) => {
  const requests: Request[] = [];
  const page = mountPage(originUrl, originFetch(requests, handlers(original, origin)));
  try {
    fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
    await choose("采集方式", "VR 遥操作（真机采集）");
    const changes = [
      {
        document: "数据集信息.json",
        expected_sha256: "a".repeat(64),
        path: ["collection"],
        value: { ...original, method_id: 1 },
      },
    ];
    expect(await preview(requests)).toEqual({
      dataset_id: "dataset-14",
      changes:
        origin === "开源下载"
          ? changes
          : [
              ...changes,
              {
                document: "数据集信息.json",
                expected_sha256: "a".repeat(64),
                path: ["data_origin"],
                value: "真机采集",
              },
            ],
    });
  } finally {
    page.close();
  }
});

// 契约：三个候选只包含使用中和原来引用的停用项，机器人新增多选保序且旧引用保留。
it("编辑保留原停用引用且不能新选其他停用项", async () => {
  const requests: Request[] = [];
  const page = mountPage(originUrl, originFetch(requests, handlers()));
  try {
    fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
    for (const [label, retained, excluded] of [
      ["采集方式", "旧方式（UMI 采集）（停用）", "不可选方式（真机采集）（停用）"],
      ["用途", "旧用途（停用）", "不可选用途（停用）"],
      ["机器人", "旧机器人（停用）", "不可选机器人（停用）"],
    ] as const) {
      // 数据来源在筛选栏和编辑区各有一个；编辑动作必须限定在详情内。
      const scope = label.startsWith("筛选")
        ? screen
        : within(screen.getByRole("region", { name: "数据集详情" }));
      const input = await scope.findByRole("combobox", { name: label });
      await waitFor(() => {
        expect(input.hasAttribute("disabled")).toBe(false);
      });
      fireEvent.mouseDown(input);
      expect(await screen.findByRole("option", { name: retained })).toBeTruthy();
      expect(screen.queryByRole("option", { name: excluded })).toBeNull();
      fireEvent.keyDown(screen.getByRole("combobox", { name: label }), { key: "Escape" });
    }
    await choose("机器人", "一号机器人");
    expect(await preview(requests)).toEqual({
      dataset_id: "dataset-14",
      changes: [
        {
          document: "数据集信息.json",
          expected_sha256: "a".repeat(64),
          path: ["collection"],
          value: { ...original, robot_ids: [2, 1] },
        },
      ],
    });
  } finally {
    page.close();
  }
});

// 契约：清除已有采集信息必须提交 null；不能被草稿回退逻辑重新显示原值。
it("无采集信息以 null 提交并隐藏采集子字段", async () => {
  const requests: Request[] = [];
  const page = mountPage(originUrl, originFetch(requests, handlers()));
  try {
    fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
    await choose("采集状态", "无采集信息");
    expect(screen.queryByRole("combobox", { name: "采集方式" })).toBeNull();
    expect(await preview(requests)).toEqual({
      dataset_id: "dataset-14",
      changes: [
        {
          document: "数据集信息.json",
          expected_sha256: "a".repeat(64),
          path: ["collection"],
          value: null,
        },
      ],
    });
  } finally {
    page.close();
  }
});

// 契约：没有 collection 时可新建；带出的来源能手动改回，预览不残留来源修改。
it("补充采集信息后允许改回自动带出的来源", async () => {
  const requests: Request[] = [];
  const page = mountPage(originUrl, originFetch(requests, handlers(null)));
  try {
    expect(await screen.findByText("无（不是平台采集的数据集）")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    await choose("采集状态", "采集中");
    await choose("采集方式", "VR 遥操作（真机采集）");
    await choose("数据来源", "未知");
    expect(await preview(requests)).toEqual({
      dataset_id: "dataset-14",
      changes: [
        {
          document: "数据集信息.json",
          expected_sha256: "a".repeat(64),
          path: ["collection"],
          value: { status: "collecting", method_id: 1, purpose_id: null, robot_ids: [] },
        },
      ],
    });
  } finally {
    page.close();
  }
});

// 契约：详情显示数据库名称、方式来源和停用状态；未知机器人保留编号，链接到登记页。
it("详情展示采集信息和缺失引用", async () => {
  const page = mountPage(originUrl, originFetch([], handlers()));
  try {
    const section = within(await screen.findByRole("region", { name: "采集信息" }));
    expect(section.getByText("计划中")).toBeTruthy();
    expect(section.getByText("旧方式（停用）（UMI 采集）")).toBeTruthy();
    expect(section.getByText("旧用途（停用）")).toBeTruthy();
    expect(section.getByRole("link", { name: "旧机器人（停用）" }).getAttribute("href")).toBe(
      "/robots",
    );
    expect(section.getByRole("link", { name: "未知编号 99" }).getAttribute("href")).toBe("/robots");
  } finally {
    page.close();
  }
});

// 契约：三种布局共用四个筛选；真实 URL 的数字编号转十进制文本，改选后清分页并传到列表和树。
it.each(["A", "B", "C"])("布局 %s 恢复并提交四个采集筛选", async (layout) => {
  const requests: Request[] = [];
  const unlabeled = { value: "unlabeled", label: "无采集信息", count: 1 };
  const page = mountPage(
    "/datasets?collection_status=planned&collection_method=1&collection_purpose=2&collection_robot=99&offset=20",
    originFetch(requests, {
      "/api/datasets/layout": () => Response.json({ layout, updated_at: null }),
      "/api/datasets/filters": () =>
        Response.json({
          ...filters,
          collection_statuses: [{ value: "planned", label: "计划中", count: 1 }, unlabeled],
          collection_methods: [{ value: "1", label: "VR 遥操作", count: 1 }, unlabeled],
          collection_purposes: [{ value: "2", label: "旧用途", count: 1 }, unlabeled],
          collection_robots: [{ value: "99", label: "未知编号 99", count: 1 }, unlabeled],
        }),
    }),
  );
  try {
    for (const name of ["采集状态", "采集方式", "用途", "机器人"])
      expect(await screen.findByRole("combobox", { name: `筛选${name}` })).toBeTruthy();
    expect(screen.getByText("未知编号 99（1）")).toBeTruthy();
    await choose("筛选采集状态", "无采集信息（1）");
    await waitFor(() => {
      expect(page.router.state.location.search).toMatchObject({
        collection_status: "unlabeled",
        collection_method: "1",
        collection_purpose: "2",
        collection_robot: "99",
      });
      expect(page.router.state.location.search.offset).toBeUndefined();
      for (const path of ["/api/datasets", "/api/datasets/trees"])
        expect(
          requests.some((request) => {
            const url = new URL(request.url);
            return (
              url.pathname === path &&
              url.searchParams.get("collection_status") === "unlabeled" &&
              url.searchParams.get("collection_method") === "1" &&
              url.searchParams.get("collection_purpose") === "2" &&
              url.searchParams.get("collection_robot") === "99"
            );
          }),
        ).toBe(true);
    });
  } finally {
    page.close();
  }
});
