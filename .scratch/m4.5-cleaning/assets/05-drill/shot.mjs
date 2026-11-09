// M4.5 演练截图：用 curl 登录得到的会话 cookie 打开页面，整页截图。用法：node shot.mjs <base> <cookie文件> <输出目录> <名字=路径>...
import { spawn } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
const [base, cookieFile, out, ...pages] = process.argv.slice(2); mkdirSync(out, { recursive: true });
const cookies = readFileSync(cookieFile, "utf8").split("\n").map((l) => l.replace(/^#HttpOnly_/, "")).filter((l) => l && !l.startsWith("#")).map((l) => l.split("\t")).filter((f) => f.length >= 7);
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9345", "--no-first-run", "--hide-scrollbars", "--no-proxy-server", "--user-data-dir=" + out + "/../.chrome-profile-tmp", "about:blank"], { stdio: "ignore" });
await new Promise((r) => setTimeout(r, 2500));
const targets = await (await fetch("http://127.0.0.1:9345/json")).json();
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", (e) => { const m = JSON.parse(e.data); if (pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send("Page.enable"); await send("Network.enable");
for (const f of cookies) await send("Network.setCookie", { name: f[5], value: f[6], url: base, httpOnly: true });
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }] });
await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
for (const item of pages) {
  const [name, path] = item.split("=");
  await send("Page.navigate", { url: base + path });
  await new Promise((r) => setTimeout(r, 6000));
  const m = await send("Runtime.evaluate", { expression: "Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)", returnByValue: true });
  const h = Math.min(Number(m.result?.result?.value) || 900, 8000);
  const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width: 1440, height: h, scale: 1 } });
  if (r.result) writeFileSync(`${out}/${name}.png`, Buffer.from(r.result.data, "base64"));
  console.log("截图", name, r.result ? `ok ${h}px` : JSON.stringify(r.error));
}
ws.close(); chrome.kill();
