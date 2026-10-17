// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

// frappe's own web form modules, which the eSign web bundle imports and frappe-types does not
// declare, and the non-script files the bundles import. frappe's esbuild resolves
// "frappe/public/js/…" from the bench's apps directory.

/** The website bundles and scripts the eSign page loads for their side effects. */
declare module "frappe/public/js/*.js";

/** A frappe microtemplate: esbuild compiles it into a `frappe.templates` entry. */
declare module "*.html";

declare module "frappe/public/js/frappe/web_form/web_form" {
	import type { WebForm } from "frappe-types/web";

	/** frappe/public/js/frappe/web_form/web_form.js: the members the eSign web form uses. */
	export interface WebFormController extends WebForm {
		/** Shows the success message after a save, or redirects to `success_url`. */
		handle_success(data: unknown): void;
		/** Builds the fields, the actions and the client script into `parent`. */
		prepare(web_form_doc: unknown, doc: unknown): void;
		make(): void;
		success_url?: string;
		allow_incomplete?: boolean | 0 | 1;
		accept_payment?: boolean | 0 | 1;
		esign_enabled?: boolean | 0 | 1;
	}

	const WebFormClass: {
		new (opts: { parent: JQuery }): WebFormController;
		prototype: WebFormController;
	};
	export default WebFormClass;
}

declare module "frappe/public/js/frappe/web_form/web_form_list" {
	/** frappe/public/js/frappe/web_form/web_form_list.js: renders the list from its constructor. */
	const WebFormList: new (opts: {
		doctype: string;
		web_form_name: string;
		list_columns: unknown;
		condition_json: unknown;
		settings: { allow_delete: unknown };
	}) => object;
	export default WebFormList;
}
