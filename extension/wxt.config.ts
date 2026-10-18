import { fileURLToPath } from "node:url";
import { defineConfig } from "wxt";

export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  vite: () => ({
    server: {
      fs: {
        allow: [
          fileURLToPath(new URL(".", import.meta.url)),
          fileURLToPath(new URL("../crates/browser-core/src/mechanics", import.meta.url)),
        ],
      },
    },
  }),
  manifest: {
    name: "BROWSKI Browser Companion",
    description: "Connect Chrome to a local BROWSKI runtime session.",
    permissions: [
      "sidePanel",
      "nativeMessaging",
      "storage",
      "debugger",
      "activeTab",
      "tabs",
    ],
    side_panel: {
      default_path: "panel.html",
    },
    action: {
      default_title: "Open BROWSKI panel",
    },
  },
});
