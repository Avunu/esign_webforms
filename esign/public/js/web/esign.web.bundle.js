// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * eSign Web Form Bundle
 *
 * Complete replacement for frappe's web_form.bundle.js that includes
 * our extended WebForm class with custom accept endpoint for eSign forms.
 */
// Side-effect imports: each module registers itself or emits CSS and font files.
// oxlint-disable import/no-unassigned-import
import "../../../../../frappe/frappe/public/js/bootstrap-4-web.bundle.js";
import "../../../../../frappe/frappe/public/js/controls.bundle.js";
import "../../../../../frappe/frappe/public/js/dialog.bundle.js";
import "../../../../../frappe/frappe/public/js/frappe/ui/keyboard.js";
import "../../../../../frappe/frappe/public/js/frappe/utils/datetime.js";
import "../../../../../frappe/frappe/public/js/lib/moment.js";
import "./esign_webform_script.js";
// oxlint-enable import/no-unassigned-import
import { ControlFontSelect } from "../controls/font_select";
frappe.ui.form.ControlFontSelect = ControlFontSelect;
