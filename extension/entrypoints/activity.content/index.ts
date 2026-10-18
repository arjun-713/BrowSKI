import { ACTIVITY_CHANNEL } from "../../src/page-activity";
import "./style.css";

export default defineContentScript({
  matches: ["http://*/*", "https://*/*"],
  runAt: "document_idle",
  main(ctx) {
    const host = document.createElement("div");
    host.id = "browski-page-activity";
    host.setAttribute("aria-hidden", "true");
    // A closed shadow root prevents page styles from changing the indicator.
    const root = host.attachShadow({ mode: "closed" });
    const frame = document.createElement("div");
    frame.className = "browski-activity-frame";
    const badge = document.createElement("span");
    badge.className = "browski-activity-badge";
    badge.textContent = "BROWSKI is working";
    frame.append(badge);
    const style = document.createElement("style");
    style.textContent = `
      .browski-activity-frame {
        position: fixed;
        inset: 0;
        z-index: 2147483647;
        pointer-events: none;
        border: 3px solid #f47b35;
        border-radius: 5px;
        box-sizing: border-box;
        animation: browski-working 1.8s ease-in-out infinite alternate;
      }
      .browski-activity-badge {
        position: absolute;
        top: 12px;
        left: 50%;
        transform: translateX(-50%);
        padding: 8px 14px;
        border-radius: 6px;
        background: #38261d;
        color: #fff0e5;
        font: 500 12px/1.4 system-ui, sans-serif;
        box-shadow: 0 4px 12px rgb(0 0 0 / 12%);
        white-space: nowrap;
      }
      @keyframes browski-working {
        from { opacity: 0.72; }
        to { opacity: 1; }
      }
      @media (prefers-reduced-motion: reduce) {
        .browski-activity-frame { animation: none; }
      }
    `;
    root.append(style, frame);

    function show(active: boolean): void {
      if (active && !host.isConnected) document.documentElement.append(host);
      if (!active) host.remove();
    }
    let receivedUpdate = false;
    const onMessage = (message: unknown, sender: chrome.runtime.MessageSender): void => {
      if (
        sender.id === chrome.runtime.id &&
        typeof message === "object" &&
        message !== null &&
        "type" in message &&
        message.type === ACTIVITY_CHANNEL &&
        "active" in message &&
        typeof message.active === "boolean"
      ) {
        receivedUpdate = true;
        show(message.active);
      }
    };
    chrome.runtime.onMessage.addListener(onMessage);
    void chrome.runtime
      .sendMessage({ type: "activity.read" })
      .then((message) => {
        if (!receivedUpdate && message?.type === ACTIVITY_CHANNEL)
          show(message.active === true);
      })
      .catch(() => show(false));
    ctx.onInvalidated(() => {
      chrome.runtime.onMessage.removeListener(onMessage);
      host.remove();
    });
  },
});
