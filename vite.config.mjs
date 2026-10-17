// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { defineConfig } from "vite";

// The signature fonts: esign/public/css/esign-fonts.entry.css becomes
// public/dist/css/esign-fonts.bundle.<hash>.css plus its font files, and the manifest lets
// scripts/vite-register.mjs register it in assets.json as esign-fonts.bundle.css, so it is
// served by name and cache-busted like frappe's own bundles.
export default defineConfig({
	// Font URLs relative to the stylesheet, so they resolve under /assets/esign/dist/.
	base: "./",
	build: {
		outDir: "esign/public/dist",
		// frappe's esbuild bundles share public/dist.
		emptyOutDir: false,
		manifest: true,
		assetsInlineLimit: 0,
		rollupOptions: {
			input: { "esign-fonts": "esign/public/css/esign-fonts.entry.css" },
			output: {
				assetFileNames: (assetInfo) =>
					/\.(woff2?|ttf|otf|eot)$/.test(assetInfo.names?.[0] ?? "")
						? "fonts/[name]-[hash][extname]"
						: "css/[name].bundle.[hash][extname]",
			},
		},
	},
});
