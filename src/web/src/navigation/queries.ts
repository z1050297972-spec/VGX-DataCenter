// 导航层恢复失败标记的 Query（M1-07）；与 worker 状态提示相同的约 1 秒轮询。
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { JOB_GC_TIME_MS, JOB_POLL_INTERVAL_MS, JOB_STALE_TIME_MS } from "../api/jobs";
import {
  acknowledgeRecoveryBlock,
  getRecoveryBlock,
  type AcknowledgeResult,
  type RecoveryBlock,
} from "../api/navigation";

const KEY = ["navigation", "recovery-block"] as const;

/**
 * 在登录布局和详情页共用的恢复失败标记查询。
 * @returns RecoveryBlock 查询状态；错误保留在 error，不当作有或没有标记。
 * @throws Error 缺少账号 Provider。
 * @sideEffects 共享一个 Query；未登录或必须改密时不请求。
 * @timeSemantics 每 JOB_POLL_INTERVAL_MS 轮询、无重试，离页取消。
 */
export function useRecoveryBlock(): UseQueryResult<RecoveryBlock> {
  const client = useAccountClient();
  const account = useCurrentAccount();
  return useQuery({
    queryKey: KEY,
    queryFn: ({ signal }) => getRecoveryBlock({ client, payload: undefined, signal }),
    enabled: !!account.data && !account.data.must_change_password,
    refetchInterval: JOB_POLL_INTERVAL_MS,
    retry: false,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
  });
}

/**
 * 管理员确认已处理。
 * @returns 无参数 Mutation；成功后立刻把缓存置为未挡住并失效作业与标记查询。
 * @throws Error 缺少 Provider；HTTP 失败放 mutation.error，不乐观清除。
 * @sideEffects 调 acknowledgeRecoveryBlock；成功刷新 navigation、jobs、scheduling 缓存。
 * @timeSemantics 单次请求，无重试；服务端下一轮领取（约 1 秒）放行排队的写作业。
 */
export function useAcknowledgeRecoveryBlock(): UseMutationResult<AcknowledgeResult, Error, void> {
  const client = useAccountClient();
  const cache = useQueryClient();
  return useMutation({
    mutationFn: () =>
      acknowledgeRecoveryBlock({
        client,
        payload: undefined,
        signal: new AbortController().signal,
      }),
    onSuccess: async () => {
      cache.setQueryData<RecoveryBlock>(KEY, { blocked: false });
      await cache.invalidateQueries({ queryKey: ["navigation"] });
      await cache.invalidateQueries({ queryKey: ["jobs"] });
    },
    retry: false,
    gcTime: JOB_GC_TIME_MS,
  });
}
