import { defineConfig } from "vite";
import path from "path";

export default defineConfig({
	base: "./",
	build: {
		outDir: "esign/public/dist",
		emptyOutDir: false,
		assetsInlineLimit: 0,
		rollupOptions: {
			input: path.resolve(__dirname, "esign/public/js/fonts.js"),
			output: {
				entryFileNames: "esign-fonts.js",
				assetFileNames: (assetInfo) => {
					// Keep font files in a fonts/ subdirectory
					if (/\.(woff2?|ttf|otf|eot)$/.test(assetInfo.names?.[0] ?? "")) {
						return "fonts/[name][extname]";
					}
					// CSS output
					return "esign-fonts[extname]";
				},
			},
		},
	},
});
