# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

app_name = "esign"
app_title = "eSign"
app_publisher = "Avunu LLC"
app_description = "Collect Electronic Signatures on Frappe Documents via Webforms"
app_email = "mail@avu.nu"
app_license = "MIT"

# The esbuild entries are .js files that import the TypeScript modules: `bench build` keys
# assets.json by the entry's name and `bench build --using-cached` by the built file's, and only a
# .js entry gets the same key from both.
app_include_js = ["esign.desk.bundle.js", "esign.control.bundle.js"]
app_include_css = [
	"esign.control.bundle.css",
	"esign-fonts.bundle.css",
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

# Frappe v16 composes these onto the stock controllers (and any other app's extensions),
# so each class subclasses the stock controller only.
extend_doctype_class = {
	"Web Form": "esign.esign.custom.web_form.EsignWebForm",
	"Email Template": "esign.esign.custom.email_template.EsignEmailTemplate",
}


jinja = {
	"methods": [
		"esign.esign.custom.web_form.get_esign_link",
	]
}
