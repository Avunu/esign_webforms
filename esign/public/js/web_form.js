// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

frappe.ui.form.on("Web Form", {
	refresh: function (frm) {
		if (frm.doc.doc_type) {
			frm.events.update_field_options(frm);
		}
		frm.events.set_notification_query(frm);
	},
	doc_type: function (frm) {
		frm.events.update_field_options(frm);
		frm.events.set_notification_query(frm);
	},
	update_field_options: function (frm) {
		var doc = frm.doc;
		if (!doc.doc_type) {
			return;
		}
		frappe.model.with_doctype(doc.doc_type, () => {
			const fieldnames = frappe
				.get_meta(doc.doc_type)
				.fields.filter((field) => !frappe.model.no_value_type.includes(field.fieldtype))
				.map((field) => field.fieldname);

			frm.set_df_property("esign_update_field", "options", [""].concat(fieldnames));
		});
	},
	set_notification_query: function (frm) {
		// Filter notifications to only show Custom event notifications for the same doctype
		frm.set_query("esign_notification", function () {
			return {
				filters: {
					document_type: frm.doc.doc_type,
					event: "Custom",
					enabled: 1,
				},
			};
		});
	},
});
