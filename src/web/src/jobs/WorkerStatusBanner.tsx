// 全站 worker 横幅（M0-08、M1-04）：独立于作业路由页面，避免鉴权外壳提前载入整页表格与表单。
import type { ReactElement } from "react";
import { Alert } from "antd";
import { useWorkerStatus } from "./queries";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";

/**
 * 在每个已登录页面顶部提示 worker 离线。
 * @returns online=false 显示“worker 没在运行”，重启心跳后消失；首次加载不误报，查询失败显示统一诊断；不按管理员隐藏。
 * @throws 无；网络或服务器故障由 DiagnosticCard 展示，不伪装离线。
 * @sideEffects 由 AccountLayout 挂载并共享 useWorkerStatus；登录页、身份未知及必须改密码时不发 worker 请求。
 * @timeSemantics 每秒查询服务端 15 秒阈值判定，作业终态不影响横幅；卸载/登出停止查询并清缓存。
 */
export function WorkerStatusBanner(): ReactElement {
  const query = useWorkerStatus();
  if (query.isError) return <DiagnosticCard failure={toFailureView(query.error)} />;
  if (query.data?.online === false) return <Alert type="warning" title="worker 没在运行" />;
  return <></>;
}
