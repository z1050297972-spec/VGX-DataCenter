// M1.5-15 管理员回填入口；复用导航差异和字段预览确认，不在页面计算迁移计划。
import { useState, type ReactElement } from "react";
import { Alert, Button, Modal, Typography } from "antd";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { previewInformationBackfill } from "../api/informationBackfill";
import { applyNavigationPreview } from "../api/dataOrigin";
import { useJobAction } from "../jobs/_actions";
import { useRecoveryBlock } from "../navigation/queries";
import { recoveryReason } from "../navwrites/recoveryGate";
import { FieldReview } from "./FieldReview";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";

/**
 * 只向管理员显示全量回填的预览入口。
 * @returns 管理员按钮与按打开周期隔离的对话框，成员不显示入口。
 * @throws 无。
 * @sideEffects 打开后读取恢复门禁；预览和确认各由用户显式提交。
 * @timeSemantics 关闭即卸载草稿与等待，重开必须重新预览。
 */
export function InformationBackfillEntry(): ReactElement {
  const account = useCurrentAccount();
  const [open, setOpen] = useState(false);
  if (account.data?.role !== "administrator") return <></>;
  return (
    <>
      <Button
        onClick={() => {
          setOpen(true);
        }}
      >
        回填数据集信息
      </Button>
      <Modal
        title="回填数据集信息"
        open={open}
        footer={null}
        destroyOnHidden
        onCancel={() => {
          setOpen(false);
        }}
      >
        {open && <BackfillForm key={account.data.account_id} />}
      </Modal>
    </>
  );
}

function BackfillForm(): ReactElement {
  const client = useAccountClient();
  const recovery = useRecoveryBlock();
  const reason = recoveryReason(recovery, "回填");
  const preview = useJobAction<undefined>(
    (_payload, signal) => previewInformationBackfill({ client, payload: undefined, signal }),
    false,
  );
  const confirm = useJobAction<string>(
    (payload, signal) => applyNavigationPreview({ client, payload, signal }),
    { cardTitle: "回填数据集信息" },
  );
  const busy = preview.isPending || confirm.isPending;
  return (
    <>
      <Typography.Paragraph>
        覆盖全部数据集：仅补充缺失的顶层 FPS 和数据来源，并将来源文件升级为只存血缘的第 2 版。14
        项正文和机器人型号保持不变。请先核对预览，再确认写入。
      </Typography.Paragraph>
      {reason && <Alert type="warning" title={reason} />}
      {[recovery.error, preview.error, confirm.error].map((error, index) =>
        error ? <DiagnosticCard key={index} failure={toFailureView(error)} /> : null,
      )}
      <Button
        loading={preview.isPending}
        disabled={!!reason || busy}
        onClick={() => {
          confirm.reset();
          preview.mutate(undefined);
        }}
      >
        预览回填
      </Button>
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
