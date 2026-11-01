"""下载计划领域：固定版本、预览和容量预检，不执行下载或写入存储根。

使用标准库 urllib、json 和 fnmatch；huggingface_hub 不满足跨进程续传与限速要求。
"""
