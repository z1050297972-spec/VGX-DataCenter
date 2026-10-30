// M1-09 确认流程：先刷新排队提醒，再按用户看过的编号提交；不绕过 worker 的 L12 核对。
import { useEffect, useRef, useState, type ReactElement } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, Link } from "@tanstack/react-router";
import { Alert, Button, Checkbox } from "antd";
import { useAccountClient } from "../accounts/runtime";
import { getNavigationPreview, type NavigationPreview } from "../api/dataOrigin";
import { confirmNavigationWrite } from "../api/navigationWrites";
import { JOB_GC_TIME_MS, type Job } from "../api/jobs";
import { toFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";

type Queued = NavigationPreview["queued_jobs"];
type ConfirmationResult = { kind: "queue"; jobs: Queued } | { kind: "submitted"; job: Job };

/** 确认控件的可信预览与门禁状态。 */
interface ConfirmationProps {
  /** 成功读取的保存预览；账号/编号变化由调用者重新挂载。 */ preview: NavigationPreview;
  /** 恢复阻挡、未知或读失败时为 true。 */ blocked: boolean;
}
/**
 * 明确确认改指向或撤回，并处理新的排队409。
 * @param props - 当前预览及恢复门禁。
 * @returns 确认按钮和逐项 antd 勾选列表，确认成功后进入作业页。
 * @throws 无；请求错误由 DiagnosticCard 呈现。
 * @sideEffects 确认前 GET 刷新同份预览，然后 POST；离页取消并禁止迟到导航。
 * @timeSemantics 每次请求沿用10秒预算，无重试；pending 禁止重复点击，预览过期要求重新预览。
 */
export function NavigationConfirmation(props: ConfirmationProps): ReactElement {
  const client = useAccountClient();
  const navigate = useNavigate();
  const cache = useQueryClient();
  const owner = useRef<Owner>({
    mounted: false,
    active: null,
  });
  const [queue, setQueue] = useState<Queued>([]);
  useEffect(() => {
    const current = owner.current;
    current.mounted = true;
    return () => {
      current.mounted = false;
      current.active?.abort();
    };
  }, []);
  const action = useMutation({
    mutationFn: (ids: string[]) => runConfirmation(owner.current, props.preview, client, ids),
    onSuccess: async (result) => {
      if (!isMounted(owner.current)) return;
      if (result.kind === "queue") {
        setQueue(result.jobs);
        return;
      }
      await cache.invalidateQueries({ queryKey: ["jobs"] });
      if (isMounted(owner.current))
        await navigate({ to: "/jobs/$jobId", params: { jobId: result.job.job_id } });
    },
    retry: false,
    gcTime: JOB_GC_TIME_MS,
  });
  return (
    <div className="navigation-write">
      {action.error && <DiagnosticCard failure={toFailureView(action.error)} />}
      {queue.length ? (
        <QueueSelection
          key={queue.map((item) => item.job_id).join(",")}
          jobs={queue}
          disabled={props.blocked || action.isPending}
          onConfirm={(ids) => {
            if (!props.blocked) action.mutate(ids);
          }}
        />
      ) : (
        <Button
          aria-label="确认导航写入"
          type="primary"
          loading={action.isPending}
          disabled={props.blocked || action.isPending || action.isError}
          onClick={() => {
            if (!props.blocked) action.mutate([]);
          }}
        >
          确认写入
        </Button>
      )}
    </div>
  );
}
/** 确认流程的挂载与在途请求所有权。 */
interface Owner {
  mounted: boolean;
  active: AbortController | null;
}
// 函数边界让类型收窄不跨 await：卸载可能发生在任何等待期间。
function isMounted(owner: Owner): boolean {
  return owner.mounted;
}
// 取消检查放在函数里，类型收窄不跨 await：卸载或离页可能发生在任何等待期间。
function assertLive(owner: Owner, controller: AbortController): void {
  if (controller.signal.aborted || !isMounted(owner)) throw new Error("请求已取消");
}
async function submitFresh(
  controller: AbortController,
  client: ReturnType<typeof useAccountClient>,
  fresh: NavigationPreview,
  ids: string[],
): Promise<ConfirmationResult> {
  if (fresh.queued_jobs.some((item) => !ids.includes(item.job_id)))
    return { kind: "queue", jobs: fresh.queued_jobs };
  const job = await confirmNavigationWrite({
    client,
    payload: { preview_job_id: fresh.preview_job_id, acknowledged_queue_job_ids: ids },
    signal: controller.signal,
  });
  if (controller.signal.aborted) throw new Error("请求已取消");
  return { kind: "submitted", job };
}
async function runConfirmation(
  owner: Owner,
  preview: NavigationPreview,
  client: ReturnType<typeof useAccountClient>,
  ids: string[],
): Promise<ConfirmationResult> {
  if (owner.active) throw new Error("请求处理中");
  const controller = new AbortController();
  owner.active = controller;
  try {
    const fresh = await getNavigationPreview({
      client,
      payload: preview.preview_job_id,
      signal: controller.signal,
    });
    assertLive(owner, controller);
    if (fresh.preview_job_id !== preview.preview_job_id || fresh.operation !== preview.operation)
      throw new Error("预览关联不一致");
    return await submitFresh(controller, client, fresh, ids);
  } catch (error) {
    const jobs = queueFromError(error);
    if (jobs.length) return { kind: "queue", jobs };
    throw error;
  } finally {
    if (owner.active === controller) owner.active = null;
  }
}
function QueueSelection(props: {
  jobs: Queued;
  disabled: boolean;
  onConfirm: (ids: string[]) => void;
}): ReactElement {
  const [checked, setChecked] = useState<string[]>([]);
  const all = props.jobs.every((item) => checked.includes(item.job_id));
  return (
    <section aria-label="导航写入排队确认">
      <Alert type="warning" title="已有排队写作业，请逐项勾选确认" />
      {props.jobs.map((item) => (
        <div key={item.job_id}>
          <Checkbox
            aria-label={`确认排队作业 ${item.job_id}`}
            disabled={props.disabled}
            checked={checked.includes(item.job_id)}
            onChange={(event) => {
              setChecked((values) =>
                event.target.checked
                  ? [...values, item.job_id]
                  : values.filter((id) => id !== item.job_id),
              );
            }}
          >
            作业 #{item.job_id}
          </Checkbox>
          <Link to="/jobs/$jobId" params={{ jobId: item.job_id }}>
            查看作业
          </Link>
        </div>
      ))}
      <Button
        aria-label="确认排队并提交导航写入"
        type="primary"
        disabled={props.disabled || !all}
        onClick={() => {
          props.onConfirm(checked);
        }}
      >
        确认排队并提交
      </Button>
    </section>
  );
}
function queueFromError(error: unknown): Queued {
  const failure = toFailureView(error);
  if (failure.kind !== "problem" || failure.problem.status !== 409) return [];
  const ids = failure.problem.diagnostics
    .filter((item) => item.rule === "NAV_CREATE_QUEUE_CONFIRMATION")
    .flatMap((item) =>
      item.objects
        .filter(
          (object) =>
            /^queued_job_id_[1-9][0-9]*$/.test(object.key) &&
            /^[1-9][0-9]{0,18}$/.test(object.value),
        )
        .map((object) => object.value),
    );
  return [...new Set(ids)].map((job_id) => ({ job_id, dataset_ids: [] }));
}
