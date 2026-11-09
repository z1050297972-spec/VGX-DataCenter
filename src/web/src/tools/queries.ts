// 工具查询生命周期（M4-01）：清单不持久缓存，按账号隔离，离页或关闭详情时取消请求。
import type { ToolList } from "../api/cleaningTemp";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { getTool, getTools, type ToolDetail } from "../api/tools";

// 工具登记可在部署时改变，每次进入都重新读取；毫秒值 0 表示立即陈旧及离页清理。
const TOOL_STALE_TIME_MS = 0;
const TOOL_GC_TIME_MS = 0;
const queryOptions = {
  staleTime: TOOL_STALE_TIME_MS,
  gcTime: TOOL_GC_TIME_MS,
  retry: false,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
} as const;

/**
 * 给工具库页面提供列表和手动重新检查能力。
 * @returns 工具列表查询状态，错误不转换成空列表。
 * @throws Error 缺少账号 Provider；请求错误通过 query.error 返回。
 * @sideEffects 进入页面后请求工具列表，使用账号编号隔离内存缓存，不改 URL。
 * @timeSemantics 立即陈旧，离页清缓存并取消请求；无轮询、自动重试、聚焦或重连刷新。
 */
export function useTools(): UseQueryResult<ToolList> {
  const client = useAccountClient();
  const identity = useCurrentAccount();
  return useQuery({
    ...queryOptions,
    queryKey: ["tools", identity.data?.account_id],
    enabled: !!identity.data && !identity.data.must_change_password,
    queryFn: ({ signal }) => getTools({ client, signal, payload: undefined }),
  });
}

/**
 * 在详情抽屉打开时读取该工具的配置与命令。
 * @param name - 列表里的工具名，非空。
 * @returns 工具详情查询状态，失败保留统一错误对象。
 * @throws Error 缺少账号 Provider；请求失败由查询状态承载。
 * @sideEffects 请求指定工具详情，账号和工具名共同隔离缓存，不改 URL。
 * @timeSemantics 每次打开重新读取；关闭或换号时取消请求、清缓存，不轮询或重试。
 */
export function useTool(name: string): UseQueryResult<ToolDetail> {
  const client = useAccountClient();
  const identity = useCurrentAccount();
  return useQuery({
    ...queryOptions,
    queryKey: ["tools", identity.data?.account_id, name],
    enabled: !!identity.data && !identity.data.must_change_password,
    queryFn: ({ signal }) => getTool({ client, signal, payload: name }),
  });
}
