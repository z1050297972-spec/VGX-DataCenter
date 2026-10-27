// 调度与资源示例页面（09）；沿用 Ant Design/DiagnosticCard，展示只读数据库快照。
import type { ReactElement } from "react";

/**
 * 显示所有登录账号可见的只读调度页。
 * @returns /scheduling 的单一只读页面：每类上限和运行数、每张卡的可用/移出/未知状态、移出诊断及作业链接、写锁持有者、每日下次时刻及上次结果；空闲/从未提交有独立提示。
 * @throws 无；请求失败用 DiagnosticCard，不把故障伪装为资源空闲。
 * @sideEffects 调用 useScheduling，同时显示资源与每日计划，不添加页签或 URL 参数；不提供资源/并发配置修改操作。登录菜单增加“调度”入口，普通成员同样可见。
 * @timeSemantics 每秒轮询，离页停止；服务端 UTC 仅显示时转浏览器本地。worker 离线时注明“最后已保存状态”，到期而未提交显示等待 worker，不伪造下一天。
 */
export function SchedulingPage(): ReactElement {
  throw new Error("未实现");
}

/**
 * 提供资源演示的两种类型化提交表单。
 * @returns /jobs/resources 的占卡秒数表单及写锁期望值/暂停秒数表单；空期望值可提交，值不含文件路径。
 * @throws 无；范围/类型错误在字段提示，服务端故障交 DiagnosticCard，保留已填写值。
 * @sideEffects 分别调用 useSubmitGpuJob/useSubmitNavigationJob；提交期间禁用按钮，成功进入对应新详情。期望新值为成功写入作业的编号文本，页面说明可从上次详情取得。
 * @timeSemantics 只发一次 10 秒请求，不自动重试；GPU 等待可取消，锁内暂停和取消延后规则在表单说明中呈现。
 */
export function SubmitResourceJobsPage(): ReactElement {
  throw new Error("未实现");
}
