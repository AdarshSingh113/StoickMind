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

console.log("Landing page");
await page.goto(base + "/");
await page.getByRole("heading", { name: /The AI CRM that sells/ }).waitFor();
ok(true, "public landing page renders");
await page.getByRole("tab", { name: /Order Management/ }).click();
await page.getByText("Actions with limits enforced in code").waitFor();
ok(true, "module tabs switch the preview");
await snap(page, "00-landing");

console.log("Login");
await page.getByRole("button", { name: "Open dashboard" }).first().click();
await page.waitForURL("**/login");
ok(true, "the dashboard needs a login");
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
await page.goto(base + "/app/inbox");
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
await page.getByLabel("Private note").check();
await page.getByPlaceholder(/Private note/).fill("Refund approved, pickup booked for tomorrow");
await page.keyboard.press("Enter");
await page.getByTestId("thread").getByText("Refund approved, pickup booked").waitFor();
ok(await page.getByText(/Private note ·/).first().isVisible(), "private note shows in the thread, marked team-only");
await page.getByLabel("Private note").uncheck();

console.log("Live updates (website chat taken over by a person)");
await page.goto(base + "/app/inbox?view=all");
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

console.log("Customers (R3)");
await page.goto(base + "/app/customers");
await page.getByRole("heading", { name: "Customers" }).waitFor();
// The first request on a fresh database trains the ML models (a few seconds): wait for real rows, not skeletons.
await page.locator("tbody tr:has(div.font-semibold)").nth(24).waitFor({ timeout: 90000 });
ok((await page.locator("tbody tr").count()) === 25, "customer list shows a page of 25");
await page.getByRole("button", { name: /^Champions/ }).click();
await page.waitForTimeout(700);
ok((await page.locator("tbody").getByText("Champions").count()) === (await page.locator("tbody tr").count()), "segment filter");
const firstName = (await page.locator("tbody tr td").first().locator("div.font-semibold").last().textContent()).trim();
await page.locator("tbody tr").first().click();
await page.getByRole("heading", { name: firstName }).waitFor();
ok(await page.getByText("Lifetime value").isVisible() && await page.getByText("Churn risk").first().isVisible(), "Customer 360 opens with ML scores");
await snap(page, "05-customer360");

console.log("Campaigns (R5)");
await page.goto(base + "/app/campaigns/new?journey=win_back");
await page.getByText(/customers qualify today/).waitFor();
await page.getByRole("button", { name: /Write with AI/ }).click();
await page.getByText("Variant A").waitFor();
ok(true, "A/B templates written (AI, or validated hand-written fallback)");
await page.getByRole("button", { name: /Create draft/ }).click();
await page.getByRole("button", { name: /Send campaign/ }).waitFor();
ok(true, "campaign created as a draft");
await page.getByRole("button", { name: /Send campaign/ }).click();
await page.getByRole("button", { name: /Measure results/ }).click();
await page.getByText("Verdict:").waitFor();
ok(await page.getByText("Conversion by group").isVisible(), "send + measure shows a verdict with confidence ranges");
await snap(page, "06-campaign");

console.log("Helpdesk (R5)");
await page.goto(base + "/app/helpdesk");
await page.getByRole("tab", { name: /Resolved/ }).click();
await page.locator("button:has(p)").first().click();
await page.getByRole("button", { name: /Let AI handle it|Run again/ }).waitFor();
ok(true, "ticket detail with the AI copilot");
await page.getByRole("tab", { name: /Approvals/ }).click();
await page.getByText(/Nothing waiting for approval|Needs approval|Approve|Resolve/).first().waitFor();
ok(true, "approvals queue renders");

console.log("Agent Studio (R6)");
await page.goto(base + "/app/studio");
await page.getByText("Kavya").first().click();
await page.getByRole("heading", { name: "Configuration" }).waitFor();
ok(await page.getByRole("switch", { name: "Skin reaction or allergy" }).isChecked(), "handoff rules shown, skin reaction on by default");
ok(await page.getByText("Product catalogue, prices and stock").isVisible(), "data access derived from the agent's tools");
const goal = page.locator("label:has-text('Goal') textarea");
const oldGoal = await goal.inputValue();
await goal.fill(oldGoal + " (e2e)");
await page.getByPlaceholder("What changed? (version note)").fill("e2e edit");
await page.getByRole("button", { name: /Save version/ }).click();
await page.getByText(/Saved as version/).waitFor();
ok(true, "editing an agent saves a new version");
await page.getByRole("button", { name: /Restore/ }).first().click();
await page.getByText(/Restored as version/).waitFor();
const restored = await page.waitForFunction(([el, want]) => el.value === want, [await goal.elementHandle(), oldGoal], { timeout: 5000 })
  .then(() => true, () => false);
ok(restored, "restoring an old version brings the old goal back");
await snap(page, "07-studio");

console.log("Ask your data + AI performance (R4)");
await page.goto(base + "/app/ask");
await page.getByRole("button", { name: /Top 5 products by units sold/ }).click();
await page.getByText(/AI isn't configured|numbers checked|Summary withheld|Couldn't answer|Result/).first().waitFor({ timeout: 60000 });
ok(true, "Ask your data answers, or explains that the AI key is missing");
await page.goto(base + "/app/performance");
await page.getByText("What customers ask about").waitFor();
ok(await page.getByText("Skin reaction").first().isVisible(), "conversations tab: topics + share handled fully by AI");
for (const tab of ["Traces", "Cost", "Evals", "Business impact"]) {
  await page.getByRole("tab", { name: tab }).click();
  await page.waitForTimeout(500);
}
await page.getByText(/Measured net value/).waitFor();
ok(true, "AI performance tabs render");

console.log("Command palette, dark mode, mobile");
await page.keyboard.press("Control+k");
await page.getByPlaceholder("Search pages or conversations…").fill("rash");
await page.locator("[cmdk-item]").filter({ hasText: "WhatsApp" }).first().waitFor();
ok(true, "Ctrl+K finds conversations");
await page.keyboard.press("Escape");
await page.locator("body").click({ position: { x: 5, y: 5 } }).catch(() => {});
await page.goto(base + "/app");
await page.getByLabel("Toggle theme").click();
await page.getByText("Net revenue").first().waitFor();
await page.waitForTimeout(800);
ok(await page.evaluate(() => document.documentElement.classList.contains("dark")), "dark mode toggles");
await snap(page, "05-overview-dark");
await page.getByLabel("Toggle theme").click();

const mobile = await browser.newContext({ ...devices["iPhone 13"], storageState: await ctx.storageState() });
const m = await mobile.newPage();
m.on("pageerror", (e) => errors.push(e.message));
await m.goto(base + "/app/inbox");
await m.getByText("Great, thanks!").first().click();
await m.getByLabel("Back").waitFor();
ok(true, "mobile: list -> thread with back button");
await snap(m, "06-mobile-thread");
await m.goto(base + "/app");
await m.getByText("Net revenue").first().waitFor();
const overflow = await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
ok(!overflow, "mobile: no horizontal scroll");
await m.goto(base + "/");
await m.getByRole("heading", { name: /The AI CRM that sells/ }).waitFor();
ok(!(await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)), "mobile: landing page fits");
await snap(m, "07-mobile-overview");

ok(errors.length === 0, "no JavaScript errors" + (errors.length ? ": " + errors.join(" | ") : ""));
await browser.close();
console.log("\nAll end-to-end checks passed.");
