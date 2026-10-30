// M1-08 两种创建页面，复用数据集外壳、账号 Provider、Query 与第 07 张恢复失败提示。
// 参数表单留内存，URL 只定位 dataset_id/preview_job_id；实际结果使用已有作业页。
import type { ReactElement } from "react";

/**
 * 在 /datasets/links/new 为现有数据集填写参数、预览并确认建链。
 * @returns CreateLinkForm → CreationReview → 排队提醒确认 → /jobs/$jobId；预览失败保留参数。
 * @throws 无；请求失败使用 DiagnosticCard，冲突使用 CreationConflict 并提供重新预览。
 * @sideEffects 经 useCreationFlow 发出候选/列表/预览/确认请求，使用类型化 Router search 保存预选数据集与成功预览编号；页面不直调 fetch。
 * @timeSemantics 只轮询预览作业且终态停止，间隔 JOB_POLL_INTERVAL_MS；离页取消读请求，POST 不重试；入队后作业页接管轮询。
 */
export function CreateLinkPage(): ReactElement {
  throw new Error("NotImplementedError");
}

/**
 * 在 /datasets/new 填写新数据集、来源、第一链接并预览全套入口。
 * @returns CreateDatasetForm → 预计编号与全套预览 → 明确确认 → /jobs/$jobId；成功后可到两棵树查看。
 * @throws 无；坏 URL 显示可修正提示；缺元信息未选格式及编号冲突经统一诊断要求重新预览。
 * @sideEffects useCreationFlow 提交只读预览及确认，类型化 search 只保存预览编号；恢复失败沿用全局提示及 /navigation/recovery，允许提交后排队。
 * @timeSemantics 来源印记时刻由服务器提供，页面只显示本地时间；请求预算、缓存和终态停轮询沿用现有 jobs 常量。
 */
export function CreateDatasetPage(): ReactElement {
  throw new Error("NotImplementedError");
}
