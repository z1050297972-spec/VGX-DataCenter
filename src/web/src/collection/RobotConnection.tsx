// 连接检查只提交作业；公钥弹窗只读平台状态，安装命令交负责人手动执行。
import { useState, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Alert, Button, Modal, Space, Spin, Typography } from "antd";
import { useAccountClient } from "../accounts/runtime";
import { checkRobotConnection, getRobotSshPublicKey, type Robot } from "../api/collection";
import { toFailureView } from "../api/problems";
import { DiagnosticCard } from "../DiagnosticCard";
import { useRegistryAction } from "./shared";

interface ConnectionProps {
  /** 已登记的机器人；只将永久编号发给作业接口。 */
  robot: Robot;
}

/**
 * 提供每台机器人的检查按钮和可复制平台公钥。
 * @param props - 当前机器人登记快照，用于身份和标题展示。
 * @returns 检查按钮、公钥按钮以及只读弹窗。
 * @throws 无；请求失败统一显示 DiagnosticCard。
 * @sideEffects 点击后提交检查作业并进入详情，或读取公钥；复制由 antd 交浏览器处理。
 * @timeSemantics 不轮询、不重试；离页取消请求，单次 API 请求最多 10 秒。
 */
export function RobotConnection(props: ConnectionProps): ReactElement {
  const { robot } = props;
  const client = useAccountClient();
  const navigate = useNavigate();
  const action = useRegistryAction("robots");
  const [open, setOpen] = useState(false);
  const publicKey = useQuery({
    queryKey: ["robots", "ssh-public-key", robot.robot_id],
    queryFn: ({ signal }) => getRobotSshPublicKey({ client, signal, payload: robot.robot_id }),
    enabled: open,
    retry: false,
    gcTime: 0,
  });
  return (
    <Space vertical>
      <Space>
        <Button
          loading={action.isPending}
          onClick={() => {
            action.mutate(async (signal) => {
              const job = await checkRobotConnection({ client, signal, payload: robot.robot_id });
              if (!signal.aborted)
                await navigate({ to: "/jobs/$jobId", params: { jobId: job.job_id } });
            });
          }}
        >
          检查连接
        </Button>
        <Button
          onClick={() => {
            setOpen(true);
          }}
        >
          平台公钥
        </Button>
      </Space>
      {action.error && <DiagnosticCard failure={toFailureView(action.error)} />}
      <Modal
        open={open}
        title={`平台公钥 · ${robot.name}`}
        footer={null}
        onCancel={() => {
          setOpen(false);
        }}
      >
        {publicKey.isFetching && <Spin />}
        {publicKey.error && <DiagnosticCard failure={toFailureView(publicKey.error)} />}
        {publicKey.data && (
          <>
            {publicKey.data.public_key ? (
              <>
                <Typography.Paragraph copyable={{ tooltips: ["复制", "已复制"] }}>
                  {publicKey.data.public_key}
                </Typography.Paragraph>
                {publicKey.data.copy_command ? (
                  <>
                    <Typography.Paragraph>由负责人在工作站终端手动执行：</Typography.Paragraph>
                    <Typography.Paragraph copyable={{ tooltips: ["复制", "已复制"] }}>
                      {publicKey.data.copy_command}
                    </Typography.Paragraph>
                  </>
                ) : (
                  <Alert type="info" title="请先填写机器人的地址和 SSH 用户。" />
                )}
              </>
            ) : (
              <Alert
                type="info"
                title="平台公钥尚未生成。首次检查连接时由 worker 生成，之后可在这里复制。"
              />
            )}
            <Button
              onClick={() => {
                void publicKey.refetch();
              }}
            >
              刷新公钥
            </Button>
          </>
        )}
      </Modal>
    </Space>
  );
}
