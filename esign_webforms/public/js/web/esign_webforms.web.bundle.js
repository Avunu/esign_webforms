// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

// The esbuild entry point, kept as .js so assets.json names the bundle "esign_webforms.web.bundle.js" both
// in a normal build and in `bench build --using-cached`, which keys by the built file's name.
// oxlint-disable-next-line import/no-unassigned-import -- the module registers itself
import "./esign_web.ts";
