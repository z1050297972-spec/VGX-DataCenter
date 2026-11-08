// 登记页共用操作生命周期和行按钮；只负责即时数据库操作，不提交 worker 作业。
import { useEffect, useRef, type ReactElement } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Modal, Space, Tooltip } from "antd";
import { useAccountClient } from "../accounts/runtime";
import { changeRegistry } from "../api/collection";
import type { RegistryStatus, VocabularyKind } from "../api/collection";

/**
 * 执行登记写请求，完成后刷新本页列表。
 * @param queryKey - robots 或 collection-vocabulary 缓存键。
 * @returns 带取消生命周期和统一错误的 mutation。
 * @throws 无；写请求失败通过 error 返回。
 * @sideEffects 执行传入请求，成功失效对应列表及其候选缓存。
 * @timeSemantics 不重试；卸载取消请求，预算由 API 的 ACCOUNT_TIMEOUT_MS 控制。
 */
export function useRegistryAction(queryKey: string) {
  const cache = useQueryClient();
  const active = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      active.current?.abort();
    },
    [],
  );
  return useMutation({
    mutationFn: async (send: (signal: AbortSignal) => Promise<unknown>) => {
      const controller = new AbortController();
      active.current = controller;
      try {
        await send(controller.signal);
      } finally {
        if (active.current === controller) active.current = null;
      }
    },
    onSuccess: () => cache.invalidateQueries({ queryKey: [queryKey] }),
    retry: false,
    gcTime: 0,
  });
}

interface RowActionsProps {
  /** 当前词表或机器人登记。 */
  kind: "robots" | VocabularyKind;
  /** 平台分配的正整数编号。 */
  id: number;
  /** 对象名称，用于确认内容。 */
  name: string;
  /** 使用中或停用。 */
  status: RegistryStatus;
  /** 数据集引用数，非负整数。 */
  referenceCount: number;
  /** 当前页面写操作状态。 */
  action: ReturnType<typeof useRegistryAction>;
  /** 打开该行编辑表单。 */
  onEdit: () => void;
}
/**
 * 展示编辑、停用或恢复、删除；被引用的记录禁删。
 * @param props - 行身份、状态、引用数和本页操作上下文。
 * @returns antd 行按钮及停用和删除确认框。
 * @throws 无；请求失败保留在页面 mutation 中。
 * @sideEffects 用户确认后调用登记 API，恢复直接提交。
 * @timeSemantics 写操作期间禁用按钮，不轮询。
 */
export function RegistryRowActions(props: RowActionsProps): ReactElement {
  const client = useAccountClient();
  const [modal, holder] = Modal.useModal();
  function run(operation: "retire" | "restore" | "delete"): void {
    props.action.mutate((signal) =>
      changeRegistry({
        client,
        signal,
        payload: undefined,
        kind: props.kind,
        id: props.id,
        action: operation,
      }),
    );
  }
  function confirm(operation: "retire" | "delete"): void {
    modal.confirm({
      title: operation === "delete" ? "确认删除" : "确认停用",
      content: props.name,
      okText: "确认",
      cancelText: "取消",
      onOk: () => {
        run(operation);
      },
    });
  }
  return (
    <Space wrap>
      {holder}
      <Button
        aria-label={props.kind === "robots" ? "编辑" : "改名"}
        disabled={props.action.isPending}
        onClick={props.onEdit}
      >
        {props.kind === "robots" ? "编辑" : "改名"}
      </Button>
      <Button
        aria-label={props.status === "active" ? "停用" : "恢复"}
        disabled={props.action.isPending}
        onClick={() => {
          if (props.status === "active") confirm("retire");
          else run("restore");
        }}
      >
        {props.status === "active" ? "停用" : "恢复"}
      </Button>
      <Tooltip title={props.referenceCount > 0 ? "已被数据集引用，只能停用" : undefined}>
        <span>
          <Button
            danger
            aria-label="删除"
            disabled={props.referenceCount > 0 || props.action.isPending}
            onClick={() => {
              confirm("delete");
            }}
          >
            删除
          </Button>
        </span>
      </Tooltip>
    </Space>
  );
}
