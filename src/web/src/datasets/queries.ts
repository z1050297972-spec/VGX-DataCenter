// 数据集查询状态（M1-04）；使用现有 Query 的取消与账号生命周期，不维护第二套缓存。
import { useQuery } from "@tanstack/react-query";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import {
  DATASET_STALE_TIME_MS,
  DATASET_GC_TIME_MS,
  getDatasetPanel,
  getDatasetDetail,
  getDatasetFilters,
  getDatasetTrees,
  listDatasets,
  type DatasetQuery,
} from "../api/datasets";

/**
 * 订阅同一筛选下的列表及两棵树。
 * @param filters - 生成接口类型约束的筛选及分页。
 * @returns 列表、树、候选和面板四个独立查询，任一失败仍可展示其他项。
 * @throws Error 缺少账号 Provider；请求错误保留在查询 error。
 * @sideEffects 经账号客户端发列表和树 GET，key 含账号；不改 URL。
 * @timeSemantics 进入或参数变化时读取，立即失效、离页清除，不轮询、不重试；卸载取消请求。
 */
export function useDatasetBrowser(filters: DatasetQuery) {
  const client = useAccountClient();
  const identity = useCurrentAccount();
  const options = {
    retry: false,
    staleTime: DATASET_STALE_TIME_MS,
    gcTime: DATASET_GC_TIME_MS,
    refetchOnWindowFocus: false,
  } as const;
  const treeFilters = {
    robot_type: filters.robot_type,
    robot_model_id: filters.robot_model_id,
    data_origin: filters.data_origin,
    fps: filters.fps,
    entry_path: filters.entry_path,
  };
  return {
    panel: useQuery({
      ...options,
      queryKey: ["datasets", identity.data?.account_id, "panel"],
      queryFn: ({ signal }) => getDatasetPanel({ client, payload: undefined, signal }),
    }),
    filters: useQuery({
      ...options,
      queryKey: ["datasets", identity.data?.account_id, "filters"],
      queryFn: ({ signal }) => getDatasetFilters({ client, payload: undefined, signal }),
    }),
    list: useQuery({
      ...options,
      queryKey: ["datasets", identity.data?.account_id, "list", filters],
      queryFn: ({ signal }) => listDatasets({ client, payload: filters, signal }),
    }),
    trees: useQuery({
      ...options,
      queryKey: ["datasets", identity.data?.account_id, "trees", treeFilters],
      queryFn: ({ signal }) => getDatasetTrees({ client, payload: treeFilters, signal }),
    }),
  };
}

/**
 * 订阅当前入口详情，取消前一个入口的请求。
 * @param entryPath - 已选中的相对入口路径。
 * @returns 详情查询状态，失败时不伪造空详情。
 * @throws Error 缺少 Provider；服务端故障在 error 中返回。
 * @sideEffects 通过账号客户端读详情，缓存按账号及入口隔离。
 * @timeSemantics 进入及切换入口现场读取，不轮询；离页清缓存并取消请求，不重试。
 */
export function useDatasetDetail(entryPath: string) {
  const client = useAccountClient();
  const identity = useCurrentAccount();
  return useQuery({
    queryKey: ["datasets", identity.data?.account_id, "detail", entryPath],
    queryFn: ({ signal }) => getDatasetDetail({ client, payload: entryPath, signal }),
    retry: false,
    staleTime: DATASET_STALE_TIME_MS,
    gcTime: DATASET_GC_TIME_MS,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}
