// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * eSign Control Bundle (Desk)
 *
 * Loaded through esign.control.bundle.js (app_include_js) and runs on the desk/backend.
 * At this point frappe.ui.form is guaranteed to be available, so no polling needed.
 */
import { ControlUpload } from "./controls/upload";
import { ControlSignature } from "./controls/signature";
import { ControlFontSelect } from "./controls/font_select";

// Override frappe's built-in controls with our enhanced versions
frappe.ui.form.ControlUpload = ControlUpload;
frappe.ui.form.ControlSignature = ControlSignature;
frappe.ui.form.ControlFontSelect = ControlFontSelect;
