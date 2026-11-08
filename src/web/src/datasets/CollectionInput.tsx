// M3-03 采集信息的受控输入；候选沿用登记 API，所有改动交现有字段预览流程。
import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Select, Space } from "antd";
import { useAccountClient, useCurrentAccount } from "../accounts/runtime";
import { listRobots, listVocabulary } from "../api/collection";
import { DATASET_GC_TIME_MS, DATASET_STALE_TIME_MS } from "../api/datasets";
import type { CollectionValue, CollectionStatus } from "../api/collection";
import { DiagnosticCard } from "../DiagnosticCard";
import { toFailureView } from "../api/problems";
import { COLLECTION_STATUS_LABELS } from "./collectionLabels";

interface Props {
  /** 当前草稿；null 表示无采集信息。 */ value: CollectionValue | null;
  /** 编辑页基线，用于保留原来引用的停用项。 */ original: CollectionValue | null;
  /** 请求提交中或基线过期。 */ disabled: boolean;
  /** 将完整 collection 交回字段草稿。 */ onChange: (value: CollectionValue | null) => void;
  /** 选择方式时把对应来源交回会话，是否补齐由会话判断。 */ onOrigin?: (origin: string) => void;
}
// M3-03 约束：单个数据集最多使用 16 台机器人。
const MAX_COLLECTION_ROBOTS = 16;
/**
 * 编辑采集状态、方式、用途和机器人编号，保留原引用停用项。
 * @param props - 当前草稿、原值、禁用状态与草稿回调。
 * @returns antd 选择控件及独立候选加载诊断。
 * @throws 无；候选错误由统一诊断展示。
 * @sideEffects 读取机器人与采集词表；变更仅调用草稿回调，不直接写导航层。
 * @timeSemantics 查询按账号隔离，无轮询重试；卸载取消，离页清缓存。
 */
export function CollectionInput(props: Props): ReactElement {
  const { robots, vocabulary } = useCollectionCandidates();
  const value = props.value;
  return (
    <Space orientation="vertical" className="field-input">
      {[robots.error, vocabulary.error].map((error, index) =>
        error ? <DiagnosticCard key={index} failure={toFailureView(error)} /> : null,
      )}
      <label>
        采集状态
        <Select<CollectionStatus | "unlabeled">
          aria-label="采集状态"
          virtual={false}
          disabled={props.disabled}
          value={value?.status ?? "unlabeled"}
          options={[
            ...Object.entries(COLLECTION_STATUS_LABELS).map(([value, label]) => ({ value, label })),
            { value: "unlabeled", label: "无采集信息" },
          ]}
          onChange={(status) => {
            props.onChange(
              status === "unlabeled"
                ? null
                : { ...(value ?? { method_id: null, purpose_id: null, robot_ids: [] }), status },
            );
          }}
        />
      </label>
      {value && (
        <>
          <MethodReference {...props} value={value} robots={robots} vocabulary={vocabulary} />
          <PurposeReference {...props} value={value} robots={robots} vocabulary={vocabulary} />
          <RobotReference {...props} value={value} robots={robots} vocabulary={vocabulary} />
          <Alert
            type="info"
            title="选择采集方式时，未填写或为未知的数据来源会一并带出；可在数据来源中改回，预览会列出所有改动。"
          />
        </>
      )}
    </Space>
  );
}
// 停用项仅允许基线已有引用；缺失编号保留可见且不能新选，由服务端给出最终校验诊断。
function referenceOptions(
  items: { id: number; name: string; status: string }[] | undefined,
  original: number[],
  selected: number[],
) {
  const options = (items ?? [])
    .filter((item) => item.status === "active" || original.includes(item.id))
    .map((item) => ({
      value: item.id,
      label: `${item.name}${item.status === "retired" ? "（停用）" : ""}`,
      disabled: false,
    }));
  for (const id of selected) {
    if (!options.some((item) => item.value === id))
      options.push({ value: id, label: `未知编号 ${String(id)}`, disabled: true });
  }
  return options;
}

// 候选查询只在采集信息编辑控件挂载后启用，沿用登记页的账号缓存键。
function useCollectionCandidates() {
  const client = useAccountClient();
  const account = useCurrentAccount();
  const options = {
    retry: false,
    staleTime: DATASET_STALE_TIME_MS,
    gcTime: DATASET_GC_TIME_MS,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  } as const;
  const robots = useQuery({
    ...options,
    queryKey: ["robots", account.data?.account_id],
    queryFn: ({ signal }) => listRobots({ client, payload: undefined, signal }),
  });
  const vocabulary = useQuery({
    ...options,
    queryKey: ["collection-vocabulary", account.data?.account_id],
    queryFn: ({ signal }) => listVocabulary({ client, payload: undefined, signal }),
  });
  return { robots, vocabulary };
}

// 单选编号与多选编号统一交给候选保留规则。
function singleId(id: number | null | undefined): number[] {
  return id == null ? [] : [id];
}
type ReferencesProps = Props & { value: CollectionValue } & ReturnType<
    typeof useCollectionCandidates
  >;
// 方式和用途共享词表查询；机器人使用独立查询，任一失败不掩盖另一组诊断。
function MethodReference(props: ReferencesProps): ReactElement {
  const { value, vocabulary } = props;
  const methods = vocabulary.data?.methods.map((item) => ({
    id: item.id,
    name: `${item.name}（${item.data_origin}）`,
    status: item.status,
  }));
  return (
    <label>
      采集方式
      <Select<number>
        aria-label="采集方式"
        virtual={false}
        allowClear
        disabled={props.disabled || !vocabulary.data}
        loading={vocabulary.isPending}
        value={value.method_id ?? undefined}
        options={referenceOptions(
          methods,
          singleId(props.original?.method_id),
          singleId(value.method_id),
        )}
        onChange={(id: number | undefined) => {
          props.onChange({ ...value, method_id: id ?? null });
          const method = vocabulary.data?.methods.find((item) => item.id === id);
          if (method) props.onOrigin?.(method.data_origin);
        }}
      />
    </label>
  );
}
// 用途不联动数据来源，清空只写 purpose_id 为 null。
function PurposeReference(props: ReferencesProps): ReactElement {
  const { value, vocabulary } = props;
  return (
    <label>
      用途
      <Select<number>
        aria-label="用途"
        virtual={false}
        allowClear
        disabled={props.disabled || !vocabulary.data}
        loading={vocabulary.isPending}
        value={value.purpose_id ?? undefined}
        options={referenceOptions(
          vocabulary.data?.purposes,
          singleId(props.original?.purpose_id),
          singleId(value.purpose_id),
        )}
        onChange={(id: number | undefined) => {
          props.onChange({ ...value, purpose_id: id ?? null });
        }}
      />
    </label>
  );
}
// 机器人编号使用 antd 多选保序，数量上限沿用导航层契约。
function RobotReference(props: ReferencesProps): ReactElement {
  const { value, robots } = props;
  return (
    <label>
      机器人
      <Select<number[]>
        aria-label="机器人"
        virtual={false}
        allowClear
        mode="multiple"
        maxCount={MAX_COLLECTION_ROBOTS}
        disabled={props.disabled || !robots.data}
        loading={robots.isPending}
        value={value.robot_ids}
        options={referenceOptions(
          robots.data?.items.map((item) => ({ ...item, id: item.robot_id })),
          props.original?.robot_ids ?? [],
          value.robot_ids,
        )}
        onChange={(robot_ids) => {
          props.onChange({ ...value, robot_ids });
        }}
      />
    </label>
  );
}
