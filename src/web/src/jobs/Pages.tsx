// 作业页面契约（08）：Ant Design 与统一 DiagnosticCard；不直接 fetch、不计算后端结果。
import type { ReactElement } from "react";

/**
 * 显示所有提交人的作业列表及可分享状态筛选。
 * @returns 列表、状态筛选、游标翻页和提交示例入口；九种显示状态遵守 jobStatusLabel。
 * @throws 无；无效筛选显示“作业筛选参数不合法”，请求错误由 DiagnosticCard 显示。
 * @sideEffects 经真实 /jobs Router 的 useSearch/useNavigate 读取和更新 typed search；筛选改变清 cursor，无效值不发列表请求。
 * @timeSemantics 合法列表每 JOB_POLL_INTERVAL_MS 轮询，离页取消，无自动重试；UTC 时刻仅显示时转浏览器本地。
 */
export function JobsPage(): ReactElement {
  throw new Error("未实现");
}

/**
 * 显示一个作业的状态、进度、摘要、诊断和控制按钮。
 * @returns /jobs/$jobId 的详情；展示“阶段 2/4 · 名称”、已知总数进度条或未知总数已处理量、独立计数、已用时间、速度/剩余、日志最后几十行和 DiagnosticCard；取消/中断无结果仍保留进度。
 * @throws 无；坏编号、404、409 与其他错误用统一诊断，不在页面拼接服务器失败信息。
 * @sideEffects 调 useJob/useJobLog；queued/running 可取消，cancelling 禁用取消，终态可重提；任意账号均可操作；显示重新提交自链接和历史名字删除标记，不输出工具 HTML。
 * @timeSemantics 进行中每秒轮询，终态取最后日志后停止；速度最近 10 秒、样本不足不显示，未知总数不显示百分比/剩余；已用时以服务器 elapsed_s 加本地单调增量，终态使用冻结摘要。
 */
export function JobDetailPage(): ReactElement {
  throw new Error("未实现");
}

/**
 * 用类型化表单提交示例数数作业。
 * @returns 总步数、毫秒间隔、失败步、警告步和整体中止步的 Ant Design 表单，整数范围来自生成模型契约。
 * @throws 无；字段错误保留输入，服务错误由 DiagnosticCard 展示。
 * @sideEffects 经 useSubmitCountJob POST，成功进入新详情；所有登录账号可见，不发送操作者声明、不直接读 cookie。
 * @timeSemantics 提交期间禁用重复操作，10 秒超时不宣称回滚，不自动重试；离页取消请求。
 */
export function SubmitCountJobPage(): ReactElement {
  throw new Error("未实现");
}

/**
 * 在每个已登录页面顶部提示 worker 离线。
 * @returns online=false 显示“worker 没在运行”，重启心跳后消失；首次加载不误报，查询失败显示统一诊断；不按管理员隐藏。
 * @throws 无；网络或服务器故障由 DiagnosticCard 展示，不伪装离线。
 * @sideEffects 由 AccountLayout 挂载并共享 useWorkerStatus；登录页、身份未知及必须改口令时不发 worker 请求。
 * @timeSemantics 每秒查询服务端 15 秒阈值判定，作业终态不影响横幅；卸载/登出停止查询并清缓存。
 */
export function WorkerStatusBanner(): ReactElement {
  throw new Error("未实现");
}
