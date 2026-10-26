// 详情页显示计算（08/09 Answer）：只计算速度、剩余和已用时间，不计算作业结果。
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
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function calculateJobRate(_samples: readonly ProgressSample[]): JobRate {
  throw new Error("未实现");
}

/**
 * 判断详情的业务轮询是否可以结束。
 * @param _job - 服务器已校验 Job，不将正在取消当成终态。
 * @returns completed/cancelled/interrupted 为 true；queued/running/cancelling 为 false。
 * @throws Error 状态不在生成契约范围或状态/摘要不一致。
 * @sideEffects 无；调用方据此停止详情和日志轮询，保留全局 worker 在线轮询。
 * @timeSemantics 同步，不使用时间猜作业是否完成。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function isJobTerminal(_job: Job): boolean {
  throw new Error("未实现");
}

/**
 * 展示三个进行中状态或六种结局。
 * @param _job - 生成的 Job；completed 的摘要必须有服务器结果。
 * @returns 排队中、运行中、正在取消、成功、带警告成功、部分成功、失败、已取消或已中断之一。
 * @throws Error completed 缺失 outcome 或其他状态携带 outcome，按缺陷呈现而非猜成功。
 * @sideEffects 无；只映射标签，不根据前端计数重算 outcome。
 * @timeSemantics 同步无时钟；已取消和已中断仍保留最后阶段和计数显示。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function jobStatusLabel(_job: Job): string {
  throw new Error("未实现");
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
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 规则4要求函数体仅抛未实现异常，完整输入签名必须保留。
export function useJobTiming(_job: Job | undefined): JobTiming {
  throw new Error("未实现");
}
