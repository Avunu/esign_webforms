# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import frappe

frappe_version = int(frappe.__version__.split(".")[0])

app_name = "esign"
app_title = "eSign"
app_publisher = "Avunu LLC"
app_description = "Collect Electronic Signatures on Frappe Documents via Webforms"
app_email = "mail@avu.nu"
app_license = "MIT"

app_include_js = ["esign.desk.bundle.js", "esign.control.bundle.js"]
app_include_css = [
	"esign.control.bundle.css",
	"/assets/esign/dist/esign-fonts.css",
]

# Install/migrate hooks for communication type registration
after_install = "esign.config.after_install"
after_migrate = "esign.config.after_migrate"
after_uninstall = "esign.config.after_uninstall"

# Timeline integration for eSign audit trail
additional_timeline_content = {
	"*": ["esign.esign.get_timeline_content"],
}


doctype_js = {
	"Web Form": "public/js/web_form.js",
}

if frappe_version >= 16:
	extend_doctype_class = {
		"Web Form": "esign.esign.custom.web_form.EsignWebForm",
		"Email Template": "esign.esign.custom.email_template.EsignEmailTemplate",
	}
else:
	override_doctype_class = {
		"Web Form": "esign.esign.custom.web_form.EsignWebForm",
		"Email Template": "esign.esign.custom.email_template.EsignEmailTemplate",
	}


jinja = {
	"methods": [
		"esign.esign.custom.web_form.get_esign_link",
	]
}
