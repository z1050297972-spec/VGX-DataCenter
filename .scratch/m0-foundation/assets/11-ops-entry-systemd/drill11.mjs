// 验收 5 浏览器部分：照第 6–10 张演示的写法，用无头 Chrome 走一遍全过程并截图。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-drill11-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9341", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9341/json/version")).json(); break; } catch { await sleep(200); } }
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
    wait: async (expr, ms = 10000) => { for (let t = 0; t < ms; t += 200) { if (await ev(expr)) return true; await sleep(200); } throw new Error("timeout: " + expr + " @ " + (await ev("location.href")) + " :: " + (await ev("document.body.innerText.slice(0,300)"))); },
    front: () => send("Page.bringToFront", {}, sessionId),
  };
}
const H = `
window.__fill = (name, value) => { const el = [...document.querySelectorAll('input')].find(e => e.id === name || e.id.endsWith('_' + name)); if (!el) throw new Error('no input ' + name); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; el.focus(); set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); };
window.__click = (text, scope) => { const root = scope ? [...document.querySelectorAll(scope)].pop() : document; const b = [...root.querySelectorAll('button')].filter(b => (b.getAttribute('aria-label') || b.innerText.replace(/\\s/g,'')) === text && !b.disabled).pop(); if (!b) throw new Error('no button ' + text); b.click(); };`;
const log = (...a) => console.log(...a);
const rows = (p) => p.ev("[...document.querySelectorAll('.ant-table-tbody tr')].map(r => r.innerText.replace(/\\s+/g,' ')).filter(t => t && !t.includes('暂无数据'))");
const body = (p) => p.ev("document.body.innerText");
const st = (p) => p.ev("fetch('/api' + location.pathname).then(r=>r.json()).then(d=>d.state)");
async function waitState(p, want, ms) { const t = Date.now(); for (;;) { const s = await st(p); if (s === want) return; if (Date.now() - t > ms) throw new Error("state " + s + " != " + want); await sleep(400); } }
try {
  const admin = await page(); const member = await page();
  await admin.go("/"); await admin.wait("location.pathname === '/login'"); log("未登录访问首页 → /login");
  await admin.shot("drill-0-login");
  await admin.ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await admin.wait("location.pathname === '/'"); log("1. admin 登录成功");
  const version = await admin.ev("fetch('/api/version').then(r=>r.json()).then(d=>d.version)");
  await sleep(1000); log("   /api/version =", version, "| 页面底部含此版本:", (await body(admin)).includes(version));
  await admin.shot("drill-1-admin-home");
  await admin.go("/accounts"); await admin.wait("document.body.innerText.includes('账号管理')");
  await admin.ev(H + "__click('新建账号')"); await sleep(500);
  await admin.ev(H + "__fill('login_name','member1'); __fill('display_name','成员一'); __fill('password','Member-pass-2026!'); __click('保存账号')");
  await admin.wait("document.body.innerText.includes('member1')"); log("2. admin 新建成员 member1"); await sleep(500); await admin.shot("drill-2-member-created");
  await member.go("/login"); await member.ev(H + "__fill('login_name','member1'); __fill('password','Member-pass-2026!'); __click('登录')");
  await member.wait("location.pathname === '/change-password'"); log("3. member1 首次登录被要求改口令");
  await member.ev(H + "__fill('current_password','Member-pass-2026!'); __fill('new_password','Member-new-2026!'); __fill('confirmation','Member-new-2026!'); __click('保存口令')");
  await member.wait("location.pathname === '/'"); log("   member1 改口令后进入首页");
  await member.go("/jobs/new"); await member.wait("document.body.innerText.includes('提交示例作业') && !!document.querySelector('input')");
  await member.ev(H + "__fill('steps','10'); __fill('interval_ms','500');"); await sleep(300);
  await member.ev(H + "__click('提交作业')");
  await member.wait("/^\\/jobs\\/\\d+$/.test(location.pathname)"); const job = await member.ev("location.pathname"); log("4. member1 提交示例作业 →", job);
  const seen = new Set(); for (let t = 0; t < 40; t++) { const s = await st(member); seen.add(s); if (s === "completed") break; await sleep(500); }
  await waitState(member, "completed", 20000); await sleep(1500);
  log("   经历的状态:", JSON.stringify([...seen]));
  const detail = await member.ev(`fetch('/api${job}').then(r=>r.json())`);
  log("   作业结果:", JSON.stringify({ state: detail.state, result: detail.result, platform_version: detail.platform_version }));
  log("   作业日志:", (await member.ev(`fetch('/api${job}/log').then(r=>r.text())`)).slice(0, 600));
  await member.shot("drill-3-job-completed");
  await admin.front();
  await admin.go("/audit/operations"); await admin.wait("document.querySelectorAll('.ant-table-tbody tr').length > 0"); await sleep(800);
  log("5. 操作日志:", JSON.stringify(await rows(admin))); await admin.shot("drill-4-operations");
  await admin.go("/audit/logins"); await admin.wait("document.querySelectorAll('.ant-table-tbody tr').length > 0"); await sleep(800);
  log("   登录日志:", JSON.stringify(await rows(admin))); await admin.shot("drill-5-logins");
  await admin.go("/storage-roots"); await admin.wait("document.querySelectorAll('.ant-table-tbody tr').length >= 2", 15000); await sleep(800);
  log("6. 存储根:", JSON.stringify(await rows(admin)));
  log("   API:", JSON.stringify(await admin.ev("fetch('/api/storage-roots').then(r=>r.json())")));
  await admin.shot("drill-6-storage-roots");
  log("DRILL PASS");
} catch (e) { log("DRILL FAIL:", e.message); process.exitCode = 1; }
finally { chrome.kill("SIGKILL"); ws.close(); }
