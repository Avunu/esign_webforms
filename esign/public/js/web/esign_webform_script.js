// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * eSign WebForm Script
 *
 * This replaces frappe's webform_script.js for eSign-enabled forms.
 * It extends WebForm to use our custom accept endpoint and registers
 * our custom controls for the web/public frontend.
 */
import WebFormList from "../../../../../frappe/frappe/public/js/frappe/web_form/web_form_list";
import WebForm from "../../../../../frappe/frappe/public/js/frappe/web_form/web_form";

// ============================================================================
// Document Preview Functions
// ============================================================================

/**
 * Scale print format to fit the document pane width
 */
function scaleToFitDocumentPane() {
	const documentPane = document.querySelector(".esign-document-pane");
	const shadowHost = document.getElementById("shadow-host");

	if (!shadowHost || !shadowHost.shadowRoot || !documentPane) {
		return;
	}

	const printFormat = shadowHost.shadowRoot.querySelector(".print-format");
	if (!printFormat) {
		return;
	}

	// Reset zoom to measure natural width
	printFormat.style.zoom = "100%";

	// Get the natural width of the print format content
	const contentWidth = printFormat.scrollWidth;

	// clientWidth = inner width INCLUDING CSS padding.
	// Subtract the actual horizontal padding so the print format doesn't
	// overflow into the padded area.
	const paneStyle = getComputedStyle(documentPane);
	const horizontalPadding = parseFloat(paneStyle.paddingLeft) + parseFloat(paneStyle.paddingRight);
	const availableWidth = documentPane.clientWidth - horizontalPadding;

	// Calculate scale factor
	let scale = 100;
	if (contentWidth > availableWidth && availableWidth > 0) {
		scale = 100 * (availableWidth / contentWidth);
	}

	// Apply the scale transformation
	printFormat.style.zoom = `${scale}%`;
}

/**
 * Load print HTML asynchronously from the server
 * @returns {Promise} Promise that resolves when content is loaded and rendered
 */
function loadPrintHtml() {
	const ctx = frappe.esign_context;
	if (!ctx || !ctx.doctype || !ctx.name) {
		console.error("eSign context not available");
		return Promise.reject("Context not available");
	}

	const shadowHost = document.getElementById("shadow-host");
	if (!shadowHost || !shadowHost.shadowRoot) {
		console.error("Shadow host not available");
		return Promise.reject("Shadow host not available");
	}

	const shadowRoot = shadowHost.shadowRoot;
	const loadingEl = shadowRoot.getElementById("print-view-loading");
	const printContent = shadowRoot.getElementById("print-content");

	// Show loading state
	if (loadingEl) loadingEl.classList.remove("hide");
	if (printContent) printContent.classList.add("hide");

	return frappe
		.call({
			method: "esign.esign.custom.web_form.get_print_html",
			args: {
				doctype: ctx.doctype,
				docname: ctx.name,
				print_format: ctx.print_format || "standard",
				key: ctx.key || "",
			},
			freeze: false,
		})
		.then((response) => {
			if (response.message) {
				renderPrintHtml(response.message.print_html, response.message.print_style);
			}
		})
		.catch((error) => {
			console.error("Failed to load print HTML:", error);
			if (loadingEl) {
				loadingEl.innerHTML = '<p class="text-danger">Failed to load document preview.</p>';
			}
		});
}

/**
 * Render print HTML into the shadow DOM
 * @param {string} printHtml - The HTML content to render
 * @param {string} printStyle - Additional CSS styles for the print format
 */
function renderPrintHtml(printHtml, printStyle) {
	const shadowHost = document.getElementById("shadow-host");
	if (!shadowHost || !shadowHost.shadowRoot) return;

	const shadowRoot = shadowHost.shadowRoot;
	const loadingEl = shadowRoot.getElementById("print-view-loading");
	const printContent = shadowRoot.getElementById("print-content");
	const styleEl = shadowRoot.getElementById("print-style");

	// Append print format styles to existing style element
	if (styleEl && printStyle) {
		styleEl.textContent += printStyle;
	}

	// Set the print content
	if (printContent) {
		printContent.innerHTML = `<div class="print-format">${printHtml}</div>`;
		printContent.classList.remove("hide");
	}

	// Hide loading
	if (loadingEl) loadingEl.classList.add("hide");

	// Scale after content is rendered
	setTimeout(scaleToFitDocumentPane, 100);

	// Re-scale when fonts are loaded
	if (document.fonts) {
		document.fonts.ready.then(() => {
			setTimeout(scaleToFitDocumentPane, 100);
		});
	}
}

/**
 * Refresh the document preview (called after form submission)
 * @returns {Promise} Promise that resolves when content is refreshed
 */
function refreshPrintHtml() {
	return loadPrintHtml();
}

// Expose functions globally for external access
window.loadPrintHtml = loadPrintHtml;
window.refreshPrintHtml = refreshPrintHtml;

/**
 * Initialize document preview functionality
 */
function initDocumentPreview() {
	const ctx = frappe.esign_context;

	// Skip loading print HTML if we have a signed PDF (completed documents)
	if (ctx && ctx.signed_pdf_url) {
		console.debug("Signed PDF available, skipping print HTML load");
		return;
	}

	// Load print HTML for documents that need signing
	loadPrintHtml();

	// Re-scale on window resize with debouncing
	let resizeTimeout;
	window.addEventListener("resize", () => {
		clearTimeout(resizeTimeout);
		resizeTimeout = setTimeout(scaleToFitDocumentPane, 150);
	});
}

// ============================================================================
// Custom Controls Registration
// ============================================================================

// Import and register eSign controls for web forms
import { ControlUpload } from "../controls/upload";
import { ControlSignature } from "../controls/signature";

frappe.ui.form.ControlUpload = ControlUpload;
frappe.ui.form.ControlSignature = ControlSignature;

class EsignWebForm extends WebForm {
	handle_success(data) {
		// Override to use eSign success card in sidebar
		const formCard = document.querySelector(".esign-form-card");
		const successCard = document.getElementById("esign-success-card");

		// Refresh the document preview to show the new signature
		if (window.refreshPrintHtml) {
			window.refreshPrintHtml().then(() => {
				console.debug("Document preview refreshed after signing");
			});
		}

		if (formCard && successCard) {
			// Hide the form card, show the success card
			formCard.classList.add("hide");
			successCard.classList.remove("hide");

			// Handle redirect if success_url is set
			if (this.success_url) {
				this.handle_redirect();
			}
		} else {
			// Fallback to parent behavior
			super.handle_success(data);
		}
	}

	handle_redirect() {
		// Countdown and redirect
		const timeSpan = document.querySelector(".esign-redirect-message .time");
		if (!timeSpan) {
			window.location.href = this.success_url;
			return;
		}

		let countdown = 5;
		const interval = setInterval(() => {
			countdown--;
			timeSpan.textContent = countdown;
			if (countdown <= 0) {
				clearInterval(interval);
				window.location.href = this.success_url;
			}
		}, 1000);
	}

	save() {
		// Use eSign accept endpoint if esign_enabled, otherwise use default
		let method = this.esign_enabled
			? "esign.esign.custom.web_form.accept"
			: "frappe.website.doctype.web_form.web_form.accept";

		// debug
		console.debug("Using save method:", method);

		let is_new = this.is_new;
		let valid = this.validate && this.validate();
		if (!valid && valid !== undefined) {
			frappe.msgprint(__("Couldn't save, please check the data you have entered"), __("Validation Error"));
			return false;
		}

		// validation hack: get_values will check for missing data
		let doc_values = super.get_values(this.allow_incomplete);

		if (!doc_values) return false;

		if (window.saving) return false;

		// TODO: remove this (used for payments app)
		let for_payment = Boolean(this.accept_payment && !this.doc.paid);

		Object.assign(this.doc, doc_values);
		this.doc.doctype = this.doc_type;
		this.doc.web_form_name = this.name;

		// Save
		window.saving = true;
		frappe.form_dirty = false;

		frappe.call({
			type: "POST",
			method: method,
			args: {
				data: this.doc,
				web_form: this.name,
				for_payment,
			},
			btn: $("btn-primary"),
			freeze: true,
			callback: (response) => {
				// Check for any exception in response
				if (!response.exc) {
					// Success
					this.handle_success(response.message);
					frappe.web_form.events.trigger("after_save");
					if (this.after_save) {
						this.after_save();
					}
					// args doctype and docname added to link doctype in file manager
					if (is_new && (response.message.attachment || response.message.file)) {
						frappe.call({
							type: "POST",
							method: "frappe.handler.upload_file",
							args: {
								file_url: response.message.attachment || response.message.file,
								doctype: response.message.doctype,
								docname: response.message.name,
							},
						});
					}
				}
			},
			always: function () {
				window.saving = false;
			},
		});
		return false;
	}
}

frappe.ready(function () {
	let web_form_doc = frappe.web_form_doc;
	let reference_doc = frappe.reference_doc;

	// Initialize document preview (always, even for completed forms)
	if (frappe.esign_context) {
		initDocumentPreview();
	}

	// If document is already completed/signed, don't initialize the form
	if (frappe.is_completed) {
		console.debug("Document already signed, skipping form initialization");
		return;
	}

	show_login_prompt();

	if (web_form_doc.is_list) {
		show_list();
	} else {
		show_form();
	}

	function show_login_prompt() {
		if (frappe.session.user != "Guest" || !web_form_doc.login_required) return;
		const login_required = new frappe.ui.Dialog({
			title: __("Not Permitted"),
			primary_action_label: __("Login"),
			primary_action: () => {
				window.location.replace("/login?redirect-to=" + window.location.pathname);
			},
		});
		login_required.show();
		login_required.set_message(__("You are not permitted to access this page without login."));
	}

	function show_list() {
		// oxlint-disable-next-line no-new -- WebFormList renders the list from its constructor
		new WebFormList({
			doctype: web_form_doc.doc_type,
			web_form_name: web_form_doc.name,
			list_columns: web_form_doc.list_columns,
			condition_json: web_form_doc.condition_json,
			settings: {
				allow_delete: web_form_doc.allow_delete,
			},
		});
	}

	function show_form() {
		// Use our extended EsignWebForm instead of base WebForm
		let web_form = new EsignWebForm({
			parent: $(".web-form-wrapper"),
		});
		let doc = reference_doc || {};
		setup_fields(web_form_doc, doc);

		web_form.prepare(web_form_doc, doc);
		web_form.make();

		if (web_form_doc.is_new) {
			web_form.set_default_values();
		}

		$(".file-size").each(function () {
			$(this).text(frappe.form.formatters.FileSize($(this).text()));
		});
	}

	function setup_fields(form_doc, doc_data) {
		form_doc.web_form_fields.forEach((df) => {
			df.is_web_form = true;
			df.read_only = df.read_only || (!form_doc.is_new && !form_doc.in_edit_mode);
			if (df.fieldtype === "Table") {
				df.get_data = () => {
					let data = [];
					if (doc_data && doc_data[df.fieldname]) {
						return doc_data[df.fieldname];
					}
					return data;
				};

				$.each(df.fields || [], function (_i, field) {
					if (field.fieldtype === "Link") {
						field.only_select = true;
					}
					field.is_web_form = true;
				});

				if (df.fieldtype === "Attach") {
					df.is_private = true;
				}

				delete df.parent;
				delete df.parentfield;
				delete df.parenttype;
				delete df.doctype;

				return df;
			}
			if (df.fieldtype === "Link") {
				df.only_select = true;
			}
			if (["Attach", "Attach Image"].includes(df.fieldtype)) {
				if (typeof df.options !== "object") {
					df.options = {};
				}
				df.options.disable_file_browser = true;
			}
		});
	}
});
