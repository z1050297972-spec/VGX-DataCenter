// 第 6 张演示：两个隔离浏览器上下文，管理员停用成员后成员切回窗口被踢回登录页。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-demo-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9333", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9333/json/version")).json(); break; } catch { await sleep(200); } }
const ws = new WebSocket(ver.webSocketDebuggerUrl); await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map();
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
const send = (method, params = {}, sessionId) => new Promise((res, rej) => { const i = ++id; pending.set(i, (d) => (d.error ? rej(new Error(method + " " + JSON.stringify(d.error))) : res(d.result))); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
async function page() {
  const { browserContextId } = await send("Target.createBrowserContext");
  const { targetId } = await send("Target.createTarget", { url: "about:blank", browserContextId });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Page.enable", {}, sessionId); await send("Runtime.enable", {}, sessionId);
  const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }, sessionId); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400)); return r.result.value; };
  return {
    ev,
    go: async (path) => { await send("Page.navigate", { url: BASE + path }, sessionId); await sleep(1500); },
    shot: async (name) => { const { data } = await send("Page.captureScreenshot", { format: "png" }, sessionId); writeFileSync(`${OUT}/${name}.png`, Buffer.from(data, "base64")); },
    wait: async (expr, ms = 8000) => { for (let t = 0; t < ms; t += 200) { if (await ev(expr)) return true; await sleep(200); } throw new Error("timeout: " + expr + " @ " + (await ev("location.href")) + " :: " + (await ev("document.body.innerText.slice(0,300)"))); },
    front: () => send("Page.bringToFront", {}, sessionId),
  };
}
const H = `
window.__fill = (name, value) => { const el = [...document.querySelectorAll('input')].find(e => e.id === name || e.id.endsWith('_' + name)); if (!el) throw new Error('no input ' + name); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; el.focus(); set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); };
window.__click = (text, scope) => { const root = scope ? [...document.querySelectorAll(scope)].pop() : document; const b = [...root.querySelectorAll('button')].filter(b => (b.getAttribute('aria-label') || b.innerText.replace(/\\s/g,'')) === text && !b.disabled).pop(); if (!b) throw new Error('no button ' + text); b.click(); };`;
const log = (...a) => console.log(...a);
try {
  const admin = await page(); const member = await page();
  await admin.go("/"); await admin.wait("location.pathname === '/login'"); log("admin 未登录 → /login");
  await admin.ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await admin.wait("location.pathname === '/'"); log("admin 登录成功");
  await admin.go("/accounts"); await admin.wait("document.body.innerText.includes('账号管理')");
  await admin.ev(H + "__click('新建账号')"); await sleep(500);
  await admin.ev(H + "__fill('login_name','member1'); __fill('display_name','成员一'); __fill('password','Member-pass-2026!'); __click('保存账号')");
  await admin.wait("document.body.innerText.includes('member1')"); log("新建成员 member1"); await sleep(500); await admin.shot("final-demo-1-admin-created");
  await member.go("/login"); await member.ev(H + "__fill('login_name','member1'); __fill('password','Member-pass-2026!'); __click('登录')");
  await member.wait("location.pathname === '/change-password'"); log("member 首次登录被要求改口令");
  await member.ev(H + "__fill('current_password','Member-pass-2026!'); __fill('new_password','Member-new-2026!'); __fill('confirmation','Member-new-2026!'); __click('保存口令')");
  await member.wait("location.pathname === '/'"); log("member 改口令后进入首页"); await member.shot("final-demo-2-member-home");
  log("member /api/auth/me =", await member.ev("fetch('/api/auth/me').then(r => r.status)"));
  await admin.front(); await admin.ev(H + "__click('停用', 'tr:has(td) ' ) ");
  await sleep(500); await admin.ev(H + "(() => { const ok = [...document.querySelectorAll('.ant-modal-confirm-btns button, .ant-modal-footer button')].pop(); if (!ok) throw new Error('no confirm'); ok.click(); })()");
  await admin.wait("[...document.querySelectorAll('tr')].some(r => r.innerText.includes('member1') && r.innerText.includes('启用') && !r.innerText.includes('停用'))"); log("admin 停用 member1"); await admin.shot("final-demo-3-admin-disabled");
  await member.front(); await member.ev("document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('focus'))");
  await member.wait("location.pathname === '/login'"); log("member 切回窗口 → 被踢回", await member.ev("location.pathname + location.search"));
  await member.shot("final-demo-4-member-kicked");
  log("DEMO PASS");
} catch (e) { log("DEMO FAIL", e.message); process.exitCode = 1; }
finally { ws.close(); chrome.kill("SIGTERM"); }
