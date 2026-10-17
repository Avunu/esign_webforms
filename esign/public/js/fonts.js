// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * @fileoverview Font bundle entry point for Vite build.
 * Imports @fontsource packages so Vite extracts the CSS and font files.
 *
 * @author Avunu LLC
 */

// Side-effect imports: each module registers itself or emits CSS and font files.
// oxlint-disable import/no-unassigned-import
import "@fontsource/pacifico";
import "@fontsource/dancing-script";
import "@fontsource/great-vibes";
import "@fontsource/caveat";
// oxlint-enable import/no-unassigned-import
