# /code-review：M0-04 r1-done（快照 80adc5b，只看 r1 → r1-done 的增量）

修复轮的两轴评审，由一个只读子 agent 在检出 `refs/rdp/m0-04/r1-done` 的探针工作目录里做；原文整理如下。

## Standards
1. **违反 CODING_STANDARDS 4.2/4.4（注释过期）**：`tests/test_api_errors.py:753` 的 docstring 还写着"验证契约：派工B每个已知API路由……"。修复清单第 3 条要求在整个 diff 里再搜一遍，这一处漏掉了。
2. **判断（4.4 注释位置）**：`problems.ts` 新写的"修改规范表时须同步更新此运行时校验映射"放在了 `requestId` 正则的上方，不在 `statusTable` 的上方。
3. **判断（第 7 节惯例）**：三个新写或重写的测试，docstring 不以"验证契约："开头，和同文件的其他测试不统一。
4. 其余没问题：`ALLOWED_HTTP_STATUSES` 是 `Final` 加只读映射，注释写了以 6.2 为准；logger 用 `__name__`，放在 import 之后。

## Spec
第 1、2、4、5、6、7 条 done。第 3 条 partial：`tests/test_api_errors.py:753` 还留着"派工B"。没有回归，也没有修复清单以外的改动。子 agent 另外核实过：FastAPI 的 `str(RequestValidationError)` 会带出原值，`hide_input_in_errors` 挡不住，所以第 7 条的测试确实能抓到"格式化了原异常"这种回归。

**合计**：Standards 1 条违规、2 条判断；Spec 1 条 partial。最重的都是 `test_api_errors.py:753` 这一行。
