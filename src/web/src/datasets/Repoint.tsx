import "./repoint.css";
// M1-09 详情改指向表单：默认目标来自服务端链接，修改参数立即丢弃旧预览。
import { useState, type ReactElement } from "react";
import { Alert, Button, Input, Select, Typography } from "antd";
import type { DatasetDetail } from "../api/datasets";
import { previewRepoint, type RepointInput } from "../api/navigationWrites";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { useJobAction } from "../jobs/_actions";
import { useRecoveryBlock } from "../navigation/queries";
import { recoveryReason } from "../navwrites/recoveryGate";
import { useDatasetDetail } from "./queries";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { NavigationConfirmation } from "../navwrites/Confirmation";
import { NavigationDifferences, PreviewStatus, useNavigationPreview } from "../navwrites/Preview";

/** 改指向表单的服务端详情。 */
interface RepointProps {
  /** 编号、当前入口和已有链接目标；不能由用户声明操作者。 */ detail: DatasetDetail;
}
/**
 * 在详情页开启单个数据集的改指向流程。
 * @param props - 当前入口的现场详情。
 * @returns antd 前缀表单与预览，身份或数据集变化后重置；链接目标始终取规范入口。
 * @throws 无；读取错误由统一诊断显示。
 * @sideEffects 按格式入口会额外读取按任务规范入口详情；用户点击才提交 worker 预览，表单参数仅留在内存。
 * @timeSemantics 恢复状态每秒核对，预览轮询至终态；离页取消请求。
 */
export function RepointEditor(props: RepointProps): ReactElement {
  const account = useCurrentAccount();
  const canonicalPath = props.detail.canonical_entry_path ?? props.detail.entry.entry_path;
  const canonical = useDatasetDetail(canonicalPath);
  const links =
    canonicalPath === props.detail.entry.entry_path ? props.detail.links : canonical.data?.links;
  if (!links) {
    return (
      <section className="navigation-write" aria-label="数据集改指向">
        {canonical.error ? (
          <DiagnosticCard failure={toFailureView(canonical.error)} />
        ) : (
          <Alert type="info" title="正在读取规范入口的链接目标" />
        )}
      </section>
    );
  }
  return (
    <RepointForm
      key={JSON.stringify([
        account.data?.account_id,
        props.detail.entry.dataset_id,
        props.detail.entry.entry_path,
      ])}
      detail={props.detail}
      links={links}
    />
  );
}

/** 表单的输入：当前入口详情及规范入口的链接。 */
interface FormProps extends RepointProps {
  /** 规范入口的链接，用于默认和候选旧前缀。 */ links: DatasetDetail["links"];
}
/** 前缀输入区的受控状态。 */
interface FieldsProps {
  /** 候选旧前缀。 */ targets: string[];
  /** 当前旧前缀。 */ old: string;
  /** 当前新前缀。 */ next: string;
  /** 任何输入变化：丢弃旧预览。 */ onChange: (old: string, next: string) => void;
}
function RepointFields({ targets, old, next, onChange }: FieldsProps): ReactElement {
  return (
    <>
      <label>
        现有链接目标
        <Select<string>
          aria-label="选择现有链接目标"
          className="repoint-select-full"
          value={targets.includes(old) ? old : undefined}
          options={targets.map((value) => ({ value, label: value }))}
          getPopupContainer={(trigger: HTMLElement) => trigger.parentElement ?? trigger}
          virtual={false}
          onChange={(value) => {
            onChange(value, next);
          }}
        />
      </label>
      <label>
        旧前缀
        <Input
          aria-label="旧前缀"
          value={old}
          onChange={(event) => {
            onChange(event.target.value, next);
          }}
        />
      </label>
      <label>
        新前缀
        <Input
          aria-label="新前缀"
          value={next}
          onChange={(event) => {
            onChange(old, event.target.value);
          }}
        />
      </label>
      <p>前缀须为不带结尾 / 的绝对路径；original_path 和来源.json 保持原值。</p>
    </>
  );
}
/**
 * 提交改指向预览并判断结果是否对应当前参数。
 * @param detail - 当前入口详情（提供数据集编号）。
 * @param old - 当前旧前缀。
 * @param next - 当前新前缀。
 * @returns 提交 mutation、预览查询、已保存预览及是否与当前参数一致。
 * @throws 无；错误留在 mutation.error。
 * @sideEffects 提交时 POST 预览作业，随后只读轮询。
 * @timeSemantics 同 RepointEditor；参数变化由调用者 reset，旧预览不再匹配。
 */
function useRepointPreview(detail: DatasetDetail, old: string, next: string) {
  const client = useAccountClient();
  const submit = useJobAction<RepointInput>(
    (payload, signal) => previewRepoint({ client, payload, signal }),
    false,
  );
  const query = useNavigationPreview(submit.data?.job_id);
  const preview = query.report.data;
  const matching =
    preview?.operation === "repoint_dataset" &&
    preview.preview_job_id === submit.data?.job_id &&
    preview.parameters.dataset_id === detail.entry.dataset_id &&
    preview.parameters.old_prefix === old &&
    preview.parameters.new_prefix === next;
  return { submit, query, preview, matching };
}
function RepointResults(props: {
  flow: ReturnType<typeof useRepointPreview>;
  allowed: boolean;
}): ReactElement {
  const { submit, query, preview, matching } = props.flow;
  return (
    <>
      {submit.error && <DiagnosticCard failure={toFailureView(submit.error)} />}
      <PreviewStatus {...query} />
      {preview && matching && (
        <>
          <NavigationDifferences preview={preview} />
          <NavigationConfirmation
            key={preview.preview_job_id}
            preview={preview}
            blocked={!props.allowed || submit.isPending}
          />
        </>
      )}
      {preview && !matching && <Alert type="error" title="预览与当前参数不一致，请重新预览" />}
    </>
  );
}
function RepointForm({ detail, links }: FormProps): ReactElement {
  const recovery = useRecoveryBlock();
  const reason = recoveryReason(recovery, "提交");
  const allowed = reason === null;
  const targets = [...new Set(links.map((link) => link.observed_target ?? link.source_path))];
  const [open, setOpen] = useState(false);
  const [old, setOld] = useState(targets[0] ?? "");
  const [next, setNext] = useState("");
  const flow = useRepointPreview(detail, old, next);
  const { submit } = flow;
  const datasetId = detail.entry.dataset_id;
  return (
    <section className="navigation-write" aria-label="数据集改指向">
      {reason && <Alert aria-label="导航写入限制" type="warning" title={reason} />}
      <Button
        aria-label="改指向"
        disabled={!allowed || !datasetId}
        onClick={() => {
          setOpen(true);
        }}
      >
        改指向
      </Button>
      {open && (
        <>
          <Typography.Title level={4}>改指向</Typography.Title>
          <RepointFields
            targets={targets}
            old={old}
            next={next}
            onChange={(nextOld, nextNew) => {
              setOld(nextOld);
              setNext(nextNew);
              submit.reset();
            }}
          />
          <Button
            aria-label="预览改指向"
            loading={submit.isPending}
            disabled={!allowed || !old || !next || submit.isPending}
            onClick={() => {
              if (allowed && datasetId) {
                submit.reset();
                submit.mutate({ dataset_id: datasetId, old_prefix: old, new_prefix: next });
              }
            }}
          >
            预览改指向
          </Button>
          <RepointResults flow={flow} allowed={allowed} />
        </>
      )}
    </section>
  );
}
