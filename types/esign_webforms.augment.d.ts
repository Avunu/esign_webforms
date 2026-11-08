// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

// The names esign_webforms adds to frappe's namespaces and to the page, for the desk scripts and the
// compiled bundles. A module (it imports), so the `frappe-types` block merges into the package.

import type { ControlData, FrappeCheck } from "frappe-types";

/** What the eSign page template (esign_webforms/templates/esign_webforms.html) passes to the page script. */
interface EsignContext {
	doctype: string;
	name: string;
	key: string;
	web_form: string;
	print_format: string;
	signed_pdf_url: string;
}

declare module "frappe-types" {
	interface FrappeUiFormNamespace {
		// app-owned: the image upload control, registered by esign_webforms's control bundles
		ControlUpload: typeof ControlData;
		// app-owned: the font picker control, registered by esign_webforms's control bundles
		ControlFontSelect: typeof ControlData;
	}

	interface WebFormDocFields {
		// app-owned: the Web Form's "eSign Enabled" Custom Field, which prepare() copies onto the controller
		esign_enabled?: FrappeCheck;
	}

	interface Frappe {
		// app-owned: set by the eSign page template for its document preview
		esign_context?: EsignContext;
		// app-owned: set by the eSign page template once every signature field is signed
		is_completed?: boolean;
	}
}

declare global {
	/** A family the Local Font Access API reports (only the member esign_webforms reads). */
	interface LocalFontData {
		readonly family: string;
	}

	interface Window {
		// app-owned: the eSign page's document preview loader, for other page scripts
		loadPrintHtml?: () => Promise<void>;
		// app-owned: reloads the eSign page's document preview after signing
		refreshPrintHtml?: () => Promise<void>;
		// The Local Font Access API (Chromium only), not in TypeScript's DOM library
		queryLocalFonts?: () => Promise<LocalFontData[]>;
	}
}
