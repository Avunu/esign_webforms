# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

app_name = "esign_webforms"
app_title = "Webform eSignatures"
app_publisher = "Avunu LLC"
app_description = "Collect Electronic Signatures on Frappe Documents via Webforms"
app_email = "mail@avu.nu"
app_license = "MIT"

# The esbuild entries are .js files that import the TypeScript modules: `bench build` keys
# assets.json by the entry's name and `bench build --using-cached` by the built file's, and only a
# .js entry gets the same key from both.
app_include_js = ["esign_webforms.desk.bundle.js", "esign_webforms.control.bundle.js"]
app_include_css = [
	"esign_webforms.control.bundle.css",
	"esign-fonts.bundle.css",
]

# Install/migrate hooks for communication type registration
after_install = "esign_webforms.config.after_install"
after_migrate = "esign_webforms.config.after_migrate"
after_uninstall = "esign_webforms.config.after_uninstall"

# Timeline integration for eSign audit trail
additional_timeline_content = {
	"*": ["esign_webforms.esign.get_timeline_content"],
}


doctype_js = {
	"Web Form": "public/js/web_form.js",
}

# Frappe v16 composes these onto the stock controllers (and any other app's extensions),
# so each class subclasses the stock controller only.
extend_doctype_class = {
	"Web Form": "esign_webforms.esign.custom.web_form.EsignWebForm",
	"Email Template": "esign_webforms.esign.custom.email_template.EsignEmailTemplate",
}


jinja = {
	"methods": [
		"esign_webforms.esign.custom.web_form.get_esign_link",
	]
}


# frappe-nix:rename-shim-begin esign
# esign's whitelisted methods under their old dotted paths, for callers that still use
# them (cached bundles, webhooks, bookmarks). Written by frappe-rename-app; keep it for
# at least one minor release after the rename.
override_whitelisted_methods = {
	**globals().get("override_whitelisted_methods", {}),
	"esign.esign.can_esign": "esign_webforms.esign.can_esign",
	"esign.esign.send_esign_email": "esign_webforms.esign.send_esign_email",
	"esign.esign.custom.email_template.get_esign_email_templates": "esign_webforms.esign.custom.email_template.get_esign_email_templates",
	"esign.esign.custom.web_form.get_esign_link": "esign_webforms.esign.custom.web_form.get_esign_link",
	"esign.esign.custom.web_form.get_print_html": "esign_webforms.esign.custom.web_form.get_print_html",
	"esign.esign.custom.web_form.download_signed_pdf": "esign_webforms.esign.custom.web_form.download_signed_pdf",
	"esign.esign.custom.web_form.get_esign_web_forms": "esign_webforms.esign.custom.web_form.get_esign_web_forms",
	"esign.esign.custom.web_form.accept": "esign_webforms.esign.custom.web_form.accept",
}
# frappe-nix:rename-shim-end
