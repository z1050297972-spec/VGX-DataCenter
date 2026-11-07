// M1.5-16 分类管理入口；候选与计数共用筛选缓存，不在浏览器重算导航层计划。
import { useState, type ReactElement } from "react";
import { Alert, Button, Modal, Table, Tabs, Tag, Typography } from "antd";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { useDatasetFilterOptions } from "./queries";
import { useRecoveryBlock } from "../navigation/queries";
import { recoveryReason } from "../navwrites/recoveryGate";
import { useJobAction } from "../jobs/_actions";
import {
  previewClassificationRemoval,
  type ClassificationRemoveParameters,
} from "../api/classificationRemove";
import { applyNavigationPreview } from "../api/dataOrigin";
import { FieldReview } from "./FieldReview";
import type { DatasetFilters } from "../api/datasets";

/**
 * 在数据中心打开场景和任务的统一管理入口。
 * @returns 登录账号可用的按钮及分类对话框。
 * @throws 无；读取失败由统一诊断显示。
 * @sideEffects 打开后读取候选与恢复状态；用户显式提交预览和确认，不修改 URL。
 * @timeSemantics 关闭即卸载；重开读取最新候选，草稿不跨打开周期保留。
 */
export function ClassificationManagementEntry(): ReactElement {
  const account = useCurrentAccount();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        onClick={() => {
          setOpen(true);
        }}
      >
        管理场景/任务
      </Button>
      <Modal
        title="管理场景/任务"
        open={open}
        footer={null}
        destroyOnHidden
        onCancel={() => {
          setOpen(false);
        }}
      >
        {open && <ClassificationForm key={account.data?.account_id} />}
      </Modal>
    </>
  );
}

function ClassificationForm(): ReactElement {
  const client = useAccountClient();
  const recovery = useRecoveryBlock();
  const reason = recoveryReason(recovery, "删除");
  const preview = useJobAction<ClassificationRemoveParameters>(
    (payload, signal) => previewClassificationRemoval({ client, payload, signal }),
    false,
  );
  const confirm = useJobAction<string>(
    (payload, signal) => applyNavigationPreview({ client, payload, signal }),
    { cardTitle: "删除场景/任务值" },
  );
  const busy = preview.isPending || confirm.isPending;
  const filters = useDatasetFilterOptions();
  const [kind, setKind] = useState<"scene" | "tasks">("scene");
  const rows = classificationRows(filters.data, kind);
  return (
    <>
      <Typography.Paragraph>
        删除会从所有使用它的数据集中去掉该值；内置词表项仍会保留。请先核对预览，再确认写入。
      </Typography.Paragraph>
      {reason && <Alert type="warning" title={reason} />}
      {[filters.error, recovery.error, preview.error, confirm.error].map((error, index) =>
        error ? <DiagnosticCard key={index} failure={toFailureView(error)} /> : null,
      )}
      <Tabs
        activeKey={kind}
        onChange={(key) => {
          preview.reset();
          confirm.reset();
          setKind(key === "scene" ? "scene" : "tasks");
        }}
        items={[
          { key: "scene", label: "场景", disabled: busy },
          { key: "tasks", label: "任务", disabled: busy },
        ]}
      />
      <Table
        rowKey="value"
        size="small"
        scroll={{ x: "max-content" }}
        loading={filters.isPending}
        dataSource={rows}
        columns={[
          { title: "名称", dataIndex: "name" },
          { title: "编码", dataIndex: "value" },
          { title: "使用的数据集数", dataIndex: "count" },
          {
            title: "是否内置词表",
            render: (_, row) => <Tag>{row.builtin ? "内置" : "自定义"}</Tag>,
          },
          {
            title: "操作",
            render: (_, row) => (
              <>
                <Button
                  danger
                  aria-label={`删除 ${row.name}`}
                  disabled={row.count === 0 || !!reason || busy || filters.isError}
                  onClick={() => {
                    confirm.reset();
                    preview.mutate({ kind, value: row.value });
                  }}
                >
                  删除
                </Button>
                {row.builtin && row.count === 0 && (
                  <Typography.Text type="secondary">内置词表项，没有数据集在用</Typography.Text>
                )}
              </>
            ),
          },
        ]}
      />
      {filters.isPending && <Alert type="info" title="正在读取分类候选" />}
      {preview.data && (
        <FieldReview
          key={preview.data.job_id}
          jobId={preview.data.job_id}
          allowed={!reason && !busy && !confirm.isError && !confirm.isSuccess}
          pending={confirm.isPending}
          onConfirm={(identifier) => {
            if (!reason && !busy && !confirm.isError && !confirm.isSuccess)
              confirm.mutate(identifier);
          }}
        />
      )}
    </>
  );
}

// 候选与词表分开提供，合并后才能同时显示自定义值及零计数的内置项。
function classificationRows(filters: DatasetFilters | undefined, kind: "scene" | "tasks") {
  if (!filters) return [];
  const vocabulary = kind === "scene" ? filters.scene_vocabulary : filters.task_vocabulary;
  const candidates = kind === "scene" ? filters.scenes : filters.tasks;
  // 内置零计数项也要保留；未标注是筛选哨兵，不是可以删除的分类值。
  const values = new Set([
    ...vocabulary.map((term) => term.code),
    ...candidates.map((item) => item.value),
  ]);
  return [...values]
    .filter((value) => value !== "unlabeled")
    .map((value) => {
      const term = vocabulary.find((item) => item.code === value);
      const candidate = candidates.find((item) => item.value === value);
      return {
        value,
        name: term?.name ?? candidate?.label ?? value,
        count: candidate?.count ?? 0,
        builtin: !!term,
      };
    });
}
