# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The demo hook frappe-demo calls (`esign_webforms.demo.setup`)."""

import datetime
import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from esign_webforms import demo
from esign_webforms.tests.utils import make_pdf

CTX = {"today": datetime.date(2026, 1, 15), "seed": 1, "company": None, "erpnext_demo": False}
PDF = make_pdf()


class TestDemo(IntegrationTestCase):
	def setup_demo(self) -> None:
		with patch("esign_webforms.demo.get_pdf", return_value=PDF):
			demo.setup(CTX)

	def test_setup_creates_the_esign_web_form_and_template(self):
		self.setup_demo()
		web_form = frappe.db.get_value(
			"Web Form",
			demo.WEB_FORM,
			[
				"doc_type",
				"esign_enabled",
				"print_format",
				"esign_update_field",
				"esign_signer_name_field",
				"esign_signer_email_field",
			],
			as_dict=True,
		)
		assert web_form is not None
		self.assertEqual(web_form.doc_type, demo.DOCTYPE)
		self.assertEqual(web_form.esign_enabled, 1)
		self.assertEqual(web_form.print_format, demo.PRINT_FORMAT)
		self.assertEqual(web_form.esign_update_field, "status")
		self.assertEqual(web_form.esign_signer_name_field, "signer_name")
		self.assertEqual(web_form.esign_signer_email_field, "signer_email")
		self.assertEqual(frappe.db.get_value("Email Template", demo.EMAIL_TEMPLATE, "esign_request"), 1)

	def test_unsigned_agreement_waits_for_a_signature(self):
		self.setup_demo()
		values = frappe.db.get_value(
			demo.DOCTYPE, demo.UNSIGNED, ["docstatus", "signature", "start_date"], as_dict=True
		)
		assert values is not None
		self.assertEqual(values.docstatus, 0)
		self.assertFalse(values.signature)
		self.assertEqual(str(values.start_date), "2026-01-29")

	def test_signed_agreement_has_its_pdf_and_audit_record(self):
		self.setup_demo()
		values = frappe.db.get_value(
			demo.DOCTYPE, demo.SIGNED, ["docstatus", "status", "signature"], as_dict=True
		)
		assert values is not None
		self.assertEqual(values.docstatus, 1)
		self.assertEqual(values.status, "Signed")
		self.assertTrue(str(values.signature).startswith("data:image/png;base64,"))

		files = frappe.get_all(
			"File",
			filters={"attached_to_doctype": demo.DOCTYPE, "attached_to_name": demo.SIGNED},
			pluck="file_name",
		)
		self.assertEqual(len(files), 1)
		self.assertTrue(files[0].startswith(f"{demo.SIGNED}_signed_20260115_104215"))

		content = frappe.db.get_value(
			"Communication",
			{"reference_doctype": demo.DOCTYPE, "reference_name": demo.SIGNED, "communication_type": "eSign"},
			"content",
		)
		assert isinstance(content, str)
		audit = json.loads(content)
		self.assertEqual(audit["signer_email"], demo.SIGNER_EMAIL)
		self.assertEqual(audit["signer_name"], "Dana Whitfield")
		self.assertEqual(audit["timestamp"], "2026-01-15 10:42:15")
		self.assertTrue(audit["signer_email_verified"])
		self.assertEqual(audit["verified_via"], "recipient link")
		self.assertEqual(audit["consent_text"], "I agree to sign this document electronically.")
		self.assertEqual(len(audit["pdf_hash"]), 64)

	def test_setup_is_idempotent(self):
		self.setup_demo()
		self.setup_demo()
		self.assertEqual(frappe.db.count(demo.DOCTYPE, {"name": ("in", [demo.UNSIGNED, demo.SIGNED])}), 2)
		self.assertEqual(
			frappe.db.count(
				"Communication",
				{
					"reference_doctype": demo.DOCTYPE,
					"reference_name": demo.SIGNED,
					"communication_type": "eSign",
				},
			),
			1,
		)

	def test_render_pdf_renders_the_print_format(self):
		self.setup_demo()
		doc = frappe.get_doc(demo.DOCTYPE, demo.UNSIGNED)
		with patch("esign_webforms.demo.get_pdf", return_value=PDF) as get_pdf:
			self.assertEqual(demo.render_pdf(doc), PDF)
		html = get_pdf.call_args.args[0]
		self.assertIn("Northwind Bakery", html)
		self.assertIn("January 29, 2026", html)
