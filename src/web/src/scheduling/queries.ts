// 只读调度轮询；沿用第8张账号感知传输、身份缓存清理及取消生命周期。
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { getScheduling, type Scheduling } from "../api/scheduling";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { JOB_POLL_INTERVAL_MS, JOB_STALE_TIME_MS, JOB_GC_TIME_MS } from "../api/jobs";

/**
 * 轮询只读调度状态，在同一页面同时显示资源和每日计划。
 * @returns Scheduling 的查询状态；请求失败保留 error，不合成空闲卡或零运行数。
 * @throws Error 账号 Provider 缺失；网络和服务端错误由查询结果返回供 DiagnosticCard 渲染。
 * @sideEffects 用 useAccountClient 调 getScheduling，queryKey 以 scheduling 为前缀并包含账号编号；身份改变清缓存、卸载取消请求，401 统一回登录。
 * @timeSemantics 复用 JOB_POLL_INTERVAL_MS 每秒轮询，JOB_STALE_TIME_MS/JOB_GC_TIME_MS=0、retry=false；同页只维护一份查询。
 */
export function useScheduling(): UseQueryResult<Scheduling> {
  const client = useAccountClient();
  const identity = useCurrentAccount();
  return useQuery({
    queryKey: ["scheduling", identity.data?.account_id],
    enabled: !!identity.data && !identity.data.must_change_password,
    queryFn: ({ signal }) => getScheduling({ client, payload: undefined, signal }),
    refetchInterval: JOB_POLL_INTERVAL_MS,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
    retry: false,
  });
}
