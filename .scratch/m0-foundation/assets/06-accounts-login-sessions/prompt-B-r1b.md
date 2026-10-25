第 1 轮补充（同一轮，演示时发现的）。上面五条处理完以后接着做这一条，最后只跑一次 `make check`。

**阻塞：真实浏览器里前端调不通任何接口。** `src/web/src/api/client.ts` 的 `defaultFetch` 直接等于全局 `fetch`，`src/web/src/api/accounts.ts` 的 `createAccountClient` 以 `options.fetchImpl(...args)` 的方法形式调用它，`this` 是 `options` 而不是 `window`。Chrome 抛 `TypeError: Failed to execute 'fetch' on 'Window': Illegal invocation`，页面一打开就显示"请求失败，请检查网络"。测试全部注入了替身，所以没有测出来。

要做的：
1. 让默认传输不依赖调用方式，例如 `defaultFetch` 改成在调用时才读全局 `fetch` 的函数（`(...args) => fetch(...args)`）。`accounts.ts` 那处调用也改成不带接收者的调用。
2. 补一条回归测试，先红后绿：用 `vi.stubGlobal` 换一个在 `this` 不是 `undefined` 或 `globalThis` 时抛 `TypeError` 的假 `fetch`（模拟浏览器的检查），通过 `defaultFetch` 和 `createAccountClient` 走一次真实调用路径，断言没有抛错、请求确实发出。测试结束恢复全局。改之前先用这条测试看到红。
3. 搜一遍前端，看还有没有别处把浏览器原生函数（`fetch`、`setTimeout` 之类）存进对象、再以方法形式调用。有就一并修，并在最终回复里列出。

演示我在沙箱外复核：验收第 11 条全流程（管理员建成员，成员首次登录改口令，管理员停用，成员切回窗口被踢回登录页），用临时补丁已经跑通。

另外：你在 `/tmp/rdp-accounts-review-r1`（以及任何 `/tmp/rdp-*`）建的试验文件，交付前删掉，并在最终回复里写明。
