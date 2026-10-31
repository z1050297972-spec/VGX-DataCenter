// 轻量创建入口；不导入创建页面，使详情页与主入口保持按路由拆包。
import type { ReactElement } from "react";
import { Button } from "antd";
import { useNavigate } from "@tanstack/react-router";

/** 数据集详情中的建链入口属性。 */
export interface CreateLinkEntryProps {
  /** 已知永久编号；身份未知时为 null，不能建链。 */
  datasetId: string | null;
}
/**
 * 从当前数据集详情进入建链页。
 * @param props - 当前数据集永久编号。
 * @returns 带固定 aria-label 的入口按钮。
 * @throws 无。
 * @sideEffects 点击只导航并预选数据集，不提交作业。
 * @timeSemantics 同步导航；参数表单在下一页初始化。
 */
export function CreateLinkEntry(props: CreateLinkEntryProps): ReactElement {
  const navigate = useNavigate();
  return (
    <Button
      aria-label="建链"
      disabled={!props.datasetId}
      onClick={() => {
        if (props.datasetId)
          void navigate({ to: "/datasets/links/new", search: { dataset_id: props.datasetId } });
      }}
    >
      建链
    </Button>
  );
}
/**
 * 从数据集页面上方进入新增数据集页。
 * @returns 所有成员可用的新增按钮。
 * @throws 无。
 * @sideEffects 仅导航到独立创建路由，不改变已有筛选缓存。
 * @timeSemantics 同步导航，不发写请求。
 */
export function CreateDatasetEntry(): ReactElement {
  const navigate = useNavigate();
  return (
    <Button
      type="primary"
      aria-label="新增数据集"
      onClick={() => {
        void navigate({ to: "/datasets/new", search: {} });
      }}
    >
      新增数据集
    </Button>
  );
}
