// End-to-end smoke test: drives the REAL app (built React + FastAPI + SQLite) in a headless browser.
// Usage: NODE_PATH=$(npm root -g) node e2e/smoke.mjs http://localhost:8000 [screenshot-dir]
import { createRequire } from "node:module";
// Uses the Playwright installed on the machine (NODE_PATH=$(npm root -g)), not a project dependency.
const { chromium, devices } = createRequire(import.meta.url)("playwright");

const base = process.argv[2] ?? "http://localhost:8000";
const shots = process.argv[3];
const scale = Number(process.env.SCALE ?? 1);
const ok = (cond, msg) => { if (!cond) throw new Error("FAILED: " + msg); console.log("  ✓ " + msg); };
const snap = async (page, name) => shots && page.screenshot({ path: `${shots}/${name}.png` });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: scale, colorScheme: "light" });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

console.log("Login");
await page.goto(base + "/");
await page.waitForURL("**/login");
ok(true, "unauthenticated visit redirects to /login");
await snap(page, "01-login");
await page.fill("input[type=password]", "wrong");
await page.click("button:has-text('Sign in')");
await page.getByRole("alert").waitFor();
ok((await page.getByRole("alert").textContent()).includes("Wrong password"), "wrong password is rejected");
await page.fill("input[type=password]", process.env.KOTLER_ADMIN_PASSWORD ?? "kotler");
await page.click("button:has-text('Sign in')");
await page.getByRole("heading", { name: "Overview" }).waitFor();
ok(true, "correct password opens the dashboard");

console.log("Overview");
await page.getByText("Net revenue").first().waitFor();
await page.waitForTimeout(800);
ok(await page.getByText("What to know").isVisible(), "insights render");
ok((await page.locator(".recharts-area").count()) > 0, "revenue chart renders");
await snap(page, "02-overview");
await page.getByRole("tab", { name: "90 days" }).click();
await page.waitForTimeout(600);
ok(await page.getByText("compared with the previous 90 days").isVisible(), "period switch refetches");

console.log("Inbox");
// Start from fresh demo chats every run (the endpoint replaces earlier demo data), so the test is repeatable.
ok((await page.request.post(base + "/api/v1/inbox/demo")).ok(), "demo conversations loaded");
await page.goto(base + "/inbox");
await page.getByText("Great, thanks!").first().waitFor();
ok(true, "conversations listed");
await page.getByRole("tab", { name: /Needs you/ }).click();
await page.waitForTimeout(400);
ok(await page.getByText("I want a refund.").first().isVisible(), "'Needs you' filter shows escalated chats");
ok(!(await page.getByText("Great, thanks!").first().isVisible()), "...and hides chats the AI handled");
await page.getByText("I want a refund.").first().click();
await page.getByText("The AI escalated this chat.").waitFor();
ok(true, "escalation banner shown in thread");
await snap(page, "03-inbox-thread");
await page.getByRole("button", { name: "Take over" }).first().click();
await page.getByPlaceholder(/Reply on WhatsApp/).waitFor();
ok(true, "take over enables the composer");
await page.getByPlaceholder(/Reply on WhatsApp/).fill("Hi, I'm Neha from Glow & Co. I've started your refund.");
await page.keyboard.press("Enter");
await page.getByTestId("thread").getByText("I've started your refund.").waitFor();
ok(true, "human reply appears in the thread");

console.log("Live updates (website chat taken over by a person)");
await page.goto(base + "/inbox?view=all");
await page.getByText("Website visitor").first().click();  // the skin-quiz web chat
await page.getByRole("button", { name: "Take over" }).first().click();
await page.getByPlaceholder(/Reply on Website/).waitFor();
// The customer writes from the website widget (a different "browser"): no reload on our side.
const live = `Is anyone there? I need help choosing (${Date.now() % 100000})`;
const r = await fetch(base + "/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ session_id: "demo-web-0004", message: live }) });
const body = await r.json();
ok(body.human === true && body.replies.length === 0, "AI stays silent while a person handles the chat");
await page.getByTestId("thread").getByText(live).waitFor({ timeout: 8000 });
ok(true, "customer message arrived live (Server-Sent Events), no reload");
await page.getByPlaceholder(/Reply on Website/).fill("Hi! I'm here. Tell me about your skin.");
await page.keyboard.press("Enter");
await page.getByTestId("thread").getByText("Tell me about your skin.").waitFor();
const upd = await (await fetch(`${base}/api/chat/updates?session_id=demo-web-0004&after=${body.last_id}`)).json();
ok(upd.messages.some((m) => m.text.includes("Tell me about your skin")), "widget receives the person's reply");
await snap(page, "04-inbox-live");
await page.getByRole("button", { name: "Hand back to AI" }).click();
await page.getByText("Handed back to the AI.").waitFor();
ok(true, "hand back to AI");

console.log("Command palette, dark mode, mobile");
await page.keyboard.press("Control+k");
await page.getByPlaceholder("Search pages or conversations…").fill("rash");
await page.locator("[cmdk-item]").filter({ hasText: "WhatsApp" }).first().waitFor();
ok(true, "Ctrl+K finds conversations");
await page.keyboard.press("Escape");
await page.locator("body").click({ position: { x: 5, y: 5 } }).catch(() => {});
await page.goto(base + "/");
await page.getByLabel("Toggle theme").click();
await page.getByText("Net revenue").first().waitFor();
await page.waitForTimeout(800);
ok(await page.evaluate(() => document.documentElement.classList.contains("dark")), "dark mode toggles");
await snap(page, "05-overview-dark");
await page.getByLabel("Toggle theme").click();

const mobile = await browser.newContext({ ...devices["iPhone 13"], storageState: await ctx.storageState() });
const m = await mobile.newPage();
m.on("pageerror", (e) => errors.push(e.message));
await m.goto(base + "/inbox");
await m.getByText("Great, thanks!").first().click();
await m.getByLabel("Back").waitFor();
ok(true, "mobile: list -> thread with back button");
await snap(m, "06-mobile-thread");
await m.goto(base + "/");
await m.getByText("Net revenue").first().waitFor();
const overflow = await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
ok(!overflow, "mobile: no horizontal scroll");
await snap(m, "07-mobile-overview");

ok(errors.length === 0, "no JavaScript errors" + (errors.length ? ": " + errors.join(" | ") : ""));
await browser.close();
console.log("\nAll end-to-end checks passed.");
