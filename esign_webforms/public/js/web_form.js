// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * Fill the "Set Property After Response" select with the value fields of the web form's
 * doctype.
 * @param {frappe.ui.form.Form<"Web Form">} frm
 */
function update_field_options(frm) {
	const doc_type = frm.doc.doc_type;
	if (!doc_type) {
		return;
	}
	void frappe.model.with_doctype(doc_type, () => {
		const fieldnames = (frappe.get_meta(doc_type)?.fields ?? [])
			.filter((field) => !frappe.model.no_value_type.includes(field.fieldtype))
			.map((field) => field.fieldname);

		frm.set_df_property("esign_update_field", "options", [""].concat(fieldnames));
	});
}

/**
 * Offer only enabled Custom-event notifications for the web form's doctype.
 * @param {frappe.ui.form.Form<"Web Form">} frm
 */
function set_notification_query(frm) {
	frm.set_query("esign_notification", function () {
		return {
			filters: {
				document_type: frm.doc.doc_type,
				event: "Custom",
				enabled: 1,
			},
		};
	});
}

/** @type {frappe.ui.form.FormEvents<"Web Form">} */
const web_form_events = {
	refresh(frm) {
		if (frm.doc.doc_type) {
			update_field_options(frm);
		}
		set_notification_query(frm);
	},
	doc_type(frm) {
		update_field_options(frm);
		set_notification_query(frm);
	},
};

frappe.ui.form.on("Web Form", web_form_events);
