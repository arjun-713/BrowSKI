import { ACTIVITY_CHANNEL, type ActivityState } from "../../src/page-activity";
import "./style.css";

const PILL_TEXT: Record<Exclude<ActivityState, "idle">, string> = {
  working: "BROWSKI is working in this tab",
  approval: "BROWSKI is waiting for your approval in the side panel",
  paused: "BROWSKI is paused",
};

// The glow is the agent's presence in the page: an orange edge that breathes,
// a light sweeping the border, and one pill that can stop the task.
const STYLE = `
  :host { all: initial; }
  .glow, .sweep {
    position: fixed;
    inset: 0;
    pointer-events: none;
    border-radius: 10px;
  }
  .glow {
    box-shadow:
      inset 0 0 0 2px rgb(255 122 26 / 95%),
      inset 0 0 14px 2px rgb(255 110 10 / 70%),
      inset 0 0 44px 6px rgb(255 106 0 / 22%);
    animation: breathe 2.6s ease-in-out infinite alternate;
  }
  /* A beam of light travels the border: an oversized conic layer rotated by
     transform (registered properties do not apply inside shadow roots) and
     clipped to a 3px ring around the viewport. */
  .sweep {
    overflow: hidden;
    padding: 4px;
    mask: linear-gradient(#000 0 0) content-box exclude, linear-gradient(#000 0 0);
  }
  .sweep::before {
    content: "";
    position: absolute;
    top: 50%;
    left: 50%;
    width: 200vmax;
    height: 200vmax;
    margin: -100vmax 0 0 -100vmax;
    background: conic-gradient(
      transparent 0deg 250deg,
      rgb(255 122 26 / 70%) 300deg,
      rgb(255 196 140) 340deg,
      #fff4e8 354deg,
      transparent 360deg
    );
    animation: sweep 4.8s linear infinite;
  }
  .pill {
    position: fixed;
    bottom: 18px;
    left: 50%;
    display: flex;
    align-items: center;
    gap: 10px;
    max-width: calc(100vw - 32px);
    padding: 6px 6px 6px 14px;
    border: 1px solid rgb(255 122 26 / 45%);
    border-radius: 10px;
    color: #efe9dd;
    background: #141210;
    box-shadow:
      0 10px 30px -8px rgb(0 0 0 / 60%),
      0 0 24px -4px rgb(255 122 26 / 45%);
    font: 500 12.5px/1.3 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    transform: translateX(-50%);
    pointer-events: auto;
    animation: rise 360ms cubic-bezier(0.16, 1, 0.3, 1) both;
  }
  .led {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #ff7a1a;
    box-shadow: 0 0 10px 2px rgb(255 122 26 / 70%);
    animation: breathe 1.2s ease-in-out infinite alternate;
  }
  .text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .stop {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 28px;
    padding: 0 10px;
    border: 0;
    border-radius: 7px;
    color: #1b0d03;
    background: #ff7a1a;
    font: 600 12px/1 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    cursor: pointer;
  }
  .stop:hover { background: #ff9a4d; }
  .stop:focus-visible { outline: 2px solid #ffb27a; outline-offset: 2px; }
  .stop:disabled { opacity: 0.6; cursor: default; }
  .stop svg { width: 10px; height: 10px; }
  /* Waiting for the user: the sweep stops and the edge deepens into a slow,
     strong pulse that reads as "your turn", not "working". */
  [data-state="approval"] .glow {
    box-shadow:
      inset 0 0 0 3px rgb(255 122 26),
      inset 0 0 36px 10px rgb(255 90 0 / 55%),
      inset 0 0 120px 28px rgb(255 90 0 / 20%);
    animation: deep 2.4s ease-in-out infinite;
  }
  [data-state="approval"] .sweep { display: none; }
  [data-state="approval"] .pill { border-color: #ff7a1a; }
  [data-state="paused"] .glow { animation: none; opacity: 0.45; }
  [data-state="paused"] .sweep { display: none; }
  [data-state="paused"] .led { animation: none; opacity: 0.5; }
  @keyframes breathe { from { opacity: 0.6; } to { opacity: 1; } }
  @keyframes sweep { to { transform: rotate(1turn); } }
  @keyframes deep { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
  @keyframes rise { from { opacity: 0; transform: translate(-50%, 10px); } }
  @media (prefers-reduced-motion: reduce) {
    .glow, .led, .pill { animation: none; }
    .sweep { display: none; }
  }
`;

function buildOverlay(onStop: () => void) {
  const host = document.createElement("div");
  host.id = "browski-page-activity";
  // A closed shadow root keeps page scripts and styles away from the overlay.
  const root = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = STYLE;
  const layer = document.createElement("div");
  const glow = document.createElement("div");
  glow.className = "glow";
  glow.setAttribute("aria-hidden", "true");
  const sweep = document.createElement("div");
  sweep.className = "sweep";
  sweep.setAttribute("aria-hidden", "true");
  const pill = document.createElement("div");
  pill.className = "pill";
  pill.setAttribute("role", "status");
  const led = document.createElement("span");
  led.className = "led";
  const text = document.createElement("span");
  text.className = "text";
  const stop = document.createElement("button");
  stop.className = "stop";
  stop.type = "button";
  stop.setAttribute("aria-label", "Stop the BROWSKI task");
  stop.innerHTML =
    '<svg viewBox="0 0 10 10" aria-hidden="true"><rect width="10" height="10" rx="1.5" fill="currentColor"/></svg>Stop';
  stop.addEventListener("click", (event) => {
    // Only a real user click may stop the task; page scripts cannot reach
    // this closed shadow root, and synthetic events are ignored.
    if (!event.isTrusted || stop.disabled) return;
    stop.disabled = true;
    onStop();
  });
  pill.append(led, text, stop);
  layer.append(glow, sweep, pill);
  root.append(style, layer);
  return {
    host,
    render(state: ActivityState) {
      if (state === "idle") return;
      layer.dataset.state = state;
      text.textContent = PILL_TEXT[state];
      stop.disabled = false;
    },
  };
}

export default defineContentScript({
  matches: ["http://*/*", "https://*/*"],
  runAt: "document_idle",
  main(ctx) {
    const overlay = buildOverlay(() => {
      void chrome.runtime.sendMessage({ type: "activity.stop" }).catch(() => undefined);
    });

    function show(active: boolean, state: ActivityState): void {
      if (active) {
        overlay.render(state);
        if (!overlay.host.isConnected) document.documentElement.append(overlay.host);
      } else {
        overlay.host.remove();
      }
    }

    function read(message: unknown): { active: boolean; state: ActivityState } | null {
      if (
        typeof message !== "object" ||
        message === null ||
        !("type" in message) ||
        message.type !== ACTIVITY_CHANNEL ||
        !("active" in message) ||
        typeof message.active !== "boolean"
      ) {
        return null;
      }
      const state =
        "state" in message &&
        typeof message.state === "string" &&
        ["working", "approval", "paused", "idle"].includes(message.state)
          ? (message.state as ActivityState)
          : "working";
      return { active: message.active, state };
    }

    let receivedUpdate = false;
    const onMessage = (message: unknown, sender: chrome.runtime.MessageSender): void => {
      const activity = sender.id === chrome.runtime.id ? read(message) : null;
      if (activity) {
        receivedUpdate = true;
        show(activity.active, activity.state);
      }
    };
    chrome.runtime.onMessage.addListener(onMessage);
    void chrome.runtime
      .sendMessage({ type: "activity.read" })
      .then((message) => {
        const activity = read(message);
        if (!receivedUpdate && activity) show(activity.active, activity.state);
      })
      .catch(() => show(false, "idle"));
    ctx.onInvalidated(() => {
      chrome.runtime.onMessage.removeListener(onMessage);
      overlay.host.remove();
    });
  },
});
