// 共用的有界请求执行器；传输即使忽略取消，也不能把迟到结果交还页面。
import { toFailureView } from "./problems";

/**
 * 在调用方取消或具名超时上限到达时终止一次请求等待。
 * @param signal - 调用方的取消信号，必填。
 * @param timeoutMs - 调用方具名常量给出的正整数毫秒上限。
 * @param action - 使用合并信号发出一次类型化请求的闭包，不缓存浏览器原生方法。
 * @returns 请求完成值，取消或超时先发生时拒绝并忽略迟到结果。
 * @throws Error 已取消、到期或请求失败，保留安全的诊断cause，不自动重试。
 * @sideEffects 调用action一次；结束后移除监听器并清除计时器，不写缓存或持久存储。
 * @timeSemantics 超时由timeoutMs控制，取消不保证服务器撤销已执行的事务。
 */
export function boundedRequest<T>(
  signal: AbortSignal,
  timeoutMs: number,
  action: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  if (signal.aborted) return Promise.reject(new Error("请求失败", { cause: toFailureView(null) }));
  const controller = new AbortController();
  const combined = AbortSignal.any([signal, controller.signal]);
  const timer = setTimeout(() => {
    controller.abort();
  }, timeoutMs);
  let aborted: () => void = () => undefined;
  const pending = new Promise<T>((resolve, reject) => {
    aborted = () => {
      reject(new Error("请求失败", { cause: toFailureView(null) }));
    };
    combined.addEventListener("abort", aborted, { once: true });
    void action(combined).then(resolve, reject);
  });
  return pending.finally(() => {
    clearTimeout(timer);
    combined.removeEventListener("abort", aborted);
  });
}
