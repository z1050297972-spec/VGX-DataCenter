批准修改 `tests/test_followups_cleanup.py`。不过这不只是改数量：main 的 M0 第 13 张 D2 规定"每个生产作业类型自己声明提交需要的角色。凡是写导航层、删除或清除数据、或者占用 GPU 的类型，都只允许管理员经通用接口提交；只读的扫描、统计类型，成员也可以提交"。按这条给 M2 的类型定角色：
- `download_staging_delete`（删暂存数据）→ `Role.ADMINISTRATOR`
- `download_ingest_apply`（入库写导航层）→ `Role.ADMINISTRATOR`
- `download`、`download_preview`、`download_staging_scan`、`download_ingest_preview` → `Role.MEMBER`

入库确认要和 M1 的"确认写入"（`nav_write_apply` 是管理员类型，但成员能经专用接口确认写入）保持一致：成员经 M2 的专用入库接口仍能确认入库；经通用 `/api/jobs` 直接提交 `download_ingest_apply` 时成员得 403。照 M1 专用接口的做法实现，不要另造一套授权。删暂存本来就要求管理员，声明角色后确认专用接口行为不变。

然后更新 `test_followups_cleanup.py` 的期望字典（加上这 6 个类型和角色，docstring 里的"14个"改成实际数量），补一条断言：成员经通用接口提交 `download_ingest_apply` 得 403。跑 `make check`（一份）全绿。不要 git add、不要提交。最终回复第一行写 `状态：全部完成` 或 `状态：未完成`，后面写改了什么和 `make check` 末尾输出原样。
