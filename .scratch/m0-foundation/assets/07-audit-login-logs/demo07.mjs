// 第 7 张演示：两个账号做操作、输错口令，在两个日志页筛出记录；删除成员后显示（已删除）。
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const [, , BASE, OUT] = process.argv;
const profile = mkdtempSync(tmpdir() + "/rdp-demo7-chrome-");
const chrome = spawn("google-chrome", ["--headless=new", "--remote-debugging-port=9335", `--user-data-dir=${profile}`, "--window-size=1280,900", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ver; for (let i = 0; i < 50; i++) { try { ver = await (await fetch("http://127.0.0.1:9335/json/version")).json(); break; } catch { await sleep(200); } }
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

const text = (p) => p.ev("document.body.innerText");
const rows = (p) => p.ev("[...document.querySelectorAll('.ant-table-tbody tr')].map(r => r.innerText.replace(/\\s+/g,' ')).filter(t => t && !t.includes('暂无数据'))");
try {
  const admin = await page(); const member = await page();
  await admin.go("/login"); await admin.ev(H + "__fill('login_name','admin'); __fill('password','Admin-pass-2026!'); __click('登录')");
  await admin.wait("location.pathname === '/'"); log("admin 登录");
  await admin.go("/accounts"); await admin.wait("document.body.innerText.includes('账号管理')");
  await admin.ev(H + "__click('新建账号')"); await sleep(500);
  await admin.ev(H + "__fill('login_name','member1'); __fill('display_name','成员一'); __fill('password','Member-pass-2026!'); __click('保存账号')");
  await admin.wait("document.body.innerText.includes('member1')"); log("admin 新建 member1");
  await member.go("/login"); await member.ev(H + "__fill('login_name','member1'); __fill('password','wrong-pass-123'); __click('登录')");
  await member.wait("document.body.innerText.includes('账号或口令错误')"); log("member 输错一次口令");
  await member.ev(H + "__fill('login_name','member1'); __fill('password','Member-pass-2026!'); __click('登录')");
  await member.wait("location.pathname === '/change-password'");
  await member.ev(H + "__fill('current_password','Member-pass-2026!'); __fill('new_password','Member-new-2026!'); __fill('confirmation','Member-new-2026!'); __click('保存口令')");
  await member.wait("location.pathname === '/'"); log("member 首次登录改口令");
  await member.go("/audit/operations"); await sleep(1000);
  log("member 打开操作日志页 →", await member.ev("location.pathname + location.search"), "| 页面含日志表:", await member.ev("!!document.querySelector('.ant-table')"));
  log("member GET /api/audit/operations =", await member.ev("fetch('/api/audit/operations').then(r => r.status)"), "/api/audit/logins =", await member.ev("fetch('/api/audit/logins').then(r => r.status)"));
  await member.shot("demo7-1-member-denied");
  const anon = await page(); await anon.go("/login"); await anon.ev(H + "__fill('login_name','nobody'); __fill('password','Typed-secret-999'); __click('登录')"); await sleep(1500); log("未知账号 nobody 登录一次");
  await admin.go("/audit/operations?target_account_id=2"); await admin.wait("document.querySelectorAll('.ant-table-tbody tr').length > 0 && !document.body.innerText.includes('加载')");
  await sleep(800); log("操作日志 对象=2:", JSON.stringify(await rows(admin))); await admin.shot("demo7-2-ops-target");
  await admin.go("/audit/logins?account_id=2"); await sleep(1500); log("登录日志 账号=2:", JSON.stringify(await rows(admin)));
  await admin.go("/audit/logins?result=account_missing"); await sleep(1500); const missing = await rows(admin); log("登录日志 账号不存在:", JSON.stringify(missing));
  log("页面含 nobody 原文:", (await text(admin)).includes("nobody"), "含口令原文:", (await text(admin)).includes("Typed-secret-999"));
  await admin.go("/audit/logins?result=wrong_password"); await sleep(1500); log("登录日志 口令错误:", JSON.stringify(await rows(admin))); await admin.shot("demo7-3-logins-wrong");
  await admin.go("/audit/logins?account_id=abc"); await sleep(1500);
  const bad = await text(admin); log("非法参数页: 提示", bad.includes("日志筛选参数不合法"), "| 崩溃", bad.includes("请求失败"), "| 有筛选表单", bad.includes("筛选结果"));
  await admin.go("/audit/operations"); await sleep(1500);
  await admin.ev("(() => { const el = document.getElementById('audit-retention-days'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; el.focus(); set.call(el, '14'); el.dispatchEvent(new Event('input', { bubbles: true })); })()");
  await admin.ev(H + "__click('保存保留期')"); await sleep(1500);
  log("保留期接口 =", await admin.ev("fetch('/api/audit/retention').then(r => r.json()).then(j => j.days)"));
  await admin.go("/audit/operations?operation=set_retention"); await sleep(1500); log("操作日志 修改保留期:", JSON.stringify(await rows(admin)));
  await admin.go("/accounts"); await admin.wait("document.body.innerText.includes('member1')");
  await admin.ev(H + "(() => { const tr = [...document.querySelectorAll('tr')].find(r => r.innerText.includes('member1')); [...tr.querySelectorAll('button')].find(b => b.getAttribute('aria-label') === '删除').click(); })()");
  await sleep(500); await admin.ev("(() => { const ok = [...document.querySelectorAll('.ant-modal-confirm-btns button, .ant-modal-footer button')].pop(); ok.click(); })()");
  await admin.wait("!document.body.innerText.includes('member1')"); log("admin 删除 member1");
  await admin.go("/audit/operations?target_account_id=2"); await sleep(1500); const after = await rows(admin);
  log("删除后 操作日志 对象=2:", JSON.stringify(after)); await admin.shot("demo7-4-deleted");
  const ok = after.some(r => r.includes("成员一（已删除）"));
  log(ok ? "DEMO PASS（已删除 标记出现）" : "DEMO CHECK: 未见（已删除）");
  if (!ok) process.exitCode = 1;
} catch (e) { log("DEMO FAIL", e.message); process.exitCode = 1; }
finally { ws.close(); chrome.kill("SIGTERM"); }
