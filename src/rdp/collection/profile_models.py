"""RobotProfile 事实模型（领域层，ADR 0007、M5-01）。

复用 Pydantic 严格校验，不读取机器人、文件或工具配置；未知事实用缺省键表示，
不把未知目标当作无目标。取法只描述来源，不执行 JSON 路径或处理实时消息。
"""

from ipaddress import ip_address
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

type ProfileText = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
type PositiveCount = Annotated[int, Field(gt=0)]
type RateHz = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class _ProfileModel(BaseModel):
    """所有事实均拒绝未知字段和隐式标量转换，错误不回显原始输入。"""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)


class ReadinessCondition(_ProfileModel):
    """加入 ROS 图前的事实条件，不在读取时执行检查。

    Attributes:
        check: 平台封闭的只读检查类型；run_on_robot 仅作说明，不执行检查。
        value: address_present 为 IP 文本；udp_port_listening 为 1 至 65535 的整数端口号；
            process_running 为命令行中的固定文本；run_on_robot 不提供值。
        level: 不满足时的级别，error（默认）或 warning；说明性条件不影响结果。
        reason: 条件的原因和下一步，非空文本；不能包含凭据，仅展示而不作为命令执行。
    """

    check: Literal["address_present", "udp_port_listening", "process_running", "run_on_robot"]
    value: ProfileText | int | None = None
    level: Literal["error", "warning"] = "error"
    reason: ProfileText

    @model_validator(mode="after")
    def _check_value(self) -> Self:
        """按封闭检查类型校验事实，不允许把缺少参数当作就绪。"""
        if self.check == "run_on_robot":
            if self.value is not None:
                raise ValueError("run_on_robot 不接受 value")
        elif self.check == "udp_port_listening":
            if not isinstance(self.value, int) or not 1 <= self.value <= 65535:
                raise ValueError("udp_port_listening 的 value 必须为 1 至 65535 的整数端口号")
        elif not isinstance(self.value, str):
            raise ValueError("地址或进程检查必须提供非空文本 value")
        elif self.check == "address_present":
            try:
                ip_address(self.value)
            except ValueError:
                raise ValueError("address_present 的 value 必须为 IP 地址") from None
        return self


class RosGraph(_ProfileModel):
    """ROS 图的加入方式，仅保存事实，不执行 shell 或连接 DDS。

    Attributes:
        distro: ROS 发行版，非空文本。
        rmw: RMW 实现名称，非空文本。
        domain_id: DDS 域编号，非负整数；省略表示未知。
        discovery: 发现方式，非空文本。
        discovery_server: 发现服务器地址；该方式不用服务器时省略。
        participant: 参与者类型；发现方式未指定时省略。
        qos_subscribe: 订阅可靠性，BEST_EFFORT 或 RELIABLE。
        readiness: 按文件顺序检查的就绪条件，可为空。
    """

    distro: ProfileText
    rmw: ProfileText
    domain_id: int | None = Field(default=None, ge=0)
    discovery: ProfileText
    discovery_server: ProfileText | None = None
    participant: ProfileText | None = None
    qos_subscribe: Literal["BEST_EFFORT", "RELIABLE"]
    readiness: list[ReadinessCondition]


class JointSource(_ProfileModel):
    """一个关节组的数据来源，省略的事实等待补测。

    Attributes:
        topic: ROS 话题绝对名称，以 / 开头。
        message_type: 话题消息类型，非空文本；省略表示未知。
        extract: 数组取法，如 JointState.position 或 json:字段路径；
            也可用非空路径列表逐项提取标量，顺序等于关节顺序；省略表示未知。
        rate_hz: 标称频率，有限正数，单位 Hz；不是运行时最低频率保证。
        stamp: 时间戳来源，header 或 receive；省略表示未知。
        stamp_trusted: 时间戳是否可信，省略表示未确认；false 不替调用方选择对齐策略。
        may_be_silent: 已知在空闲时可能不发消息，默认 false，不代表存活保证。
    """

    topic: str = Field(pattern=r"^/\S+$")
    message_type: ProfileText | None = None
    extract: ProfileText | Annotated[list[ProfileText], Field(min_length=1)] | None = None
    rate_hz: RateHz | None = None
    stamp: Literal["header", "receive"] | None = None
    stamp_trusted: bool | None = None
    may_be_silent: bool = False

    @property
    def unknown_count(self) -> int:
        """来源中未确认的类型、取法、频率、时间戳来源和可信度数量，单位项，非负。"""
        return sum(
            value is None
            for value in (
                self.message_type,
                self.extract,
                self.rate_hz,
                self.stamp,
                self.stamp_trusted,
            )
        )


class NoTarget(_ProfileModel):
    """确认没有目标的组；不能用来表示目标尚未补测。

    Attributes:
        none: 只能为 true，表示事实上的无目标。
    """

    none: Literal[True]


class JointGroup(_ProfileModel):
    """目标与观测共享名字、顺序、维数和单位的关节组。

    Attributes:
        name: 组名，非空，同一 Profile 内唯一。
        joints: 按来源数组顺序排列的非空关节名列表；未知时省略。
        joint_count: 名字未知时记录的正整数维数，与 joints 二选一。
        unit: 位置值的物理单位；省略表示未知，不按数值猜测。
        observation: 必填的观测来源。
        target: 目标来源或明确的无目标；省略表示目标未知。
    """

    name: ProfileText
    joints: list[ProfileText] | None = Field(default=None, min_length=1)
    joint_count: PositiveCount | None = None
    unit: ProfileText | None = None
    observation: JointSource
    target: JointSource | NoTarget | None = None

    @model_validator(mode="after")
    def _dimension(self) -> Self:
        """维数必须明确；只在取法逐项列出标量时静态核对数量，不猜数组话题的长度。"""
        if (self.joints is None) == (self.joint_count is None):
            raise ValueError("joints 与 joint_count 必须且只能提供一项")
        if self.joints is not None:
            for name, source in (("observation", self.observation), ("target", self.target)):
                if (
                    isinstance(source, JointSource)
                    and isinstance(source.extract, list)
                    and len(source.extract) != len(self.joints)
                ):
                    raise ValueError(f"{name}.extract 标量路径数量必须等于 joints 数量")
        return self

    @property
    def unknown_count(self) -> int:
        """未知关节名记一项，未知单位和目标各记一项，再累加来源未知事实，单位项。"""
        target_unknown = (
            self.target.unknown_count
            if isinstance(self.target, JointSource)
            else int(self.target is None)
        )
        return (
            int(self.joints is None)
            + int(self.unit is None)
            + self.observation.unknown_count
            + target_unknown
        )


class ProfileCamera(_ProfileModel):
    """相机事实；话题与共享内存来源不同时指定，不访问对应地址或路径。

    Attributes:
        name: 相机名，非空，同一 Profile 内唯一。
        topic: 图像话题，以 / 开头；没有 ROS 图像话题时省略。
        source: 非 ROS 来源描述，如 shm:路径；具体来源未知时省略。
        message_type: ROS 消息类型；非 ROS 相机不适用。
        encoding: 原始或压缩编码；省略表示未知。
        resolution: [宽, 高]，两个正整数，单位像素；省略表示未知。
        rate_hz: 标称帧率，有限正数，单位 Hz；省略表示未知。
        stamp: 时间戳来源，header 或 receive；省略表示未知。
        stamp_trusted: 时间戳是否可信；省略表示未确认。
        trigger: 触发方式描述；省略表示未确认，不用于对齐。
        stereo_eye: 双目的 left 或 right；与 stereo_partner 同时提供，省略表示未声明双目。
        stereo_partner: 同一 Profile 内另一目的相机名；必须目别相反且相互指回。
    """

    name: ProfileText
    topic: str | None = Field(default=None, pattern=r"^/\S+$")
    source: ProfileText | None = None
    message_type: ProfileText | None = None
    encoding: ProfileText | None = None
    resolution: list[PositiveCount] | None = Field(default=None, min_length=2, max_length=2)
    rate_hz: RateHz | None = None
    stamp: Literal["header", "receive"] | None = None
    stamp_trusted: bool | None = None
    trigger: ProfileText | None = None
    stereo_eye: Literal["left", "right"] | None = None
    stereo_partner: ProfileText | None = None

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        """避免一个相机同时宣称 ROS 与非 ROS 两个来源。"""
        if self.topic is not None and self.source is not None:
            raise ValueError("topic 与 source 不能同时指定")
        return self

    @property
    def unknown_count(self) -> int:
        """相机来源缺失记一项，ROS 类型按需计数，再数未确认的图像和时序事实，单位项。"""
        return (
            int(self.topic is None and self.source is None)
            + int(self.topic is not None and self.message_type is None)
            + sum(
                value is None
                for value in (
                    self.encoding,
                    self.resolution,
                    self.rate_hz,
                    self.stamp,
                    self.stamp_trusted,
                    self.trigger,
                )
            )
        )


class RobotProfile(_ProfileModel):
    """按型号共用的版本化事实说明；不含单台机器人凭据或工具算法参数。

    Attributes:
        profile: 稳定标识，小写字母、数字、下划线或连字符，以字母开头。
        version: 说明档版本，正整数；更改事实后由评审升级。
        model: 与机器人登记和数据集 robot_model 相同的非空文字。
        robot_type_labels: 数据里的型号标签；省略表示未知，空列表表示确认没有标签。
        ros: ROS 图和就绪条件。
        joint_group: 按文件顺序的关节组，可为空。
        camera: 按文件顺序的相机，可为空。
    """

    profile: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    version: PositiveCount
    model: ProfileText
    robot_type_labels: list[ProfileText] | None = None
    ros: RosGraph
    joint_group: list[JointGroup]
    camera: list[ProfileCamera]

    @field_validator("joint_group", "camera")
    @classmethod
    def _unique_names(
        cls, value: list[JointGroup] | list[ProfileCamera]
    ) -> list[JointGroup] | list[ProfileCamera]:
        """组名和相机名各自唯一，保证调用方能够按名字稳定选取。"""
        if len({item.name for item in value}) != len(value):
            raise ValueError("name 不得重复")
        return value

    @model_validator(mode="after")
    def _stereo_pairs(self) -> Self:
        """双目必须是完整的互指关系，避免布局把未配对的相机误当右目隐藏。"""
        cameras = {camera.name: camera for camera in self.camera}
        for camera in self.camera:
            if camera.stereo_eye is None:
                if camera.stereo_partner is not None:
                    raise ValueError("双目 stereo_eye 与 stereo_partner 必须同时提供")
                continue
            partner = cameras.get(camera.stereo_partner or "")
            opposite_eye = "right" if camera.stereo_eye == "left" else "left"
            if (
                partner is None
                or partner.stereo_eye != opposite_eye
                or partner.stereo_partner != camera.name
            ):
                raise ValueError("双目伙伴必须在同一 Profile 中存在、目别相反且互相指回")
        return self

    @property
    def unknown_count(self) -> int:
        """未知事实总数，单位项；可选发现参数和无目标不计数，未确认的名字按组计一项。"""
        return (
            int(self.robot_type_labels is None)
            + int(self.ros.domain_id is None)
            + sum(group.unknown_count for group in self.joint_group)
            + sum(camera.unknown_count for camera in self.camera)
        )
