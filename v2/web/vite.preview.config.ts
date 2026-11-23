// Dev-only UI preview: renders the real pages with fixture data and no sign-in.
// Not part of the production build (vite.config.ts builds index.html only). Binds to loopback.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [
    react(),
    {
      name: "preview-spa-fallback",
      configureServer(server) {
        server.middlewares.use((req, _res, next) => {
          if (req.url && /^\/(provider|examiner)(\/|\?|$)/.test(req.url)) req.url = "/preview.html";
          next();
        });
      },
    },
  ],
  resolve: {
    alias: [{ find: /^(\.\.?\/)+api$/, replacement: fileURLToPath(new URL("./src/preview/mockApi.ts", import.meta.url)) }],
  },
  server: { host: "127.0.0.1", port: 5174, strictPort: true, open: false },
});
