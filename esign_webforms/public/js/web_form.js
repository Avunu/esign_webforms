// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * The field types "Set Property After Response" can set (UPDATE_FIELD_TYPES in
 * esign_webforms/esign/custom/web_form.py).
 */
const UPDATE_FIELD_TYPES = ["Select", "Link", "Data", "Text"];

/**
 * Fill the "Set Property After Response" select with the fields of the web form's doctype that
 * it can set.
 * @param {frappe.ui.form.Form<"Web Form">} frm
 */
function update_field_options(frm) {
	const doc_type = frm.doc.doc_type;
	if (!doc_type) {
		return;
	}
	void frappe.model.with_doctype(doc_type, () => {
		const fieldnames = (frappe.get_meta(doc_type)?.fields ?? [])
			.filter((field) => UPDATE_FIELD_TYPES.includes(field.fieldtype))
			.map((field) => field.fieldname);

		frm.set_df_property("esign_update_field", "options", [""].concat(fieldnames));
	});
}

/**
 * The field types the "Signer Name Field" and "Signer Email Field" can name (SIGNER_FIELD_TYPES
 * in esign_webforms/esign/custom/web_form.py).
 */
const SIGNER_FIELD_TYPES = ["Data"];

/**
 * Fill the "Signer Name Field" and "Signer Email Field" selects with the web form's own fields
 * that they can name: the audit trail records only what the signer typed into the form.
 * @param {frappe.ui.form.Form<"Web Form">} frm
 */
function update_signer_field_options(frm) {
	/** @type {string[]} */
	const options = [""];
	for (const field of frm.doc.web_form_fields ?? []) {
		if (field.fieldname && field.fieldtype && SIGNER_FIELD_TYPES.includes(field.fieldtype)) {
			options.push(field.fieldname);
		}
	}
	for (const setting of ["esign_signer_name_field", "esign_signer_email_field"]) {
		frm.set_df_property(setting, "options", options);
	}
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
		update_signer_field_options(frm);
	},
	web_form_fields_remove(frm) {
		update_signer_field_options(frm);
	},
	doc_type(frm) {
		update_field_options(frm);
		set_notification_query(frm);
	},
};

frappe.ui.form.on("Web Form", web_form_events);

/** @type {frappe.ui.form.FormEvents<"Web Form Field">} */
const web_form_field_events = {
	fieldname(frm) {
		update_signer_field_options(frm);
	},
	fieldtype(frm) {
		update_signer_field_options(frm);
	},
};

frappe.ui.form.on("Web Form Field", web_form_field_events);
