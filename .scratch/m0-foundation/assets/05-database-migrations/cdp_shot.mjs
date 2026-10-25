// 演示截图：用 Chrome DevTools 协议打开页面、可选地点击一个按钮、等待文字出现后截图。
// 用法：node cdp_shot.mjs <调试端口> <页面地址> <输出 png> [按钮文字] [等待出现的文字]
// 只用 Node 22 自带的 fetch 和 WebSocket，不装任何依赖。
import { writeFileSync } from "node:fs";
const [port, url, out, button, waitText] = process.argv.slice(2);
const target = await (await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, { method: "PUT" })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let seq = 0;
const pending = new Map();
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
});
const send = (method, params = {}) => new Promise((r) => { const id = ++seq; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
const evaluate = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true })).result?.result?.value;
const waitFor = async (text, ms = 10000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (await evaluate(`document.body && document.body.innerText.includes(${JSON.stringify(text)})`)) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
};
await send("Emulation.setDeviceMetricsOverride", { width: 1200, height: 1400, deviceScaleFactor: 1, mobile: false });
await waitFor("错误编号", 10000);
if (button) {
  const clicked = await evaluate(`(() => { const b = [...document.querySelectorAll("button")].find((x) => x.innerText.includes(${JSON.stringify(button)})); if (!b) return false; b.click(); return true; })()`);
  console.log(`点击「${button}」：${clicked}`);
}
if (waitText) console.log(`等到「${waitText}」：${await waitFor(waitText, 10000)}`);
const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
writeFileSync(out, Buffer.from(shot.result.data, "base64"));
console.log("页面文字：" + JSON.stringify((await evaluate("document.body.innerText")).slice(0, 1500)));
await send("Target.closeTarget", { targetId: target.id }).catch(() => {});
ws.close();
