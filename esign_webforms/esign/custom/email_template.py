# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import frappe
from frappe.email.doctype.email_template.email_template import EmailTemplate
from frappe.types import DF


class EsignEmailTemplate(EmailTemplate):
	# Custom fields from ../custom/email_template.json
	esign_request: DF.Check | None

	def get_context(self, context):
		context.update(
			{
				"esign_request": self.get("esign_request"),
			}
		)
		return context


@frappe.whitelist()
def get_esign_email_templates():
	"""Get all eSign-enabled email templates for a given doctype."""
	return frappe.get_all(
		"Email Template",
		filters={"esign_request": 1},
		fields=["subject", "response_html", "response"],
	)
