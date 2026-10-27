// 详情页显示计算（08/09 Answer）：只计算速度、剩余和已用时间，不计算作业结果。
import { useEffect, useState, useSyncExternalStore } from "react";
import { JOB_POLL_INTERVAL_MS } from "../api/jobs";
import type { Job } from "../api/jobs";

/** 速度使用最近约 10 秒的轮询样本，单位毫秒；不使用一秒窗口放大抖动。 */
export const JOB_RATE_WINDOW_MS = 10000;
/** 每秒一次轮询，最多保留窗口边界两侧共 12 份样本，避免长作业内存增长。 */
export const JOB_RATE_SAMPLE_LIMIT = 12;
/** 至少两个不同时间的样本才能算速度；单位份。 */
export const JOB_RATE_MIN_SAMPLES = 2;

/** 单个已接收样本；用 performance.now，不用浏览器墙钟算速度。 */
export interface ProgressSample {
  /** 接收时本进程单调毫秒数，有限非负。 */
  receivedAtMs: number;
  /** 最新 Job 响应；阶段变化、重跑计数归零时清空前序样本。 */
  job: Job;
}
/** 可显示的速率和预计剩余时间；null 表示证据不足。 */
export interface JobRate {
  /** 当前单位每秒处理量；有限非负，没有进展或样本不够为 null。 */
  unitsPerSecond: number | null;
  /** 剩余秒数；未知 total、速度为零或证据不足为 null。 */
  remainingSeconds: number | null;
}

/**
 * 以最近十秒且同一阶段的样本计算速度与剩余时间。
 * @param _samples - 接收时刻升序的有界样本，最多 JOB_RATE_SAMPLE_LIMIT；不接受不同作业混合。
 * @returns 有效样本至少两份且时间有差、done 增长时算增量/秒；未知 total 只给速度，剩余为 null；阶段/计数重置后的样本重新累计。
 * @throws Error 非法单调时刻、顺序、编号或非有限计数，属于显示计算缺陷，不生成 NaN/Infinity。
 * @sideEffects 无；不修改样本或请求缓存，不编造总数，不改变后端 outcome。
 * @timeSemantics 仅使用接收单调毫秒，窗口 JOB_RATE_WINDOW_MS；相同 progress_at 的重复快照不能伪装新进展。
 */
export function calculateJobRate(_samples: readonly ProgressSample[]): JobRate {
  const empty = { unitsPerSecond: null, remainingSeconds: null };
  const samples = rateSamples(_samples);
  const first = samples[0];
  const end = samples.at(-1);
  if (samples.length < JOB_RATE_MIN_SAMPLES || !first?.job.progress || !end?.job.progress)
    return empty;
  const seconds = (end.receivedAtMs - first.receivedAtMs) / 1000;
  const units = end.job.progress.done - first.job.progress.done;
  if (seconds <= 0 || units <= 0) return empty;
  const unitsPerSecond = units / seconds;
  return {
    unitsPerSecond,
    remainingSeconds:
      end.job.progress.total === null
        ? null
        : Math.max(0, end.job.progress.total - end.job.progress.done) / unitsPerSecond,
  };
}

/**
 * 判断详情的业务轮询是否可以结束。
 * @param _job - 服务器已校验 Job，不将正在取消当成终态。
 * @returns completed/cancelled/interrupted 为 true；queued/running/cancelling 为 false。
 * @throws Error 状态不在生成契约范围或状态/摘要不一致。
 * @sideEffects 无；调用方据此停止详情和日志轮询，保留全局 worker 在线轮询。
 * @timeSemantics 同步，不使用时间猜作业是否完成。
 */
export function isJobTerminal(_job: Job): boolean {
  const terminal = ["completed", "cancelled", "interrupted"].includes(_job.state);
  if (
    !["queued", "running", "cancelling", "completed", "cancelled", "interrupted"].includes(
      _job.state,
    ) ||
    terminal !== (_job.summary !== null)
  )
    throw new Error("作业状态与摘要不一致");
  if (
    _job.summary &&
    (_job.summary.state !== _job.state ||
      (_job.state === "completed") !== (_job.summary.outcome !== null))
  )
    throw new Error("作业状态与结果不一致");
  return terminal;
}

/**
 * 展示三个进行中状态或六种结局。
 * @param _job - 生成的 Job；completed 的摘要必须有服务器结果。
 * @returns 排队中、运行中、正在取消、成功、带警告成功、部分成功、失败、已取消或已中断之一。
 * @throws Error completed 缺失 outcome 或其他状态携带 outcome，按缺陷呈现而非猜成功。
 * @sideEffects 无；只映射标签，不根据前端计数重算 outcome。
 * @timeSemantics 同步无时钟；已取消和已中断仍保留最后阶段和计数显示。
 */
export function jobStatusLabel(_job: Job): string {
  isJobTerminal(_job);
  if (_job.state === "completed") {
    const outcome = _job.summary?.outcome;
    if (!outcome) throw new Error("已完成作业缺少结果");
    return JOB_OUTCOME_LABELS[outcome];
  }
  return JOB_STATE_LABELS[_job.state];
}

/** 详情可显示的时间量，空详情或尚无计时样本时不伪造数值。 */
export interface JobTiming extends JobRate {
  /** 已用秒数；queued为0，执行中使用已保存片段加本地单调增量，终态取摘要，空详情为null。 */
  elapsedSeconds: number | null;
}

/**
 * 为详情维护有界的速度样本与已用时间。
 * @param _job - 最新详情或undefined；更换编号、阶段切换、重跑计数归零时重建采样窗口。
 * @returns JobTiming；少于两份有效样本不显示速度，未知total不显示剩余，空详情不伪造已用时。
 * @throws Error 非法响应状态或单调时刻；请求错误仍由外层Query呈现。
 * @sideEffects 仅维护至多JOB_RATE_SAMPLE_LIMIT份内存样本及显示计时器，不写缓存/URL/持久存储；卸载清理计时器。
 * @timeSemantics 直接调用performance.now()取单调毫秒，不将原生方法保存到对象；最近10秒窗口、每秒更新显示，终态停止计时。
 */
export function useJobTiming(_job: Job | undefined): JobTiming {
  const [store] = useState(() => new TimingStore());
  useEffect(() => {
    store.accept(_job, performance.now());
    if (!_job || _job.state === "queued" || isJobTerminal(_job)) return;
    const timer = setInterval(() => {
      store.tick(performance.now());
    }, JOB_POLL_INTERVAL_MS);
    return () => {
      clearInterval(timer);
    };
  }, [_job, store]);
  return useSyncExternalStore(store.subscribe, store.snapshot, store.snapshot);
}

function rateSamples(samples: readonly ProgressSample[]): readonly ProgressSample[] {
  if (samples.length > JOB_RATE_SAMPLE_LIMIT) throw new Error("进度样本超过上限");
  const last = samples.at(-1);
  if (!last) return [];
  let start = 0;
  for (const [index, sample] of samples.entries()) {
    const previous = samples[index - 1];
    validateSample(sample, previous, last.job.job_id);
    if (resetSample(previous?.job.progress, sample.job.progress)) start = index;
  }
  const seen = new Set<string | null>();
  return samples.slice(start).filter((sample) => {
    if (
      sample.receivedAtMs < last.receivedAtMs - JOB_RATE_WINDOW_MS ||
      seen.has(sample.job.progress_at)
    )
      return false;
    seen.add(sample.job.progress_at);
    return true;
  });
}
function validateSample(
  sample: ProgressSample,
  previous: ProgressSample | undefined,
  jobId: string,
): void {
  if (
    !Number.isFinite(sample.receivedAtMs) ||
    sample.receivedAtMs < 0 ||
    sample.job.job_id !== jobId ||
    (previous && sample.receivedAtMs < previous.receivedAtMs)
  )
    throw new Error("进度样本不合法");
  const progress = sample.job.progress;
  if (progress && !Number.isFinite(progress.done)) throw new Error("进度计数不合法");
}
function resetSample(previous: Job["progress"] | undefined, current: Job["progress"]): boolean {
  return (
    !!previous &&
    !!current &&
    (current.stage_index !== previous.stage_index ||
      current.done < previous.done ||
      current.total_items < previous.total_items)
  );
}

// 每个hook独立的内存外部存储；通过订阅通知React，effect不直接同步setState。
class TimingStore {
  private value: JobTiming = { unitsPerSecond: null, remainingSeconds: null, elapsedSeconds: null };
  private samples: ProgressSample[] = [];
  private job: Job | undefined;
  private receivedAtMs = 0;
  private baseElapsedSeconds = 0;
  private lastReadMs = 0;
  private listeners = new Set<() => void>();
  snapshot = (): JobTiming => this.value;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  accept(job: Job | undefined, now: number): void {
    this.clock(now);
    const changed = this.recordSample(job, now);
    const previous = changed ? null : this.elapsed(now);
    this.job = job;
    this.receivedAtMs = now;
    // 较旧的服务端快照不能重置本地计时起点并让显示冻结；继承已走过的单调片段。
    this.baseElapsedSeconds = job?.elapsed_s ?? 0;
    if (activeJob(job) && previous !== null)
      this.baseElapsedSeconds = Math.max(this.baseElapsedSeconds, previous);
    const elapsed = this.elapsed(now);
    this.publish({
      ...calculateJobRate(this.samples),
      elapsedSeconds: elapsed,
    });
  }
  private recordSample(job: Job | undefined, now: number): boolean {
    const changed = this.job?.job_id !== job?.job_id;
    if (changed || resetSample(this.job?.progress, job?.progress ?? null)) this.samples = [];
    if (job)
      this.samples = [...this.samples, { receivedAtMs: now, job }].slice(-JOB_RATE_SAMPLE_LIMIT);
    return changed;
  }
  tick(now: number): void {
    this.clock(now);
    if (!activeJob(this.job)) return;
    this.publish({
      ...this.value,
      elapsedSeconds: Math.max(this.value.elapsedSeconds ?? 0, this.elapsed(now) ?? 0),
    });
  }
  private elapsed(now: number): number | null {
    if (!this.job) return null;
    if (this.job.state === "queued") return 0;
    if (isJobTerminal(this.job)) return this.job.summary?.elapsed_s ?? null;
    return this.baseElapsedSeconds + Math.max(0, now - this.receivedAtMs) / 1000;
  }
  private clock(now: number): void {
    if (!Number.isFinite(now) || now < 0 || now < this.lastReadMs)
      throw new Error("单调时钟不合法");
    this.lastReadMs = now;
  }
  private publish(value: JobTiming): void {
    this.value = value;
    for (const listener of this.listeners) listener();
  }
}
function activeJob(job: Job | undefined): boolean {
  return !!job && job.state !== "queued" && !isJobTerminal(job);
}

/** 后端作业结果的统一中文名称，列表、详情和定时计划共用。 */
export const JOB_OUTCOME_LABELS = {
  succeeded: "成功",
  succeeded_with_warnings: "带警告成功",
  partially_succeeded: "部分成功",
  failed: "失败",
} as const;
/** 尚未完成或取消/中断的状态名称，不把等待原因当成状态。 */
export const JOB_STATE_LABELS = {
  queued: "排队中",
  running: "运行中",
  cancelling: "正在取消",
  cancelled: "已取消",
  interrupted: "已中断",
} as const;
