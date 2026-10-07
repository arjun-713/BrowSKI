import { defineConfig } from "wxt";

export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  manifest: {
    name: "BROWSKI Browser Companion",
    description: "Connect Chrome to a local BROWSKI runtime session.",
    permissions: ["sidePanel", "nativeMessaging", "storage", "debugger", "activeTab"],
    side_panel: {
      default_path: "panel.html",
    },
    action: {
      default_title: "Open BROWSKI panel",
    },
  },
});
