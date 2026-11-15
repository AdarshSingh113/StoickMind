/* Kotler AI chat widget. Embed on any page:
 *   <script src="https://YOUR-APP/widget.js" defer></script>
 * No framework, no cookies. A random session id is kept in localStorage so the conversation continues
 * across page loads. Messages are rendered with textContent (never innerHTML), so nothing a customer
 * or the AI writes can inject HTML or scripts into the page.
 */
(function () {
  if (window.__kotlerWidget) return;
  window.__kotlerWidget = true;
  var script = document.currentScript;
  var API = (script && script.src ? new URL(script.src).origin : location.origin) + "/api/chat";
  var C = { brand: "#4F46E5", soft: "#EEF2FF", ink: "#0F172A", line: "#E6E8F0" };

  function sessionId() {
    var id = null;
    try { id = localStorage.getItem("kotler_session"); } catch (e) {}
    if (!id) {
      id = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
      try { localStorage.setItem("kotler_session", id); } catch (e) {}
    }
    return id;
  }

  var css = document.createElement("style");
  css.textContent =
    ".kw-btn{position:fixed;right:20px;bottom:20px;width:58px;height:58px;border-radius:50%;border:0;cursor:pointer;" +
    "background:linear-gradient(135deg,#14B8A6," + C.brand + ");color:#fff;font-size:26px;box-shadow:0 8px 24px rgba(79,70,229,.35);z-index:99999}" +
    ".kw-panel{position:fixed;right:20px;bottom:90px;width:360px;max-width:calc(100vw - 32px);height:520px;max-height:calc(100vh - 120px);" +
    "background:#fff;border:1px solid " + C.line + ";border-radius:18px;box-shadow:0 12px 40px rgba(15,23,42,.18);display:none;" +
    "flex-direction:column;overflow:hidden;z-index:99999;font-family:Inter,-apple-system,Segoe UI,Roboto,sans-serif}" +
    ".kw-head{padding:14px 16px;background:" + C.brand + ";color:#fff;font-weight:600}.kw-head small{display:block;font-weight:400;opacity:.85}" +
    ".kw-body{flex:1;overflow-y:auto;padding:14px;background:#F6F7FB}" +
    ".kw-msg{max-width:85%;padding:9px 12px;margin:6px 0;border-radius:14px;font-size:14px;line-height:1.45;white-space:pre-wrap;color:" + C.ink + "}" +
    ".kw-bot{background:#fff;border:1px solid " + C.line + ";border-top-left-radius:4px}" +
    ".kw-me{background:" + C.soft + ";margin-left:auto;border-top-right-radius:4px}" +
    ".kw-foot{display:flex;gap:8px;padding:10px;border-top:1px solid " + C.line + "}" +
    ".kw-foot input{flex:1;border:1px solid " + C.line + ";border-radius:10px;padding:10px;font-size:14px}" +
    ".kw-foot button{border:0;border-radius:10px;padding:0 14px;background:" + C.brand + ";color:#fff;cursor:pointer}";
  document.head.appendChild(css);

  var btn = document.createElement("button");
  btn.className = "kw-btn"; btn.setAttribute("aria-label", "Chat with us"); btn.textContent = "✦";
  var panel = document.createElement("div");
  panel.className = "kw-panel"; panel.setAttribute("role", "dialog");
  panel.innerHTML = '<div class="kw-head">Glow & Co. assistant<small>Products, routines and orders · English or Hinglish</small></div>' +
    '<div class="kw-body"></div><form class="kw-foot"><input maxlength="1000" placeholder="Type your message…" aria-label="Message">' +
    "<button>Send</button></form>";
  document.body.appendChild(btn); document.body.appendChild(panel);
  var body = panel.querySelector(".kw-body"), form = panel.querySelector("form"), input = panel.querySelector("input");

  function add(text, who) {
    var div = document.createElement("div");
    div.className = "kw-msg " + (who === "me" ? "kw-me" : "kw-bot");
    // *bold* -> <b> using DOM nodes only (safe)
    text.split(/(\*[^*\n]+\*)/g).forEach(function (part) {
      if (/^\*[^*\n]+\*$/.test(part)) { var b = document.createElement("b"); b.textContent = part.slice(1, -1); div.appendChild(b); }
      else if (part) div.appendChild(document.createTextNode(part.replace(/\*\*/g, "")));
    });
    body.appendChild(div); body.scrollTop = body.scrollHeight;
    return div;
  }

  function send(text) {
    if (!text.trim()) return;
    add(text, "me");
    var typing = add("…", "bot");
    fetch(API, { method: "POST", headers: { "Content-Type": "application/json" },
                 body: JSON.stringify({ session_id: sessionId(), message: text }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        typing.remove();
        if (d.last_id) lastId = Math.max(lastId, d.last_id);
        if (d.human && !(d.replies || []).length) {
          if (!humanNoted) { humanNoted = true; add("A member of our team is looking at this and will reply here.", "bot"); }
          return;
        }
        (d.replies || ["Sorry, something went wrong."]).forEach(function (t) { add(t, "bot"); });
      })
      .catch(function () { typing.remove(); add("Sorry, I couldn't connect. Please try again.", "bot"); });
  }

  // A person can take over this chat from the Kotler inbox. Their replies can't be pushed to a plain web page,
  // so while the panel is open we ask for new ones every 4 seconds (cheap: one indexed query).
  var lastId = 0, humanNoted = false;
  function poll() {
    if (panel.style.display !== "flex" || !lastId) return;
    fetch(API + "/updates?session_id=" + encodeURIComponent(sessionId()) + "&after=" + lastId)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        (d.messages || []).forEach(function (m) { add(m.text, "bot"); });
        if (d.last_id) lastId = Math.max(lastId, d.last_id);
      }).catch(function () {});
  }
  setInterval(poll, 4000);

  var greeted = false;
  btn.onclick = function () {
    var open = panel.style.display === "flex";
    panel.style.display = open ? "none" : "flex";
    if (!open && !greeted) { greeted = true; add("Hi! Ask me about products for your skin, or about your order.", "bot"); }
    if (!open) input.focus();
  };
  form.onsubmit = function (e) { e.preventDefault(); var t = input.value; input.value = ""; send(t); };
  window.KotlerChat = { open: function (q) { if (panel.style.display !== "flex") btn.onclick(); if (q) send(q); } };
})();
