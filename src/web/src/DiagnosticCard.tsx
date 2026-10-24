// 统一诊断展示组件（M0 工单 04、规范 10.5）；使用 Ant Design，不负责请求协议或作业结果。
// 本票没有报错详情接口；可选回调为第 5 张存表后的接入点，缺省仅提示按编号查运行日志。
import type { ReactElement } from "react";
import type { ProblemResponse, RequestFailureView } from "./api/problems";

/** 工单 04 选择的详情加载上限，单位毫秒；避免展开后永久等待，独立于健康检查的超时策略。 */
export const ERROR_DETAILS_TIMEOUT_MS = 5000;

/** 卡片属性无物理量；服务端结构全部从 OpenAPI 生成类型间接取得。 */
export interface DiagnosticCardProps {
  /** 必填的已归一化请求失败；无默认值，无单位；服务端诊断保持原顺序。 */
  failure: RequestFailureView;
  /**
   * 可选的完整报错加载器；参数为服务端错误编号和取消信号，返回已脱敏纯文本。
   * 默认不提供；只用于程序缺陷。不得在回调中直接使用未批准的详情接口或回显秘密。
   */
  loadDetails?: (errorId: ProblemResponse["error_id"], signal: AbortSignal) => Promise<string>;
}

/**
 * 显示五段诊断或程序缺陷摘要，并在用户展开后才显示完整报错区域。
 *
 * @param props - 卡片输入，无单位，字段约束见 DiagnosticCardProps。
 * @returns 非缺陷 problem 按诊断顺序展示级别、阶段、来源及五段：对象、规则、实际与期望
 * （同一行）、后果、下一步。对象按原键值顺序显示，空对象显示“全局”，expected=null
 * 不显示期望；无诊断时显示服务端 detail 和编号。程序缺陷折叠时只显示 detail 和 error_id，
 * 不显示诊断/栈；展开后没有 loadDetails 时显示“请按错误编号在运行日志中查询完整报错。”；
 * 有回调时显示加载提示、返回的纯文本或固定“完整报错暂不可用，请按编号查询运行日志。”。
 * unavailable 只显示适配层提供的固定文案及可选编号，不提供完整报错展开按钮。
 * 所有服务端文字及详情均按 React 文本渲染，不执行 HTML；组件不自行拼接报错原因。
 * @throws 无。详情回调的同步异常或 Promise 拒绝都转成固定提示，不显示异常原文。
 * @sideEffects 默认不发请求、不改 URL/存储。仅用户首次展开缺陷详情且提供回调时调用一次；
 * 同编号折叠再展开复用本次挂载的成功结果或失败提示，不轮询、不自动重试。
 * 卸载、编号或回调变化时取消旧请求并清空详情，忽略迟到结果；新编号重新从折叠态开始。
 * @timeSemantics 详情请求上限使用 ERROR_DETAILS_TIMEOUT_MS（5000 毫秒），超时取消并显示固定失败提示；
 * 完成、切换或卸载时清理计时器；本次挂载之外不缓存。其他展示同步，无额外轮询。
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 骨架函数体只允许抛错；派工 B 使用 props 后删除此豁免。
export function DiagnosticCard(props: DiagnosticCardProps): ReactElement {
  throw new Error("未实现");
}
