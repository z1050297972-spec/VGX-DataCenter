// M1-08 创建预览与确认部件；只展示保存的计划投影，不在前端重算差异或编号。
import type { ReactElement } from "react";
import type { CreationPreview, QueuedNavigationJob } from "../api/datasetCreation";
import type { RequestFailureView } from "../api/problems";

/** 预览审阅组件输入。 */
export interface CreationReviewProps {
  /** 成功预览，report.creation 必须非空；缺失时不允许确认。 */
  preview: CreationPreview;
  /** 写入提交请求在途时为 true，防止重复点击。 */
  pending: boolean;
  /** 用户看过差异后打开确认流程，先刷新同数据集排队提醒。 */
  onConfirm: () => void;
  /** 返回表单编辑并使本预览确认资格失效。 */
  onEdit: () => void;
}

/**
 * 展示将写文件、链接、数据块、根变化及按格式入口，并请求明确确认。
 * @param _props - 保存的预览、pending 和确认/编辑回调。
 * @returns 操作、预计编号、参数、完整差异路径、检查范围及 notices；noop 明确显示已经是这样了。
 * @throws 无；不合约预览禁用确认并由页面给出诊断。
 * @sideEffects 仅发出 onConfirm/onEdit；不把文件正文放入页面，不运行写入作业。
 * @timeSemantics created_at 使用 formatDateTime 显示浏览器本地时区；确认中的按钮禁用。
 */
export function CreationReview(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 保留完整调用契约；读取参数后移除此豁免。
  _props: CreationReviewProps,
): ReactElement {
  throw new Error("NotImplementedError");
}

/** 排队提醒的显式确认输入。 */
export interface CreationQueueWarningProps {
  /** 当前同数据集排队写作业，按编号升序；展示对应 /jobs/$jobId 链接。 */
  jobs: QueuedNavigationJob[];
  /** POST 进行中为 true，禁用继续提交。 */
  pending: boolean;
  /** 明确确认当前看到的编号；新排队编号出现时必须再次提示。 */
  onAcknowledge: (jobIds: string[]) => void;
  /** 取消确认，保留可编辑表单。 */
  onCancel: () => void;
}

/**
 * 提醒已有排队作业将修改相同数据集。
 * @param _props - 当前排队列表、请求状态及明确确认/取消回调。
 * @returns 提醒与作业链接；说明可能冲突，提供继续提交和返回编辑。
 * @throws 无。
 * @sideEffects 只发出用户实际看到的编号，不用通配确认跳过后续新提醒。
 * @timeSemantics 反映提交前队列快照，不保证随后无新作业；最终冲突由 worker L12 校验。
 */
export function CreationQueueWarning(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 保留完整调用契约；读取参数后移除此豁免。
  _props: CreationQueueWarningProps,
): ReactElement {
  throw new Error("NotImplementedError");
}

/** 冲突反馈不复制服务端诊断协议。 */
export interface CreationConflictProps {
  /** HTTP 或写作业中的统一冲突诊断，包含对象、实际、期望及下一步。 */
  failure: RequestFailureView;
  /** 丢弃旧预览确认资格，回到当前参数重新预览。 */
  onPreviewAgain: () => void;
}

/**
 * 显示预览后导航状态变化的差异与重新预览入口。
 * @param _props - 服务端冲突诊断和回到预览的回调。
 * @returns 复用 DiagnosticCard 的差异展示，提示本次冲突一行未写。
 * @throws 无。
 * @sideEffects 点击后触发 onPreviewAgain，不自动重提旧计划。
 * @timeSemantics 冲突是写锁内复核结果；重新预览生成新的状态与编号观察。
 */
export function CreationConflict(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 保留完整调用契约；读取参数后移除此豁免。
  _props: CreationConflictProps,
): ReactElement {
  throw new Error("NotImplementedError");
}
