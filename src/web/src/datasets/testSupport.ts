// M1-04 页面测试样本：按生成类型手写两个有区别的数据集，不读取真实导航层。
import type { components } from "../api/schema";
import type { SceneArrays } from "../api/sceneTypes";
import type { FetchImplementation } from "../api/client";
import { pageFetch } from "../scheduling/pageTestSupport";

type Schema = SceneArrays<components["schemas"]>;
export const size: Schema["DatasetSize"] = {
  display_bytes: 2048,
  display_source: "measured",
  recorded_on: "2026-10-12",
  recorded_size_bytes: null,
  size_bytes: 2048,
  size_checked_at: "2026-11-04T12:00:00Z",
};
export const taskEntry: Schema["EntrySummary"] = {
  dataset_id: "dataset-14",
  entry_path: "按任务/libero_10",
  name: "libero_10",
  view: "task",
  format: null,
  version: null,
  size,
};
export const formatEntry: Schema["EntrySummary"] = {
  ...taskEntry,
  entry_path: "按格式/lerobot/2.1/libero_10",
  view: "format",
  format: "lerobot",
  version: "2.1",
};
export const datasets: Schema["DatasetListResponse"] = {
  items: [
    {
      dataset_id: "dataset-14",
      name: "libero_10",
      canonical_entry_path: taskEntry.entry_path,
      entries: [formatEntry, taskEntry],
      robot_types: ["franka"],
      robot_model_ids: [],
      fps: [20],
      data_origin: "unknown",
      scene: ["tabletop", "kitchen", "自定义场景"],
      tasks: ["pick_place", "tidy"],
      robot_model: "Franka",
      indexed_at: "2026-10-29T12:00:00Z",
      size,
    },
    {
      dataset_id: "dataset-20",
      name: "other",
      canonical_entry_path: "按任务/other",
      entries: [
        { ...taskEntry, dataset_id: "dataset-20", entry_path: "按任务/other", name: "other" },
      ],
      robot_types: ["g2a"],
      robot_model_ids: [],
      fps: [30],
      data_origin: "unknown",
      scene: [],
      tasks: [],
      robot_model: null,
      indexed_at: "2026-10-29T12:00:00Z",
      size,
    },
  ],
  total: 2,
  offset: 0,
  limit: 20,
  indexed_at: "2026-10-29T12:00:00Z",
};
const treeSize: Schema["TreeSize"] = {
  known_bytes: 2048,
  total_bytes: 2048,
  measured_entry_count: 1,
  recorded_entry_count: 0,
  unknown_entry_count: 0,
  oldest_size_checked_at: "2026-11-04T12:00:00Z",
  newest_size_checked_at: "2026-11-04T12:00:00Z",
};
export const trees: Schema["DatasetTreesResponse"] = {
  indexed_at: datasets.indexed_at,
  nodes: [
    {
      path: "按任务",
      parent_path: null,
      name: "按任务",
      kind: "view",
      view: "task",
      format: null,
      version: null,
      dataset_id: null,
      entry_path: null,
      dataset_count: 2,
      entry_count: 2,
      size: { ...treeSize, known_bytes: 4096, total_bytes: 4096, measured_entry_count: 2 },
    },
    {
      path: "按格式",
      parent_path: null,
      name: "按格式",
      kind: "view",
      view: "format",
      format: null,
      version: null,
      dataset_id: null,
      entry_path: null,
      dataset_count: 1,
      entry_count: 1,
      size: treeSize,
    },
    ...[taskEntry, formatEntry].map((entry): Schema["DatasetTreeNode"] => ({
      ...entry,
      path: entry.entry_path,
      parent_path: entry.view === "task" ? "按任务" : "按格式",
      kind: "entry",
      dataset_count: 1,
      entry_count: 1,
      size: treeSize,
    })),
  ],
};
// 虚拟树仍跳到规范入口；独立样本用一组场景验证三种布局共享同一路径契约。
trees.nodes.push(
  {
    path: "按场景",
    parent_path: null,
    name: "按场景",
    kind: "view",
    view: "scene",
    format: null,
    version: null,
    dataset_id: null,
    entry_path: null,
    dataset_count: 1,
    entry_count: 1,
    size: treeSize,
  },
  {
    path: "按场景/tabletop",
    parent_path: "按场景",
    name: "桌面",
    kind: "scene",
    view: "scene",
    format: null,
    version: null,
    dataset_id: null,
    entry_path: null,
    dataset_count: 1,
    entry_count: 1,
    size: treeSize,
  },
  {
    ...taskEntry,
    path: "按场景/tabletop/libero_10",
    parent_path: "按场景/tabletop",
    kind: "entry",
    view: "scene",
    dataset_count: 1,
    entry_count: 1,
    size: treeSize,
  },
);
export const filters: Schema["DatasetFilterOptions"] = {
  robot_models_registered: false,
  default_robot_filter: "robot_type",
  robot_models: [],
  robot_model_options: [{ value: "unknown", label: "未知", count: 2 }],
  robot_types: [
    { value: "franka", label: "franka", count: 1 },
    { value: "g2a", label: "g2a", count: 1 },
    { value: "unknown", label: "未知", count: 0 },
  ],
  fps: [
    { value: "20", label: "20", count: 1 },
    { value: "30", label: "30", count: 1 },
    { value: "unknown", label: "未知", count: 0 },
  ],
  data_origins: [{ value: "unknown", label: "未知", count: 2 }],
  scenes: [
    { value: "tabletop", label: "桌面", count: 1 },
    { value: "unlabeled", label: "未标注", count: 1 },
  ],
  tasks: [
    { value: "pick_place", label: "抓取放置", count: 1 },
    { value: "tidy", label: "收纳整理", count: 1 },
    { value: "unlabeled", label: "未标注", count: 1 },
  ],
  scene_vocabulary: [
    { code: "kitchen", name: "家居-厨房" },
    { code: "tabletop", name: "桌面" },
  ],
  task_vocabulary: [
    { code: "pick_place", name: "抓取放置" },
    { code: "tidy", name: "收纳整理" },
  ],
};
export const detail: Schema["DatasetDetailResponse"] = {
  provenance: { state: "absent", data_origin: "未知", data_origin_set_by: null },
  entry: taskEntry,
  entries: [taskEntry, formatEntry],
  canonical_entry_path: taskEntry.entry_path,
  dataset_size: size,
  indexed_at: "2026-10-29T12:00:00Z",
  observed_at: "2026-10-29T12:10:00Z",
  index_stale: false,
  subtasks_entry_path: taskEntry.entry_path,
  diagnostics: [],
  links: [],
  sources: [],
  information: {
    name: "数据集信息.json",
    entry_path: taskEntry.entry_path,
    content:
      '{"dataset_id":"dataset-14","fields":[{"number":1,"name":"标识","value_markdown":"libero_10"}]}',
    usable: true,
    sha256: "abc",
    diagnostics: [],
  },
  canonical_information: null,
  original_paths: {
    name: "原始路径.json",
    entry_path: taskEntry.entry_path,
    content: '{"dataset_id":"dataset-14","sources":[]}',
    usable: true,
    sha256: "def",
    diagnostics: [],
  },
};
export const panel: Schema["DatasetPanelResponse"] = {
  findings: [
    {
      group: "json",
      severity: "action_required",
      diagnostics: {
        rule: "TOP_LEVEL_UNREGISTERED",
        source: "平台",
        total: 7,
        error_count: 7,
        warning_count: 0,
        samples: [
          {
            level: "error",
            category: "input",
            stage: "检查导航一致性",
            source: "平台",
            objects: [{ key: "entry_path", value: "VGX_video/" }],
            rule: "TOP_LEVEL_UNREGISTERED",
            actual: "未登记目录",
            expected: "登记的非数据集目录",
            consequence: "不扫描此目录",
            next_step: "核对是否需要登记",
            error_chain: [],
          },
        ],
      },
    },
  ],
  indexed_at: datasets.indexed_at,
  storage_roots: [],
};

/** 一个账号保存的布局偏好；测试里用两个对象模拟两个账号，互不影响。 */
export type LayoutStore = Schema["LayoutResponse"];

/**
 * 创建数据集页面的 HTTP 边界替身，其他页面复用现有样本。
 * @param requests - 接收实际 Request，供测试检查 URL 与请求体，不访问网络。
 * @param layout - 当前账号保存的布局偏好；GET 读它，PUT 改它，默认是无偏好行时的 A 和 null。
 * @returns 注入真实客户端的传输；不替换内部模块。
 * @throws 无。
 * @sideEffects 只向传入数组追加请求；PUT /api/datasets/layout 会改传入的偏好对象。
 * @timeSemantics 每次即时响应，无定时器。
 */
export function datasetFetch(
  requests: Request[] = [],
  layout: LayoutStore = { layout: "A", updated_at: null },
): FetchImplementation {
  const fallback = pageFetch();
  return (request) => {
    requests.push(request);
    const url = new URL(request.url);
    if (url.pathname === "/api/datasets/layout") {
      if (request.method !== "PUT") return Promise.resolve(Response.json(layout));
      return request.json().then((body: Schema["LayoutRequest"]) => {
        layout.layout = body.layout;
        layout.updated_at = "2026-10-29T12:00:00Z";
        return Response.json(layout);
      });
    }
    if (url.pathname === "/api/datasets/trees") {
      // 与服务端一致：给了 entry_path 就只返回该路径前缀下的节点。
      const prefix = url.searchParams.get("entry_path");
      const nodes = prefix
        ? trees.nodes.filter((node) => node.path === prefix || node.path.startsWith(`${prefix}/`))
        : trees.nodes;
      return Promise.resolve(Response.json({ ...trees, nodes }));
    }
    if (url.pathname === "/api/datasets/filters") return Promise.resolve(Response.json(filters));
    if (url.pathname === "/api/datasets/panel") return Promise.resolve(Response.json(panel));
    if (url.pathname === "/api/datasets/detail")
      return Promise.resolve(
        Response.json({
          ...detail,
          entry:
            url.searchParams.get("entry_path") === formatEntry.entry_path ? formatEntry : taskEntry,
        }),
      );
    if (url.pathname === "/api/datasets") {
      const selected = datasets.items.filter(
        (item) =>
          (!url.searchParams.has("robot_type") ||
            item.robot_types.includes(url.searchParams.get("robot_type"))) &&
          (!url.searchParams.has("fps") || item.fps.includes(Number(url.searchParams.get("fps")))),
      );
      return Promise.resolve(
        Response.json({ ...datasets, items: selected, total: selected.length }),
      );
    }
    return fallback(request);
  };
}
