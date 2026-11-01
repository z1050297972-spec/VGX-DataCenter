状态：未完成

已完成：

- 六个 M2 类型显式声明指定角色，期望字典更新为 20 个类型。
- 补测成员经通用接口提交 `download_ingest_apply` 返回 403。
- M1、M2 专用确认共用提交服务的确认选项，成员仍可确认；暂存删除仍要求管理员。
- 后端 `2757 passed`，OpenAPI、tsc 通过。未暂存、未提交。

检查停在监控页的静态内联样式。已请求允许将 `src/web/src/monitoring/Pages.tsx:148` 改为 SVG 原生宽高属性；该文件超出你原先限定的修改范围，尚未改动。

`make check` 末尾输出原样：

```text
[9/12] ESLint
cd src/web && node_modules/.bin/eslint . --max-warnings 0

/home/shawn/桌面/robot-data-platform.wt/m2-downloads/src/web/src/monitoring/Pages.tsx
  148:9  error  静态样式使用 CSS 类；运行时值须说明原因，见 CODING_STANDARDS 10.9。  no-restricted-syntax

✖ 1 problem (1 error, 0 warnings)

make: *** [Makefile:40: check] Error 1
```