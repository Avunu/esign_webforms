// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { Dialog, Form, FrappeResponse } from "frappe-types";

// oxlint-disable-next-line import/no-unassigned-import -- registers the timeline card's microtemplate
import "./templates/esign_timeline.html";

/** A row of esign_webforms.esign.custom.web_form.get_esign_web_forms. */
interface EsignWebFormRow {
	name: string;
	title: string;
	route: string;
	print_format: string | null;
	esign_require_verified_email: 0 | 1;
}

/** A MultiSelect suggestion. */
interface ContactOption {
	value: string;
	label: string;
	description: string;
}

/** What esign_webforms.esign.send_esign_email returns. */
interface SendEsignEmailResult {
	success: boolean;
	message: string;
	communication: string;
	esign_link: string;
}

/**
 * Optional form events another app can define on a doctype to steer the dialog: the sending
 * Email Account and the suggested recipients.
 */
interface EsignFormEvents {
	get_email_account?: (
		frm: Form,
		fieldname: string,
	) => Promise<string | null | undefined> | string | null | undefined;
	get_email_recipients?: (
		frm: Form,
		fieldname: string,
	) => Promise<string[] | null | undefined> | string[] | null | undefined;
}

$(document).on("form-refresh", function (_event: JQuery.TriggeredEvent, frm: Form) {
	frappe
		.call<boolean>("esign_webforms.esign.can_esign", {
			doctype: frm.doctype,
			doc: frm.doc,
		})
		.then((r: FrappeResponse<boolean>) => {
			if (r.message) {
				const esign_dialog = new ESignDialog(frm);
				frm.add_custom_button(__("Send for eSign"), () => {
					if (frm.doc.__islocal) {
						frappe.msgprint(__("Please save the document before sending for eSign."));
						return;
					}
					esign_dialog.show();
				});
			}
		});
});

class ESignDialog {
	frm: Form;
	web_forms: EsignWebFormRow[];
	dialog: Dialog;
	contact_list_cache: ContactOption[];

	constructor(frm: Form) {
		this.frm = frm;
		this.web_forms = [];
		this.contact_list_cache = [];
		this.dialog = this.init_dialog();
	}

	/** The form's optional eSign events (see EsignFormEvents). */
	get esign_events(): EsignFormEvents {
		return this.frm.events as EsignFormEvents;
	}

	init_dialog(): Dialog {
		return new frappe.ui.Dialog({
			title: __("Send for eSign"),
			fields: [
				{
					label: __("From"),
					fieldtype: "Link",
					options: "Email Account",
					fieldname: "email_account",
					only_select: 1,
					get_query: () => {
						const filters: Record<string, unknown> = { enable_outgoing: 1 };
						if (this.frm.doc.company) {
							filters.company = this.frm.doc.company;
						}
						return { filters };
					},
				},
				{
					label: __("To"),
					fieldtype: "MultiSelect",
					reqd: 1,
					fieldname: "recipients",
					get_data: (txt?: string) => {
						return this.get_cached_contact_list(txt);
					},
				},
				{
					fieldtype: "Section Break",
					fieldname: "more_options",
					label: __("More Options"),
					collapsible: 1,
				},
				{
					label: __("CC"),
					fieldtype: "MultiSelect",
					fieldname: "cc",
					get_data: (txt?: string) => {
						return this.get_cached_contact_list(txt);
					},
				},
				{
					label: __("BCC"),
					fieldtype: "MultiSelect",
					fieldname: "bcc",
					get_data: (txt?: string) => {
						return this.get_cached_contact_list(txt);
					},
				},
				{
					fieldtype: "Section Break",
					fieldname: "template_section",
				},
				{
					label: __("Email Template"),
					fieldtype: "Link",
					options: "Email Template",
					fieldname: "email_template",
					reqd: 1,
					get_query: () => ({
						filters: { esign_request: 1 },
					}),
					onchange: () => {
						const template = this.dialog.get_value("email_template");
						if (template) {
							this.load_email_template(String(template));
						}
					},
				},
				{
					label: __("eSign Web Form"),
					fieldtype: "Select",
					fieldname: "web_form",
					reqd: 1,
					options: [],
					onchange: () => {
						this.on_web_form_change();
					},
				},
				{
					fieldtype: "Section Break",
					fieldname: "message_section",
				},
				{
					label: __("Subject"),
					fieldtype: "Data",
					reqd: 1,
					fieldname: "subject",
					length: 524288,
				},
				{
					label: __("Message"),
					fieldtype: "Text Editor",
					fieldname: "content",
					reqd: 1,
				},
				{
					fieldtype: "HTML",
					fieldname: "esign_link_preview",
					options: "<p><em>Select a web form to preview the eSign link here.</em></p>",
				},
				{
					fieldtype: "Section Break",
					fieldname: "options_section",
				},
				{
					label: __("Send me a copy"),
					fieldtype: "Check",
					fieldname: "send_me_a_copy",
				},

				{
					label: __("Print Format"),
					fieldtype: "Link",
					options: "Print Format",
					fieldname: "print_format",
					get_query: () => ({
						filters: { doc_type: this.frm.doctype },
					}),
					onchange: () => {
						this.update_esign_link_preview();
					},
				},
			],
			size: "large",
			primary_action_label: __("Send eSign Request"),
			primary_action: (values) => {
				this.send_esign_request(values);
				this.dialog.hide();
			},
		});
	}

	show(): void {
		void this.load_web_forms();
	}

	async load_web_forms(): Promise<void> {
		// Load contact list cache first
		await this.load_contact_list_cache();

		frappe.call<EsignWebFormRow[]>({
			method: "esign_webforms.esign.custom.web_form.get_esign_web_forms",
			args: { doctype: this.frm.doctype },
			callback: (r) => {
				if (r.message && r.message.length > 0) {
					this.web_forms = r.message;
					const options = this.web_forms.map((wf) => ({
						label: wf.title,
						value: wf.name,
					}));
					this.dialog.set_df_property("web_form", "options", [...options]);
					void this.dialog.set_value("web_form", options[0]?.value);
					this.dialog.show();
					void this.prefill_email_account();
				} else {
					frappe.msgprint(__("No eSign-enabled web forms found for {0}", [this.frm.doctype]));
				}
			},
		});
	}

	async prefill_email_account(): Promise<void> {
		// Try custom hook first
		const events = this.esign_events;
		if (events.get_email_account) {
			try {
				const custom_email_account = await events.get_email_account(this.frm, "recipients");
				if (custom_email_account) {
					// Ensure proper format for MultiSelect
					void this.dialog.set_value("email_account", custom_email_account);
				}
			} catch (error) {
				console.error("Error fetching custom email accounts:", error);
			}
		} else {
			const filters: Record<string, unknown> = { enable_outgoing: 1 };
			if (this.frm.doc.company) {
				filters.company = this.frm.doc.company;
			}
			frappe.call<Array<{ name: string; default_outgoing: 0 | 1 }>>({
				method: "frappe.client.get_list",
				args: {
					doctype: "Email Account",
					filters,
					fields: ["name", "default_outgoing"],
					limit_page_length: 0,
				},
				callback: (r) => {
					if (!r.message || r.message.length === 0) return;

					const accounts = r.message;
					const default_account = accounts.find((a) => a.default_outgoing);
					const selected = default_account || (accounts.length === 1 ? accounts[0] : null);

					if (selected) {
						void this.dialog.set_value("email_account", selected.name);
					}
				},
			});
		}
	}

	on_web_form_change(): void {
		const web_form_name = this.dialog.get_value("web_form");
		const web_form = this.web_forms.find((wf) => wf.name === web_form_name);

		if (web_form && web_form.print_format) {
			void this.dialog.set_value("print_format", web_form.print_format);
		}

		this.update_esign_link_preview();
	}

	async load_contact_list_cache(): Promise<void> {
		let contacts: ContactOption[] = [];
		const doc = this.frm.doc;

		// Try custom hook first
		const events = this.esign_events;
		if (events.get_email_recipients) {
			try {
				const custom_contacts = await events.get_email_recipients(this.frm, "recipients");
				if (custom_contacts && custom_contacts.length > 0) {
					// Ensure proper format for MultiSelect
					contacts = custom_contacts.map((email) => ({
						value: email,
						label: email,
						description: email,
					}));
				}
			} catch (error) {
				console.error("Error fetching custom email recipients:", error);
			}
		}

		// Fallback to default contact extraction if no custom contacts. These are fields of
		// whichever doctype is open (Sales Order, Purchase Order, …), so they are read as strings.
		const field = (fieldname: string): string => {
			const value = doc[fieldname];
			return typeof value === "string" ? value : "";
		};
		if (contacts.length === 0) {
			if (field("customer") && field("customer_email")) {
				contacts.push({
					value: field("customer_email"),
					label: field("customer_email"),
					description: field("customer"),
				});
			}

			if (field("supplier") && field("supplier_email")) {
				contacts.push({
					value: field("supplier_email"),
					label: field("supplier_email"),
					description: field("supplier"),
				});
			}

			if (field("contact_email")) {
				contacts.push({
					value: field("contact_email"),
					label: field("contact_email"),
					description: field("contact_display") || "Contact",
				});
			}
		}

		this.contact_list_cache = contacts;
	}

	get_cached_contact_list(txt?: string): ContactOption[] {
		// Filter based on search text
		return this.contact_list_cache.filter(
			(contact) => !txt || contact.value.toLowerCase().includes(txt.toLowerCase()),
		);
	}

	load_email_template(template_name: string): void {
		frappe.call<{ subject: string; message: string }>({
			method: "frappe.email.doctype.email_template.email_template.get_email_template",
			args: {
				template_name: template_name,
				doc: this.frm.doc,
			},
			callback: (r) => {
				if (r.message) {
					void this.dialog.set_value("subject", r.message.subject);
					void this.dialog.set_value("content", r.message.message);
				}
			},
		});
	}

	update_esign_link_preview(): void {
		const web_form = this.dialog.get_value("web_form");
		const print_format = this.dialog.get_value("print_format") || "Standard";

		if (web_form) {
			frappe.call<string>({
				method: "esign_webforms.esign.custom.web_form.get_esign_link",
				args: {
					doc: this.frm.doc,
					web_form_name: web_form,
					print_format_name: print_format,
				},
				callback: (r) => {
					if (r.message) {
						const preview = this.dialog.fields_dict.esign_link_preview;
						if (!preview || !("$wrapper" in preview)) {
							return;
						}
						const verified = this.web_forms.find((wf) => wf.name === web_form)?.esign_require_verified_email;
						// A web form that requires a verified email signs only through a link bound
						// to its recipient, so the preview (bound to nobody) would not open it.
						const note = verified
							? `<p class="text-muted small">${__(
									"This web form requires a verified email: each recipient in To gets their own email, with a link bound to their address. CC, BCC and Send me a copy are not available.",
								)}</p>`
							: "";
						preview.$wrapper.html(
							`<p><strong>${__("eSign Link")}:</strong></p>
							${note}
							<div style="background: var(--control-bg); padding: 10px; border-radius: var(--border-radius); word-break: break-all;">
								<a href="${r.message}" target="_blank">${r.message}</a>
							</div>`,
						);
					}
				},
			});
		}
	}

	send_esign_request(values: Record<string, unknown>): void {
		frappe.call<SendEsignEmailResult>({
			method: "esign_webforms.esign.send_esign_email",
			args: {
				doctype: this.frm.doctype,
				name: this.frm.doc.name,
				recipients: values.recipients,
				cc: values.cc,
				bcc: values.bcc,
				subject: values.subject,
				message: values.content,
				web_form: values.web_form,
				print_format: values.print_format,
				send_me_a_copy: values.send_me_a_copy,
				email_account: values.email_account,
			},
			freeze: true,
			freeze_message: __("Sending eSign request..."),
			callback: (r) => {
				if (r.message && r.message.success) {
					frappe.show_alert({
						message: __("eSign request sent successfully"),
						indicator: "green",
					});
					void this.frm.reload_doc();
				}
			},
		});
	}
}
