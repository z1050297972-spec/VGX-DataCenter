// 数据集 HTTP 边界（M1-04）：复用生成类型、账号客户端与有界请求，不访问数据路径。
import type { components, operations } from "./schema";
import type { AccountCall } from "./accounts";
import { boundedRequest } from "./_request";
import { toFailureView } from "./problems";

export type DatasetList = components["schemas"]["DatasetListResponse"];
export type DatasetTrees = components["schemas"]["DatasetTreesResponse"];
export type DatasetFilters = components["schemas"]["DatasetFilterOptions"];
export type DatasetDetail = components["schemas"]["DatasetDetailResponse"];
export type DatasetPanel = components["schemas"]["DatasetPanelResponse"];
export type DatasetLayout = components["schemas"]["LayoutResponse"]["layout"];
export type DatasetQuery = NonNullable<operations["list_datasets"]["parameters"]["query"]>;
/** 导航文件含约 14 MB 原文，单次请求最多等待 60 秒；重试必须由用户发起。 */
export const DATASET_REQUEST_TIMEOUT_MS = 60_000;
/** 列表每页 20 个数据集，与原型一致，不全量预加载详情。 */
export const DATASET_PAGE_SIZE = 20;
/** 索引查询立即失效，单位毫秒；重新进入页面时读取最新发布结果。 */
export const DATASET_STALE_TIME_MS = 0;
/** 离页即清缓存，单位毫秒；避免保留大文件或前一个账号的数据。 */
export const DATASET_GC_TIME_MS = 0;

/**
 * 读取按编号去重的一页数据集。
 * @param input - 账号客户端、生成类型约束的筛选分页与取消信号。
 * @returns 索引列表及总数，空索引也有明确 total。
 * @throws Error HTTP、取消、超时或响应缺失，由统一诊断展示。
 * @sideEffects 发出一次 GET /api/datasets，不访问响应内路径。
 * @timeSemantics 最多 DATASET_REQUEST_TIMEOUT_MS；索引时刻来自服务端，不自动重试。
 */
export function listDatasets(input: AccountCall<DatasetQuery>): Promise<DatasetList> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.GET("/api/datasets", {
      params: { query: input.payload },
      signal,
    });
    return required(result.data);
  });
}

/**
 * 读取共享筛选下的三棵浏览树。
 * @param input - 客户端、筛选与取消信号；分页值不影响树。
 * @returns 平铺节点及扫描时间，父路径由接口决定。
 * @throws Error 传输失败、超时、取消或响应缺失。
 * @sideEffects 发一次 GET /api/datasets/trees，不探测链接目标。
 * @timeSemantics 最多 DATASET_REQUEST_TIMEOUT_MS，无轮询或重试。
 */
export function getDatasetTrees(input: AccountCall<DatasetQuery>): Promise<DatasetTrees> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.GET("/api/datasets/trees", {
      params: { query: input.payload },
      signal,
    });
    return required(result.data);
  });
}

function required<T>(value: T | undefined): T {
  if (value == null) throw new Error("请求失败", { cause: toFailureView(null) });
  return value;
}

/**
 * 读取未应用当前筛选的全局候选。
 * @param input - 账号客户端及取消信号，payload 为 undefined。
 * @returns 导航型号、FPS 与分类候选，未知项由服务器给出。
 * @throws Error 请求失败、取消、超时或缺少响应体。
 * @sideEffects 发一次 GET /api/datasets/filters，不探测机器人或存储根。
 * @timeSemantics 候选是最近索引快照，单次最多 60 秒。
 */
export function getDatasetFilters(input: AccountCall): Promise<DatasetFilters> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.GET("/api/datasets/filters", { signal });
    return required(result.data);
  });
}

/**
 * 读取所选入口详情及规范副本，子任务正文由独立接口按需读取。
 * @param input - 客户端、相对入口路径与取消信号。
 * @returns 当前入口原文、规范信息及带历史时刻的索引状态。
 * @throws Error 路径非法、入口不存在、I/O、超时或取消，均交统一诊断。
 * @sideEffects 发一次 GET /api/datasets/detail，不请求子任务或真实存储路径。
 * @timeSemantics 服务端 observed_at 与 indexed_at 分开展示；请求最多 60 秒，无重试。
 */
export function getDatasetDetail(input: AccountCall<string>): Promise<DatasetDetail> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.GET("/api/datasets/detail", {
      params: { query: { entry_path: input.payload } },
      signal,
    });
    return required(result.data);
  });
}

/**
 * 读取全索引的一致性聚合结果和扫描时存储根状态。
 * @param input - 账号客户端与取消信号，payload 为 undefined。
 * @returns 四组两级发现及完整计数、有界样例，不自行合并丢失计数。
 * @throws Error HTTP、取消、超时或响应缺失。
 * @sideEffects 发一次 GET /api/datasets/panel，只读索引。
 * @timeSemantics 最多 60 秒，状态属于最近扫描，不是浏览时的实时磁盘探测。
 */
export function getDatasetPanel(input: AccountCall): Promise<DatasetPanel> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.GET("/api/datasets/panel", { signal });
    return required(result.data);
  });
}

/**
 * 手动提交一次全量导航层与存储一致性排查。
 * @param input - 已认证客户端、undefined payload 和取消信号；范围固定为全部数据集。
 * @returns 新提交的扫描作业；权限沿用现有通用作业入口。
 * @throws Error 请求失败交统一诊断，不自动重发提交。
 * @sideEffects POST /api/jobs，只写作业及审计记录，扫描由 worker 只读执行。
 * @timeSemantics 请求最多 DATASET_REQUEST_TIMEOUT_MS，不等待扫描结束；结果时间来自发布索引。
 */
export function rescanAllDatasets(
  input: AccountCall,
): Promise<components["schemas"]["JobResponse"]> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/jobs", {
      body: { type_name: "dataset_rescan", parameters: { dataset_id: null } },
      signal,
    });
    return required(result.data);
  });
}

/**
 * 为单个已入索引数据集提交重新扫描作业。
 * @param input - 客户端、永久 dataset_id 与取消信号，不能传入口或存储路径冒充编号。
 * @returns 已创建作业记录，不等待扫描完成。
 * @throws Error 404、422、冲突、权限或传输错误，交统一诊断。
 * @sideEffects POST /api/datasets/{dataset_id}/rescan；服务器写作业记录，不在 Web 写导航层。
 * @timeSemantics 最多 60 秒，不自动重试；超时或取消不能证明服务端没有提交。
 */
export function rescanDataset(
  input: AccountCall<string>,
): Promise<components["schemas"]["JobResponse"]> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/datasets/{dataset_id}/rescan", {
      params: { path: { dataset_id: input.payload } },
      signal,
    });
    return required(result.data);
  });
}

/**
 * 提交当前数据集的统计大小作业。
 * @param input - 账号客户端、非空永久编号与取消信号，不允许页面意外提交全量统计。
 * @returns 新作业记录；成功后由共用作业动作进入详情。
 * @throws Error 服务端拒绝、取消、超时或响应缺失，沿用统一失败诊断。
 * @sideEffects 一次 POST /api/datasets/sizing，只含 dataset_id；Web 不遍历存储根。
 * @timeSemantics 单次等待最多60秒，不重试；取消请求不保证服务端回滚已创建作业。
 */
export function sizeDataset(
  input: AccountCall<string>,
): Promise<components["schemas"]["JobResponse"]> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.POST("/api/datasets/sizing", {
      body: { dataset_id: input.payload },
      signal,
    });
    return required(result.data);
  });
}

/**
 * 读取当前账号上次选的数据集布局。
 * @param input - 账号客户端与取消信号，payload 为 undefined；账号由会话决定，不能指定。
 * @returns A、B 或 C；没有保存过时服务端给 A。
 * @throws Error 传输失败、超时、取消、HTTP 错误或响应缺失，由页面降级为 A 并展示诊断。
 * @sideEffects 发一次 GET /api/datasets/layout，服务端不创建记录。
 * @timeSemantics 最多 DATASET_REQUEST_TIMEOUT_MS，无重试。
 */
export async function getDatasetLayout(input: AccountCall): Promise<DatasetLayout> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.GET("/api/datasets/layout", { signal });
    return required(result.data).layout;
  });
}

/**
 * 保存当前账号选择的数据集布局。
 * @param input - 账号客户端、布局取值与取消信号；请求体只含 layout，不含账号编号。
 * @returns 服务端已保存的布局。
 * @throws Error 传输失败、超时、取消、422 或其他 HTTP 错误；失败时旧偏好保持不变。
 * @sideEffects 发一次 PUT /api/datasets/layout，只改当前账号的偏好行。
 * @timeSemantics 最多 DATASET_REQUEST_TIMEOUT_MS，不重试；多次保存以最后一次到达服务端的为准。
 */
export async function setDatasetLayout(input: AccountCall<DatasetLayout>): Promise<DatasetLayout> {
  return boundedRequest(input.signal, DATASET_REQUEST_TIMEOUT_MS, async (signal) => {
    const result = await input.client.PUT("/api/datasets/layout", {
      body: { layout: input.payload },
      signal,
    });
    return required(result.data).layout;
  });
}
