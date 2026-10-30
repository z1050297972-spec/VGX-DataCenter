// 所有页面顶部的“写操作被挡住”提示；单独成文件，避免外壳把详情页和表格拖进主入口。
import type { ReactElement } from "react";
import { Alert } from "antd";
import { Link } from "@tanstack/react-router";
import { useRecoveryBlock } from "./queries";

/**
 * 在每个已登录页面顶部提示写导航层的作业被挡住。
 * @returns 有标记时显示醒目的错误提示和跳到详情的链接；没有标记、首次加载或查询失败时不显示（worker 提示另行报告服务故障）。
 * @throws 无。
 * @sideEffects 由 AccountLayout 挂载并共享 useRecoveryBlock；不发写请求。
 * @timeSemantics 约每秒轮询；管理员确认后下一次轮询或确认成功后立即消失。
 */
export function RecoveryBlockBanner(): ReactElement {
  const query = useRecoveryBlock();
  if (!query.data?.blocked) return <></>;
  return (
    <Alert
      type="error"
      showIcon
      title="导航层写操作已被挡住：上次写入中断后有对不上的项，需管理员处理"
      description={<Link to="/navigation/recovery">查看对不上的项</Link>}
    />
  );
}
