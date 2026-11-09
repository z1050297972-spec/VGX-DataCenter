"""M4.5 转换选择规则（领域层）；只消费成功预览快照，不访问数据盘或套默认选择。"""

from dataclasses import dataclass

from rdp.infra.db.validation import invalid_field
from rdp.jobs.cleaning.models import EpisodeReport, FileReport
from rdp.jobs.cleaning.records import CleaningPreview
from rdp.jobs.conversion.parameters import ConversionOptions
from rdp.jobs.errors import JobInputError


@dataclass(frozen=True)
class Selection:
    """工具输入与输出编号的同一份计划。

    Attributes:
        files: 未剔除文件，按 file_index 升序。
        episodes: 这些文件的全部保留段，按文件和段升序，尚未扣除手工剔除。
        excluded_indices: 需要 LeRobot 删除的产物 episode 编号，升序。
    """

    files: tuple[FileReport, ...]
    episodes: tuple[EpisodeReport, ...]
    excluded_indices: tuple[int, ...]


def select(preview: CleaningPreview, options: ConversionOptions) -> Selection:
    """统一校验最终选择并换算编号；HTTP 与执行器都使用这条规则。"""
    report = preview.report
    files = {item.file_index: item for item in report.files}
    episodes = {(item.file_index, item.segment_index): item for item in report.episodes}
    excluded_files = set(options.excluded_files)
    excluded_episodes = {
        (item.file_index, item.segment_index) for item in options.excluded_episodes
    }
    if (
        not excluded_files <= files.keys()
        or not excluded_episodes <= episodes.keys()
        or any(item.fatal_issues and key not in excluded_files for key, item in files.items())
        or any(key[0] in excluded_files for key in excluded_episodes)
        or len(excluded_files) != len(options.excluded_files)
        or len(excluded_episodes) != len(options.excluded_episodes)
    ):
        raise JobInputError(
            invalid_field(
                "excluded_files/excluded_episodes",
                "报告内不重复的身份，致命文件必须剔除，段不得属于已剔除文件",
            ).diagnostics
        )
    kept_files = tuple(files[key] for key in sorted(files) if key not in excluded_files)
    kept_episodes = tuple(episodes[key] for key in sorted(episodes) if key[0] not in excluded_files)
    if not kept_files or len(kept_episodes) <= len(excluded_episodes):
        raise JobInputError(
            invalid_field(
                "excluded_files/excluded_episodes", "至少保留一个文件和一个 episode"
            ).diagnostics
        )
    return Selection(
        kept_files,
        kept_episodes,
        tuple(
            index
            for index, episode in enumerate(kept_episodes)
            if (episode.file_index, episode.segment_index) in excluded_episodes
        ),
    )
