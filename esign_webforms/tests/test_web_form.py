# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The signing flow: the web form page, its key checks, accept and the signing jobs."""

import hashlib
import hmac
import json
from typing import Any, cast
from unittest.mock import MagicMock, patch

import frappe
from frappe.model.document import Document
from frappe.model.meta import Meta
from frappe.tests import IntegrationTestCase
from frappe.website.serve import get_response_content

from esign_webforms.esign.custom import web_form as esign_web_form
from esign_webforms.esign.custom.web_form import (
	EMAIL_BINDING_PARAM,
	AuditData,
	EsignWebForm,
	RequestData,
	accept,
	attach_print_to_document,
	download_signed_pdf,
	extract_param_from_referrer,
	get_bound_email,
	get_esign_link,
	get_esign_web_forms,
	get_print_html,
	make_email_binding,
	record_signature,
	validate_esign_key,
)
from esign_webforms.tests.utils import (
	OUTSIDER,
	PLACEHOLDER_SIGNATURE,
	SIGNATURE,
	SIGNER,
	TEST_DOCTYPE,
	WEB_FORM_ROUTE,
	ensure_test_doctype,
	ensure_user,
	form_data,
	get_agreement,
	make_agreement,
	make_email_account,
	make_pdf,
	make_web_form,
	share_key,
	signing_request,
)

PDF = make_pdf()

# The signing request as _enqueue_print_attachment snapshots it for the jobs.
REQUEST_DATA: RequestData = {
	"host_url": "https://erp.example.com/",
	"scheme": "https",
	"host": "erp.example.com",
	"headers": {"User-Agent": "TestBrowser/1.0"},
	"method": "POST",
}


def fake_attach_print(**kwargs: Any) -> dict:
	return {"fname": f"{kwargs['file_name']}.pdf", "fcontent": PDF}


def add_signer_fields(
	wf: EsignWebForm, name: str | None = "signer_name", email: str | None = "signer_email"
) -> None:
	"""Add a Full Name field to the test web form and name the form's signer fields."""
	if not any(row.get("fieldname") == "signer_name" for row in wf.web_form_fields):
		wf.append("web_form_fields", {"fieldname": "signer_name", "fieldtype": "Data", "label": "Full Name"})
	wf.esign_signer_name_field = name
	wf.esign_signer_email_field = email
	wf.save(ignore_permissions=True)


class EsignTestCase(IntegrationTestCase):
	def setUp(self) -> None:
		# Idempotent: the doctype and users are created once per site and kept.
		ensure_test_doctype()
		ensure_user(OUTSIDER)
		ensure_user(SIGNER, ["System Manager"])
		frappe.set_user("Administrator")
		frappe.conf.disable_website_cache = True
		frappe.local.form_dict = frappe._dict()
		self.web_form = cast(EsignWebForm, make_web_form())
		self.web_form_name = str(self.web_form.name)
		self.doc = make_agreement()
		self.key = share_key(self.doc)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.conf.disable_website_cache = False
		frappe.local.request = None
		frappe.local.form_dict = frappe._dict()
		frappe.flags.ignore_print_permissions = False
		frappe.flags.esign_key_write = False
		frappe.local.message_log = []

	def reload_web_form(self) -> EsignWebForm:
		return cast(EsignWebForm, frappe.get_doc("Web Form", self.web_form_name))


class TestEsignWebFormController(EsignTestCase):
	def test_controller_is_composed_onto_web_form(self):
		self.assertIsInstance(frappe.get_doc("Web Form", self.web_form_name), EsignWebForm)

	def test_validate_forces_allow_edit(self):
		self.assertTrue(self.reload_web_form().allow_edit)

		plain = cast(EsignWebForm, make_web_form(esign_enabled=0, allow_edit=0))
		self.assertFalse(plain.allow_edit)

	def test_update_field_must_be_a_type_accept_sets(self):
		wf = self.reload_web_form()
		wf.esign_update_field = "rating"
		with self.assertRaises(frappe.ValidationError):
			wf.save(ignore_permissions=True)

		wf = self.reload_web_form()
		wf.esign_update_field = "status"
		wf.save(ignore_permissions=True)
		self.assertEqual(self.reload_web_form().esign_update_field, "status")

	def test_signer_fields_must_be_data_fields_of_the_form(self):
		wf = self.reload_web_form()
		add_signer_fields(wf)
		wf = self.reload_web_form()
		self.assertEqual(wf.esign_signer_name_field, "signer_name")
		self.assertEqual(wf.esign_signer_email_field, "signer_email")

		# A field of the doctype that is not on the form: its value is not the signer's input.
		wf.esign_signer_name_field = "title"
		with self.assertRaisesRegex(frappe.ValidationError, "must be one of this web form's fields"):
			wf.save(ignore_permissions=True)

		# A field on the form that is not a Data field.
		wf = self.reload_web_form()
		wf.esign_signer_email_field = "signature"
		with self.assertRaisesRegex(frappe.ValidationError, "can only be a Data field"):
			wf.save(ignore_permissions=True)

		# Unset is allowed.
		wf = self.reload_web_form()
		wf.esign_signer_name_field = None
		wf.esign_signer_email_field = ""
		wf.save(ignore_permissions=True)

	def test_signature_exists_only_when_every_signature_field_is_signed(self):
		wf = self.reload_web_form()
		self.assertFalse(wf._check_signature_exists(self.doc))

		self.doc.db_set("signature", PLACEHOLDER_SIGNATURE)
		self.assertFalse(wf._check_signature_exists(self.doc))

		self.doc.db_set("signature", SIGNATURE)
		self.assertTrue(wf._check_signature_exists(self.doc))

		wf.web_form_fields = [row for row in wf.web_form_fields if row.fieldtype != "Signature"]
		self.assertFalse(wf._check_signature_exists(self.doc))

	def test_signed_pdf_lookup_prefers_the_esign_communication(self):
		wf = self.reload_web_form()
		self.assertIsNone(wf._get_signed_pdf(self.doc))

		direct = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{self.doc.name}_signed_1.pdf",
				"attached_to_doctype": TEST_DOCTYPE,
				"attached_to_name": self.doc.name,
				"is_private": 1,
				"content": PDF,
			}
		).insert(ignore_permissions=True)
		self.assertEqual((wf._get_signed_pdf(self.doc) or {}).get("name"), direct.name)

		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "eSign",
				"subject": "Signed",
				"reference_doctype": TEST_DOCTYPE,
				"reference_name": self.doc.name,
			}
		).insert(ignore_permissions=True)
		on_comm = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "copy.pdf",
				"attached_to_doctype": "Communication",
				"attached_to_name": comm.name,
				"is_private": 1,
				"content": make_pdf(pages=2),
			}
		).insert(ignore_permissions=True)
		self.assertEqual((wf._get_signed_pdf(self.doc) or {}).get("name"), on_comm.name)


class TestKeyValidation(EsignTestCase):
	def test_valid_key_grants_access(self):
		frappe.set_user("Guest")
		self.assertTrue(validate_esign_key(self.key, self.doc))

	def test_wrong_key_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			validate_esign_key("not-a-key", self.doc)

	def test_missing_key_is_refused_when_required(self):
		with self.assertRaises(frappe.PermissionError):
			validate_esign_key("", self.doc, require_key=True)

	def test_missing_key_falls_back_to_print_permission(self):
		self.assertTrue(validate_esign_key("", self.doc))
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			validate_esign_key("", get_agreement(self.doc.name))

	def test_has_web_form_permission_accepts_the_key_from_the_referrer(self):
		wf = self.reload_web_form()
		frappe.set_user("Guest")
		with signing_request(referrer=f"https://example.com/{WEB_FORM_ROUTE}/x/edit?key={self.key}"):
			self.assertTrue(wf.has_web_form_permission(TEST_DOCTYPE, self.doc.name))
			self.assertEqual(frappe.form_dict.key, self.key)

	def test_share_key_writes_only_through_esign_accept(self):
		# frappe's own web form accept asks for write permission too; the key must not answer
		# it there, or a guest could skip the consent and the recipient binding.
		wf = self.reload_web_form()
		frappe.set_user("Guest")
		with signing_request(key=self.key):
			self.assertTrue(wf.has_web_form_permission(TEST_DOCTYPE, self.doc.name, "read"))
			self.assertFalse(wf.has_web_form_permission(TEST_DOCTYPE, self.doc.name, "write"))
			frappe.flags.esign_key_write = True
			try:
				self.assertTrue(wf.has_web_form_permission(TEST_DOCTYPE, self.doc.name, "write"))
			finally:
				frappe.flags.esign_key_write = False

	def test_has_web_form_permission_falls_back_on_a_bad_key(self):
		wf = self.reload_web_form()
		frappe.set_user("Guest")
		with signing_request(key="wrong"):
			self.assertFalse(wf.has_web_form_permission(TEST_DOCTYPE, self.doc.name, "write"))
		with signing_request():
			self.assertFalse(wf.has_web_form_permission(TEST_DOCTYPE, self.doc.name, "write"))

	def test_referrer_parameters(self):
		with signing_request(referrer="https://example.com/form?key=abc&email=a%40b.co&key=ignored"):
			self.assertEqual(extract_param_from_referrer("key"), "abc")
			self.assertEqual(extract_param_from_referrer("email"), "a@b.co")
			self.assertEqual(extract_param_from_referrer("format"), "")
		with signing_request():
			self.assertEqual(extract_param_from_referrer("key"), "")
		with (
			signing_request(referrer="https://example.com/?key=x"),
			patch("urllib.parse.urlparse", side_effect=ValueError("bad url")),
		):
			self.assertEqual(extract_param_from_referrer("key"), "")


class TestSigningPage(EsignTestCase):
	def render(self, **form_dict: Any) -> str:
		path = f"{WEB_FORM_ROUTE}/{self.doc.name}/edit"
		# The test bench may have no built assets; bundle names then render as they are.
		with (
			signing_request(path=path, method="GET", name=self.doc.name, **form_dict),
			patch("frappe.utils.get_assets_json", return_value={}),
		):
			return get_response_content(path)

	def test_guest_with_key_gets_the_signing_page(self):
		frappe.set_user("Guest")
		content = self.render(key=self.key, email="signer@example.com", format="Standard")

		self.assertIn("esign-layout", content)
		self.assertIn(f'key: "{self.key}"', content)
		self.assertIn(f'web_form: "{self.web_form_name}"', content)
		self.assertIn('print_format: "Standard"', content)
		self.assertIn("signer@example.com", content)
		self.assertIn("esign_webforms.web.bundle.js", content)
		self.assertIn("esign-fonts.bundle.css", content)
		self.assertIn("frappe.utils.print_format.download_pdf", content)
		self.assertNotIn("esign-completed", content)

	def test_email_parameter_prefills_the_signer_email_field(self):
		wf = self.reload_web_form()
		wf.append("web_form_fields", {"fieldname": "title", "fieldtype": "Data", "label": "Your Email"})
		add_signer_fields(wf, name=None, email="title")
		frappe.set_user("Guest")
		with patch(
			"frappe.website.doctype.web_form.web_form.WebForm.add_custom_context_and_script"
		) as custom:
			self.render(key=self.key, email="prefill@example.com")
		context = custom.call_args.args[0]
		self.assertEqual(context.reference_doc["title"], "prefill@example.com")
		self.assertNotEqual(context.reference_doc.get("signer_email"), "prefill@example.com")

	def test_guest_without_key_is_refused(self):
		frappe.set_user("Guest")
		content = self.render()
		self.assertNotIn("esign-layout", content)

	def test_owner_without_key_gets_the_signing_page(self):
		# A portal user opening their own record from the web form list, as accept allows.
		self.doc.db_set("owner", OUTSIDER)
		frappe.set_user(OUTSIDER)
		self.assertIn("esign-layout", self.render())

	def test_user_without_key_or_permission_is_refused(self):
		frappe.set_user(OUTSIDER)
		self.assertNotIn("esign-layout", self.render())

	def test_completed_document_links_the_signed_pdf(self):
		self.doc.db_set("signature", SIGNATURE)
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{self.doc.name}_signed_1.pdf",
				"attached_to_doctype": TEST_DOCTYPE,
				"attached_to_name": self.doc.name,
				"is_private": 1,
				"content": PDF,
			}
		).insert(ignore_permissions=True)
		frappe.set_user("Guest")
		content = self.render(key=self.key)

		self.assertIn("esign-completed", content)
		self.assertIn("esign_webforms.esign.custom.web_form.download_signed_pdf", content)
		self.assertIn(f"docname={self.doc.name}", content)
		self.assertIn(f"web_form={self.web_form_name}", content)

	def test_force_mobile_adds_a_qr_code(self):
		self.web_form.db_set("esign_force_mobile", 1)
		frappe.set_user("Guest")
		content = self.render(key=self.key)
		self.assertIn("esign-force-mobile", content)
		self.assertIn("data:image/svg+xml;base64,", content)

	def test_disabled_esign_renders_the_standard_web_form(self):
		self.web_form.db_set("esign_enabled", 0)
		content = self.render()
		self.assertNotIn("esign-layout", content)


class TestEsignLink(EsignTestCase):
	def assert_valid_link(self, link: str) -> None:
		base = frappe.utils.get_url().rstrip("/")
		prefix = f"{base}/{WEB_FORM_ROUTE}/{self.doc.name}/edit?key="
		self.assertTrue(link.startswith(prefix), link)
		key = link.removeprefix(prefix).split("&")[0]
		frappe.set_user("Guest")
		self.assertTrue(validate_esign_key(key, get_agreement(self.doc.name)))
		frappe.set_user("Administrator")

	def test_link_carries_key_format_and_email(self):
		link = get_esign_link(self.doc, self.web_form_name, "Standard", "a+b@example.com")
		self.assert_valid_link(link)
		self.assertIn("&format=Standard", link)
		self.assertIn("&email=a%2Bb%40example.com", link)

	def test_recipient_email_is_bound_to_the_document(self):
		from urllib.parse import parse_qs, urlparse

		link = get_esign_link(self.doc, self.web_form_name, "", " a+b@example.com ")
		params = parse_qs(urlparse(link).query)
		self.assertEqual(params["email"], ["a+b@example.com"])
		self.assertEqual(
			params[EMAIL_BINDING_PARAM],
			[make_email_binding(TEST_DOCTYPE, str(self.doc.name), "a+b@example.com")],
		)
		self.assertEqual(
			get_bound_email(TEST_DOCTYPE, self.doc.name, params["email"][0], params[EMAIL_BINDING_PARAM][0]),
			"a+b@example.com",
		)

	def test_no_binding_without_one_valid_recipient(self):
		self.assertNotIn(EMAIL_BINDING_PARAM, get_esign_link(self.doc, self.web_form_name))
		for email in ("not an email", "a@example.com, b@example.com"):
			with self.subTest(email=email):
				link = get_esign_link(self.doc, self.web_form_name, "", email)
				self.assertIn("&email=", link)
				self.assertNotIn(EMAIL_BINDING_PARAM, link)
		# send_esign_email asks for no binding when others get the same message.
		link = esign_web_form.build_esign_link(self.doc, self.web_form_name, "", SIGNER, bind=False)
		self.assertIn("&email=", link)
		self.assertNotIn(EMAIL_BINDING_PARAM, link)

	def test_link_from_a_request_payload(self):
		payload = json.dumps({"doctype": TEST_DOCTYPE, "name": self.doc.name})
		self.assert_valid_link(get_esign_link(payload, self.web_form_name))

	def test_request_payload_never_gets_a_binding(self):
		# Over HTTP the caller, not the recipient, holds the link: a binding would let anyone
		# with email permission sign as any address, verified.
		for payload in (
			json.dumps({"doctype": TEST_DOCTYPE, "name": self.doc.name}),
			{"doctype": TEST_DOCTYPE, "name": self.doc.name},
		):
			with self.subTest(payload=type(payload).__name__):
				link = get_esign_link(payload, self.web_form_name, "", SIGNER)
				self.assert_valid_link(link)
				self.assertIn("&email=", link)
				self.assertNotIn(EMAIL_BINDING_PARAM, link)
		self.assertIn(EMAIL_BINDING_PARAM, get_esign_link(self.doc, self.web_form_name, "", SIGNER))

	def test_strip_email_binding(self):
		link = get_esign_link(self.doc, self.web_form_name, "Standard", SIGNER)
		stripped = esign_web_form.strip_email_binding(link)
		self.assertNotIn(EMAIL_BINDING_PARAM, stripped)
		self.assertEqual(stripped, link.split(f"&{EMAIL_BINDING_PARAM}=")[0])
		unbound = get_esign_link(self.doc, self.web_form_name)
		self.assertEqual(esign_web_form.strip_email_binding(unbound), unbound)

	def test_request_payload_needs_email_permission(self):
		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			get_esign_link({"doctype": TEST_DOCTYPE, "name": self.doc.name}, self.web_form_name)

	def test_bad_payloads_return_the_error(self):
		self.assertTrue(get_esign_link("{not json", self.web_form_name))
		self.assertIn("not found", get_esign_link({"doctype": TEST_DOCTYPE, "name": "missing"}, "x").lower())

	def test_no_link_for_a_form_that_does_not_match(self):
		self.web_form.db_set("esign_enabled", 0)
		self.assertEqual(get_esign_link(self.doc, self.web_form_name), "")
		self.assertEqual(get_esign_link(self.doc, "No Such Web Form"), "")

	def test_web_forms_for_a_doctype(self):
		forms = get_esign_web_forms(TEST_DOCTYPE)
		self.assertEqual([f.name for f in forms], [self.web_form_name])
		self.assertEqual(get_esign_web_forms("ToDo"), [])


class TestPrintHtml(EsignTestCase):
	def test_guest_with_key_gets_the_print_html(self):
		frappe.set_user("Guest")
		result = get_print_html(TEST_DOCTYPE, self.doc.name, key=self.key)
		self.assertIn("Service agreement", result["print_html"])
		self.assertIn("print_style", result)
		self.assertEqual(frappe.form_dict.key, self.key)

	def test_guest_without_key_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_print_html(TEST_DOCTYPE, self.doc.name)
		self.assertFalse(frappe.flags.ignore_print_permissions)

	def test_guest_with_a_wrong_key_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_print_html(TEST_DOCTYPE, self.doc.name, key="wrong")

	def test_user_with_print_permission_needs_no_key(self):
		result = get_print_html(TEST_DOCTYPE, self.doc.name)
		self.assertIn("Service agreement", result["print_html"])

	def test_owner_without_key_gets_the_print_html_through_the_web_form(self):
		# The keyless owner the signing page admits must also get its preview.
		self.doc.db_set("owner", OUTSIDER)
		frappe.set_user(OUTSIDER)
		result = get_print_html(TEST_DOCTYPE, self.doc.name, web_form=self.web_form_name)
		self.assertIn("Service agreement", result["print_html"])

		# Without the web form, the owner has no print permission.
		frappe.flags.ignore_print_permissions = False
		with self.assertRaises(frappe.PermissionError):
			get_print_html(TEST_DOCTYPE, self.doc.name)

	def test_web_form_does_not_admit_other_users(self):
		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			get_print_html(TEST_DOCTYPE, self.doc.name, web_form=self.web_form_name)

	def test_only_an_esign_web_form_for_the_doctype_admits(self):
		self.doc.db_set("owner", OUTSIDER)
		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			get_print_html(TEST_DOCTYPE, self.doc.name, web_form="no-such-web-form")

		frappe.set_user("Administrator")
		self.web_form.db_set("esign_enabled", 0)
		frappe.clear_document_cache("Web Form", self.web_form_name)
		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			get_print_html(TEST_DOCTYPE, self.doc.name, web_form=self.web_form_name)

	def test_guest_gets_nothing_from_the_web_form(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_print_html(TEST_DOCTYPE, self.doc.name, web_form=self.web_form_name)


class TestDownloadSignedPdf(EsignTestCase):
	def attach_signed_pdf(self, **kwargs: Any):
		return frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{self.doc.name}_signed_1.pdf",
				"attached_to_doctype": TEST_DOCTYPE,
				"attached_to_name": self.doc.name,
				"content": PDF,
				"is_private": 1,
				**kwargs,
			}
		).insert(ignore_permissions=True)

	def test_guest_needs_a_key(self):
		self.attach_signed_pdf()
		frappe.set_user("Guest")
		with signing_request(method="GET"), self.assertRaises(frappe.PermissionError):
			download_signed_pdf(TEST_DOCTYPE, self.doc.name)

	def test_user_without_key_needs_print_permission(self):
		self.attach_signed_pdf(is_private=0)
		frappe.set_user(OUTSIDER)
		with signing_request(method="GET"), self.assertRaises(frappe.PermissionError):
			download_signed_pdf(TEST_DOCTYPE, self.doc.name)

		frappe.set_user(SIGNER)
		with signing_request(method="GET"):
			download_signed_pdf(TEST_DOCTYPE, self.doc.name)
		self.assertEqual(frappe.local.response["type"], "redirect")

	def test_owner_without_key_downloads_through_the_web_form(self):
		file = self.attach_signed_pdf(is_private=0)
		self.doc.db_set("owner", OUTSIDER)
		frappe.set_user(OUTSIDER)
		with signing_request(method="GET"), self.assertRaises(frappe.PermissionError):
			download_signed_pdf(TEST_DOCTYPE, self.doc.name)
		with signing_request(method="GET"):
			download_signed_pdf(TEST_DOCTYPE, self.doc.name, web_form=self.web_form_name)
		self.assertEqual(frappe.local.response["type"], "redirect")
		self.assertEqual(frappe.local.response["location"], file.file_url)

	def test_guest_needs_a_key_even_with_the_web_form(self):
		self.attach_signed_pdf()
		frappe.set_user("Guest")
		with signing_request(method="GET"), self.assertRaises(frappe.PermissionError):
			download_signed_pdf(TEST_DOCTYPE, self.doc.name, web_form=self.web_form_name)

	def test_no_signed_pdf(self):
		with signing_request(method="GET"), self.assertRaises(frappe.DoesNotExistError):
			download_signed_pdf(TEST_DOCTYPE, self.doc.name, key=self.key)

	def test_private_file_is_sent_and_logged(self):
		file = self.attach_signed_pdf()
		frappe.set_user("Guest")
		with (
			signing_request(method="GET"),
			patch("frappe.utils.response.send_private_file", return_value="sent") as send,
		):
			self.assertEqual(download_signed_pdf(TEST_DOCTYPE, self.doc.name, key=self.key), "sent")
		self.assertTrue(send.call_args.args[0].startswith("/files/"))
		self.assertTrue(
			frappe.db.exists("Access Log", {"export_from": "File", "reference_document": file.name})
		)

	def test_public_file_redirects(self):
		file = self.attach_signed_pdf(is_private=0)
		with signing_request(method="GET"):
			download_signed_pdf(TEST_DOCTYPE, self.doc.name, key=self.key)
		self.assertEqual(frappe.local.response["type"], "redirect")
		self.assertEqual(frappe.local.response["location"], file.file_url)

	def test_cloud_storage_file_redirects_to_a_stored_sharing_link(self):
		file = self.attach_signed_pdf()
		frappe.db.set_value(
			"File", file.name, "file_url", "/api/method/retrieve?key=abc", update_modified=False
		)
		stored: dict[str, str] = {}
		full_file = MagicMock()
		full_file.get.return_value = None
		full_file.db_set.side_effect = lambda field, value: stored.__setitem__(field, value)
		real_get_doc = frappe.get_doc

		def get_doc(*args: Any, **kwargs: Any):
			if args == ("File", file.name):
				return full_file
			return real_get_doc(*args, **kwargs)

		frappe.local.flags.commit = False
		with signing_request(method="GET"), patch("frappe.get_doc", side_effect=get_doc):
			download_signed_pdf(TEST_DOCTYPE, self.doc.name, key=self.key)

		self.assertEqual(frappe.local.response["type"], "redirect")
		self.assertEqual(frappe.local.response["location"], f"/api/method/share?key={stored['sharing_link']}")
		self.assertTrue(frappe.local.flags.commit)

		# An existing link is reused, not replaced.
		full_file.get.return_value = "1234"
		full_file.db_set.reset_mock()
		with signing_request(method="GET"), patch("frappe.get_doc", side_effect=get_doc):
			download_signed_pdf(TEST_DOCTYPE, self.doc.name, key=self.key)
		self.assertEqual(frappe.local.response["location"], "/api/method/share?key=1234")
		full_file.db_set.assert_not_called()
		frappe.local.flags.commit = False


def make_notification(**kwargs: Any):
	name = "eSign Test Signed"
	if frappe.db.exists("Notification", name):
		frappe.delete_doc("Notification", name, force=True, ignore_permissions=True)
	return frappe.get_doc(
		{
			"doctype": "Notification",
			"name": name,
			"subject": "Signed: {{ doc.title }}",
			"document_type": TEST_DOCTYPE,
			"event": "Custom",
			"channel": "Email",
			"enabled": 1,
			"message": "<p>{{ doc.name }} was signed</p>",
			"recipients": [{"receiver_by_document_field": "signer_email"}],
			**kwargs,
		}
	).insert(ignore_permissions=True)


class TestAccept(EsignTestCase):
	"""accept: the signature flow and its Guest session switch."""

	def accept(self, data: str, key: str | None = None, consent: Any = 1, link: str = "", **request: Any):
		"""Post data to accept from the signing page; link adds the page's other parameters
		(email, email_sig) to the referrer."""
		referrer = None
		if key or link:
			referrer = f"https://example.com/{WEB_FORM_ROUTE}/{self.doc.name}/edit?key={key or ''}{link}"
		with signing_request(referrer=referrer, **request), patch("frappe.enqueue") as enqueue:
			result = accept(self.web_form_name, data, esign_consent=consent)
		return result, enqueue

	def test_guest_with_key_signs_and_queues_the_signed_pdf(self):
		frappe.set_user("Guest")
		result, enqueue = self.accept(
			form_data(self.doc, signature=SIGNATURE, signer_email="signer@example.com"),
			key=self.key,
			headers={"User-Agent": "TestBrowser/1.0", "X-Forwarded-For": "203.0.113.9, 10.0.0.1"},
		)

		self.doc.reload()
		self.assertEqual(self.doc.signature, SIGNATURE)
		self.assertEqual(self.doc.signer_email, "signer@example.com")
		self.assertEqual(result.name, self.doc.name)
		self.assertEqual(frappe.session.user, "Guest")
		self.assertIs(frappe.flags.web_form_doc, result)

		job = enqueue.call_args
		self.assertIs(job.args[0], attach_print_to_document)
		self.assertEqual(job.kwargs["print_format"], "standard")
		self.assertTrue(job.kwargs["enqueue_after_commit"])
		self.assertEqual(job.kwargs["request_data"]["headers"]["User-Agent"], "TestBrowser/1.0")
		audit = job.kwargs["audit_data"]
		self.assertEqual(audit["ip_address"], "203.0.113.9")
		self.assertEqual(audit["user_agent"], "TestBrowser/1.0")
		self.assertEqual(audit["signer_email"], "signer@example.com")
		self.assertEqual(audit["signed_fields"], ["Signature"])
		self.assertEqual(audit["web_form"], "eSign Test Agreement")
		self.assertIsNone(job.kwargs["notification_name"])

	def test_guest_without_key_cannot_update(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			self.accept(form_data(self.doc, signature=SIGNATURE))
		self.doc.reload()
		self.assertFalse(self.doc.signature)

	def test_guest_with_wrong_key_cannot_update(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			self.accept(form_data(self.doc, signature=SIGNATURE), key="wrong")

	def test_user_without_permission_cannot_update(self):
		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			self.accept(form_data(self.doc, signature=SIGNATURE))

	def test_user_with_doctype_write_permission_updates_without_key(self):
		# SIGNER is neither the owner nor holds a key, but their role may write the doctype.
		frappe.set_user(SIGNER)
		self.accept(form_data(self.doc, signature=SIGNATURE))
		self.doc.reload()
		self.assertEqual(self.doc.signature, SIGNATURE)

	def test_owner_updates_without_key(self):
		self.doc.db_set("owner", OUTSIDER)
		frappe.set_user(OUTSIDER)
		self.accept(form_data(self.doc, signature=SIGNATURE))
		self.doc.reload()
		self.assertEqual(self.doc.signature, SIGNATURE)

	def test_anonymous_form_saves_as_guest_and_restores_the_user(self):
		self.web_form.db_set("anonymous", 1)
		frappe.set_user(SIGNER)
		seen: list[str] = []
		original_save = Document.save

		def save(doc, *args: Any, **kwargs: Any):
			seen.append(frappe.session.user)
			return original_save(doc, *args, **kwargs)

		with patch.object(Document, "save", save):
			self.accept(form_data(self.doc, signature=SIGNATURE), key=self.key)

		self.assertEqual(seen[0], "Guest")
		self.assertEqual(frappe.session.user, SIGNER)

	def test_anonymous_form_restores_the_user_when_saving_fails(self):
		self.web_form.db_set("anonymous", 1)
		frappe.set_user(SIGNER)
		with (
			patch.object(Document, "save", side_effect=frappe.ValidationError("boom")),
			self.assertRaises(frappe.ValidationError),
		):
			self.accept(form_data(self.doc, signature=SIGNATURE), key=self.key)
		self.assertEqual(frappe.session.user, SIGNER)

	def test_submit_on_response_and_update_field(self):
		self.web_form.db_set(
			{"esign_submit_on_response": 1, "esign_update_field": "status", "esign_update_value": "Signed"}
		)
		frappe.set_user("Guest")
		self.accept(form_data(self.doc, signature=SIGNATURE), key=self.key)

		self.doc.reload()
		self.assertEqual(self.doc.docstatus, 1)
		self.assertEqual(self.doc.status, "Signed")

	def test_update_field_of_an_unsupported_type_is_left_alone(self):
		self.web_form.db_set({"esign_update_field": "rating", "esign_update_value": "5"})
		self.accept(form_data(self.doc, signature=SIGNATURE))
		self.doc.reload()
		self.assertEqual(self.doc.rating, 0)

	def test_update_field_failure_is_logged(self):
		self.web_form.db_set({"esign_update_field": "status", "esign_update_value": "Signed"})
		real_has_field = Meta.has_field

		def has_field(meta, fieldname: str) -> bool:
			if meta.name == TEST_DOCTYPE and fieldname == "status":
				raise RuntimeError("meta")
			return real_has_field(meta, fieldname)

		with patch.object(Meta, "has_field", has_field):
			self.accept(form_data(self.doc, signature=SIGNATURE))
		self.doc.reload()
		self.assertEqual(self.doc.signature, SIGNATURE)
		self.assertTrue(
			frappe.db.exists("Error Log", {"method": ("like", "eSign: Failed to set field status%")})
		)

	def test_updates_need_allow_edit(self):
		web_form = self.reload_web_form()
		web_form.allow_edit = 0
		with patch("frappe.get_lazy_doc", return_value=web_form), self.assertRaises(frappe.ValidationError):
			self.accept(form_data(self.doc, signature=SIGNATURE))

	def test_new_document_from_the_form(self):
		data = json.dumps(
			{"doctype": TEST_DOCTYPE, "signature": SIGNATURE, "signer_email": "new@example.com"}
		)
		frappe.set_user("Guest")
		result, enqueue = self.accept(data)
		self.assertTrue(frappe.db.exists(TEST_DOCTYPE, result.name))
		self.assertEqual(enqueue.call_count, 1)

	def test_new_document_needs_login_when_the_form_does(self):
		self.web_form.db_set("login_required", 1)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.ValidationError):
			self.accept(json.dumps({"doctype": TEST_DOCTYPE, "signature": SIGNATURE}))

	def test_attachments_are_saved_replaced_and_removed(self):
		self.web_form.append(
			"web_form_fields", {"fieldname": "attachment", "fieldtype": "Attach", "label": "File"}
		)
		self.web_form.save(ignore_permissions=True)

		self.accept(form_data(self.doc, attachment="notes.txt,data:text/plain;base64,aGVsbG8="))
		self.doc.reload()
		first_url = self.doc.attachment
		self.assertTrue(first_url)
		self.assertTrue(frappe.db.exists("File", {"file_url": first_url, "attached_to_name": self.doc.name}))

		# frappe also records an attach field's File on save, so each upload has two rows;
		# replacing or clearing the field removes one of them.
		def files(url: str | None) -> int:
			return frappe.db.count("File", {"file_url": url, "attached_to_name": self.doc.name})

		first_count = files(first_url)
		self.accept(form_data(self.doc, attachment="more.txt,data:text/plain;base64,d29ybGQ="))
		self.doc.reload()
		self.assertNotEqual(self.doc.attachment, first_url)
		self.assertLess(files(first_url), first_count)

		second_url = self.doc.attachment
		second_count = files(second_url)
		self.accept(form_data(self.doc, attachment=""))
		self.doc.reload()
		self.assertFalse(self.doc.attachment)
		self.assertLess(files(second_url), second_count)

	def test_new_document_with_an_attachment(self):
		self.web_form.append(
			"web_form_fields", {"fieldname": "attachment", "fieldtype": "Attach", "label": "File"}
		)
		self.web_form.save(ignore_permissions=True)
		data = json.dumps(
			{"doctype": TEST_DOCTYPE, "attachment": "notes.txt,data:text/plain;base64,aGVsbG8="}
		)
		result, _enqueue = self.accept(data)
		self.assertTrue(frappe.db.get_value(TEST_DOCTYPE, result.name, "attachment"))

	def test_form_without_esign_uses_frappes_accept(self):
		self.web_form.db_set("esign_enabled", 0)
		with patch("frappe.website.doctype.web_form.web_form.accept", return_value="base") as base:
			result, _enqueue = self.accept(form_data(self.doc, signature=SIGNATURE))
		self.assertEqual(result, "base")
		self.assertEqual(json.loads(base.call_args.args[1])["name"], self.doc.name)

	def test_signer_email_resolution(self):
		wf = self.reload_web_form()
		self.doc.signer_email = "field@example.com"

		with signing_request(referrer="https://example.com/form?email=param%40example.com"):
			self.assertEqual(
				esign_web_form._collect_audit_data(self.doc, wf, "Standard")["signer_email"],
				"param@example.com",
			)
		# An email parameter that is not a single valid address is not recorded.
		with signing_request(referrer="https://example.com/form?email=%3Cimg%20src%3Dx%3E"):
			self.assertEqual(
				esign_web_form._collect_audit_data(self.doc, wf, "Standard")["signer_email"],
				"field@example.com",
			)
		with signing_request():
			self.assertEqual(
				esign_web_form._collect_audit_data(self.doc, wf, "Standard")["signer_email"],
				"field@example.com",
			)

		self.doc.signer_email = None
		frappe.set_user(SIGNER)
		with signing_request():
			audit = esign_web_form._collect_audit_data(self.doc, wf, "Standard")
		self.assertEqual(audit["signer_email"], SIGNER)
		self.assertEqual(audit["signer_name"], "esign-signer")

		frappe.set_user("Guest")
		with signing_request():
			audit = esign_web_form._collect_audit_data(self.doc, wf, "Standard")
		self.assertIsNone(audit["signer_email"])
		self.assertEqual(audit["ip_address"], "127.0.0.1")
		self.assertIsNone(audit["user_agent"])

	def test_guest_signer_name_and_email_come_from_the_signer_fields(self):
		add_signer_fields(self.reload_web_form())
		frappe.set_user("Guest")
		result, enqueue = self.accept(
			form_data(
				self.doc,
				signature=SIGNATURE,
				signer_name="  Ana   Torres ",
				signer_email="ana.torres@example.com",
			),
			key=self.key,
		)
		self.assertEqual(result.signer_name, "  Ana   Torres ")
		audit = enqueue.call_args.kwargs["audit_data"]
		self.assertEqual(audit["signer_name"], "Ana Torres")
		self.assertEqual(audit["signer_email"], "ana.torres@example.com")

	def test_signer_fields_are_not_overridden_by_the_link(self):
		add_signer_fields(self.reload_web_form())
		wf = self.reload_web_form()
		self.doc.signer_name = "Ana Torres"
		self.doc.signer_email = "ana.torres@example.com"
		frappe.set_user("Guest")
		# The link's email parameter does not replace what the signer submitted.
		with signing_request(referrer="https://example.com/form?email=param%40example.com"):
			audit = esign_web_form._collect_audit_data(self.doc, wf, "Standard")
		self.assertEqual(audit["signer_email"], "ana.torres@example.com")
		self.assertEqual(audit["signer_name"], "Ana Torres")

		# Nor does it fill in for an invalid or empty address in the signer email field.
		for value in ("not an email", "a@example.com, b@example.com", None):
			with self.subTest(value=value):
				self.doc.signer_email = value
				with signing_request(referrer="https://example.com/form?email=param%40example.com"):
					audit = esign_web_form._collect_audit_data(self.doc, wf, "Standard")
				self.assertIsNone(audit["signer_email"])
				self.assertEqual(audit["signer_name"], "Ana Torres")

	def test_signer_fields_fall_back_when_empty_or_unset(self):
		add_signer_fields(self.reload_web_form())
		wf = self.reload_web_form()
		# An empty name field records no name, not the User the signer's email belongs to.
		self.doc.signer_name = "   "
		self.doc.signer_email = SIGNER
		with signing_request():
			audit = esign_web_form._collect_audit_data(self.doc, wf, "Standard")
		self.assertEqual(audit["signer_email"], SIGNER)
		self.assertIsNone(audit["signer_name"])

		# An empty email field falls back to the logged-in user.
		self.doc.signer_email = None
		frappe.set_user(SIGNER)
		with signing_request():
			audit = esign_web_form._collect_audit_data(self.doc, wf, "Standard")
		self.assertEqual(audit["signer_email"], SIGNER)

		# A long name is cut to what the Communication's sender name holds.
		self.doc.signer_name = "A" * 300
		with signing_request():
			audit = esign_web_form._collect_audit_data(self.doc, wf, "Standard")
		self.assertEqual(audit["signer_name"], "A" * esign_web_form.SIGNER_NAME_LENGTH)

		# A setting naming a field the form no longer has is ignored, as if unset.
		frappe.set_user("Guest")
		wf.web_form_fields = [row for row in wf.web_form_fields if row.get("fieldname") != "signer_name"]
		wf.esign_signer_email_field = "title"
		self.doc.signer_name = "Ana Torres"
		self.doc.title = "ana.torres@example.com"
		self.doc.signer_email = "field@example.com"
		with signing_request(referrer="https://example.com/form?email=param%40example.com"):
			audit = esign_web_form._collect_audit_data(self.doc, wf, "Standard")
		self.assertEqual(audit["signer_email"], "param@example.com")
		self.assertIsNone(audit["signer_name"])

	def test_client_ip_headers_in_order(self):
		with signing_request(headers={"CF-Connecting-IP": "198.51.100.1", "X-Real-IP": "198.51.100.2"}):
			self.assertEqual(esign_web_form._get_client_ip(), "198.51.100.1")
		with signing_request(headers={"X-Real-IP": " 198.51.100.2 "}):
			self.assertEqual(esign_web_form._get_client_ip(), "198.51.100.2")
		with signing_request():
			self.assertEqual(esign_web_form._get_client_ip(), "127.0.0.1")

	def test_print_format_and_notification_come_from_the_link_and_form(self):
		notification = make_notification()
		self.web_form.db_set({"esign_send_notification": 1, "esign_notification": notification.name})
		with (
			signing_request(referrer=f"https://example.com/x?key={self.key}&format=Signed%20Format"),
			patch("frappe.enqueue") as enqueue,
		):
			accept(self.web_form_name, form_data(self.doc, signature=SIGNATURE), esign_consent=1)
		self.assertEqual(enqueue.call_args.kwargs["print_format"], "Signed Format")
		self.assertEqual(enqueue.call_args.kwargs["notification_name"], notification.name)


class TestSigningJobs(EsignTestCase):
	"""attach_print_to_document and record_signature, the two background jobs."""

	def audit(self, **kwargs: Any) -> AuditData:
		values: dict[str, Any] = {
			"timestamp": "2026-10-16 12:00:00",
			"ip_address": "203.0.113.9",
			"user_agent": "<b>TestBrowser</b>",
			"signer_email": "signer@example.com",
			"signer_name": "Sam Signer",
			"signer_email_verified": True,
			"verified_via": "recipient link",
			"verified_email": "signer@example.com",
			"consent_text": "I agree to <sign> electronically.",
			"consent_timestamp": "2026-10-16 11:59:58",
			"web_form": "eSign Test Agreement",
			"print_format": "Standard",
			"signed_fields": ["Signature"],
		}
		values.update(kwargs)
		return cast(AuditData, values)

	def run_jobs(self, notification_name: str | None = None) -> MagicMock:
		frappe.local.request = None
		with (
			patch("frappe.attach_print", side_effect=fake_attach_print),
			patch("frappe.enqueue") as enqueue,
		):
			attach_print_to_document(
				self.doc, "Standard", REQUEST_DATA, self.audit(), notification_name=notification_name
			)
			self.assertIsNone(getattr(frappe.local, "request", None))
			job = enqueue.call_args
			self.assertIs(job.args[0], record_signature)
			self.assertTrue(job.kwargs["enqueue_after_commit"])
			record_signature(
				doctype=job.kwargs["doctype"],
				name=job.kwargs["name"],
				file_name=job.kwargs["file_name"],
				pdf_hash=job.kwargs["pdf_hash"],
				request_data=job.kwargs["request_data"],
				audit_data=job.kwargs["audit_data"],
				notification_name=job.kwargs["notification_name"],
			)
		return enqueue

	def test_signed_pdf_is_attached_and_recorded(self):
		self.doc.db_set("signer_email", "signer@example.com")
		self.run_jobs()

		files = frappe.get_all(
			"File",
			filters={"attached_to_doctype": TEST_DOCTYPE, "attached_to_name": self.doc.name},
			fields=["name", "file_name", "is_private", "content_hash"],
		)
		self.assertEqual(len(files), 1)
		self.assertTrue(files[0].file_name.startswith(f"{self.doc.name}_signed_"))
		self.assertTrue(files[0].is_private)

		comm = frappe.get_last_doc(
			"Communication", filters={"reference_name": self.doc.name, "communication_type": "eSign"}
		)
		audit = json.loads(comm.content)
		self.assertEqual(audit["signer_email"], "signer@example.com")
		self.assertEqual(audit["file_name"], files[0].file_name)
		self.assertEqual(len(audit["pdf_hash"]), 64)
		self.assertEqual(comm.sender, "signer@example.com")
		self.assertEqual(audit["signer_name"], "Sam Signer")
		self.assertEqual(comm.sender_full_name, "Sam Signer")

		copy = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Communication", "attached_to_name": comm.name},
			fields=["content_hash"],
		)
		self.assertEqual(copy[0].content_hash, files[0].content_hash)

	def test_request_is_restored_after_the_job(self):
		sentinel = frappe._dict(headers={})
		frappe.local.request = sentinel
		with esign_web_form._job_request(REQUEST_DATA):
			self.assertEqual(frappe.local.request.host, "erp.example.com")
		self.assertIs(frappe.local.request, sentinel)

	def test_notification_is_sent_with_the_signed_pdf_and_audit_trail(self):
		notification = make_notification(set_property_after_alert="status", property_value="Notified")
		self.doc.db_set("signer_email", "signer@example.com")
		with patch("frappe.sendmail") as sendmail:
			self.run_jobs(notification.name)

		mail = sendmail.call_args.kwargs
		self.assertEqual(mail["recipients"], ["signer@example.com"])
		self.assertEqual(mail["subject"], "Signed: Service agreement")
		self.assertIn(f"{self.doc.name} was signed", mail["message"])
		self.assertIn("eSign Audit Trail", mail["message"])
		self.assertIn("Sam Signer", mail["message"])
		self.assertIn("&lt;b&gt;TestBrowser&lt;/b&gt;", mail["message"])
		self.assertNotIn("<b>TestBrowser</b>", mail["message"])
		self.assertIn("PDF SHA-256", mail["message"])
		self.assertIn("Email verified via recipient link", mail["message"])
		self.assertIn("I agree to &lt;sign&gt; electronically.", mail["message"])
		self.assertIn("Consent Given At", mail["message"])
		self.assertIn("2026-10-16 11:59:58", mail["message"])
		self.assertTrue(mail["attachments"][0]["file_url"].startswith("/private/files/"))
		self.assertTrue(mail["communication"])
		self.assertEqual(frappe.db.get_value(TEST_DOCTYPE, self.doc.name, "status"), "Notified")

	def test_notification_numeric_property_and_sender(self):
		notification = make_notification(
			set_property_after_alert="rating",
			property_value="4",
			sender=make_email_account(),
			sender_email="sales@example.com",
		)
		self.doc.db_set("signer_email", "signer@example.com")
		with patch("frappe.sendmail") as sendmail:
			esign_web_form._send_esign_notification(
				notification.name, self.doc, MagicMock(file_url="/files/x.pdf")
			)
		self.assertEqual(sendmail.call_args.kwargs["sender"], "eSign Test Outgoing <sales@example.com>")
		self.assertNotIn("eSign Audit Trail", sendmail.call_args.kwargs["message"])
		self.assertEqual(frappe.db.get_value(TEST_DOCTYPE, self.doc.name, "rating"), 4)

	def test_notification_property_update_failure_is_logged(self):
		notification = make_notification(set_property_after_alert="status", property_value="Not An Option")
		self.doc.db_set("signer_email", "signer@example.com")
		with patch("frappe.sendmail"):
			esign_web_form._send_esign_notification(
				notification.name, self.doc, MagicMock(file_url="/files/x.pdf")
			)
		self.assertTrue(
			frappe.db.exists("Error Log", {"method": "eSign: Document update failed after notification"})
		)

	def test_notification_without_recipients_sends_nothing(self):
		notification = make_notification()
		with patch("frappe.sendmail") as sendmail:
			esign_web_form._send_esign_notification(
				notification.name, self.doc, MagicMock(file_url="/files/x.pdf")
			)
		sendmail.assert_not_called()

	def test_misconfigured_notifications_are_logged_and_skipped(self):
		cases = {
			"eSign: Notification doctype mismatch": {"document_type": "ToDo"},
			"eSign: Notification event not Custom": {"event": "New"},
			"eSign: Notification disabled": {"enabled": 0},
			"eSign: Notification channel not Email": {"channel": "System Notification"},
		}
		for title, values in cases.items():
			with self.subTest(title):
				notification = make_notification(**values)
				with patch("frappe.sendmail") as sendmail:
					esign_web_form._send_esign_notification(
						notification.name, self.doc, MagicMock(file_url="/x")
					)
				sendmail.assert_not_called()
				self.assertTrue(frappe.db.exists("Error Log", {"method": title}))

	def test_notification_errors_are_logged(self):
		esign_web_form._send_esign_notification("No Such Notification", self.doc, MagicMock(file_url="/x"))
		self.assertTrue(
			frappe.db.exists(
				"Error Log",
				{"method": f"eSign: Failed to send notification for {TEST_DOCTYPE} {self.doc.name}"},
			)
		)

	def test_cloud_storage_file_gets_an_association(self):
		appended: list[tuple[str, dict]] = []

		def fake_insert(file_doc, *args: Any, **kwargs: Any):
			file_doc.name = "cloud-file"
			file_doc.file_url = "/api/method/retrieve?key=bucket/key.pdf"
			return file_doc

		cloud_file = MagicMock(file_name="x_signed.pdf")
		cloud_file.append.side_effect = lambda table, row: appended.append((table, row))
		real_get_doc = frappe.get_doc

		def get_doc(*args: Any, **kwargs: Any):
			if args == ("File", "cloud-file"):
				return cloud_file
			return real_get_doc(*args, **kwargs)

		with (
			patch.object(esign_web_form, "_is_cloud_storage_file", return_value=True),
			patch("frappe.core.doctype.file.file.File.insert", fake_insert),
			patch("frappe.core.doctype.file.file.File.db_set") as db_set,
			patch("frappe.get_doc", side_effect=get_doc),
		):
			self.run_jobs()

		db_set.assert_called_once_with("s3_key", "bucket/key.pdf")
		self.assertEqual(appended[0][0], "file_association")
		self.assertEqual(appended[0][1]["link_doctype"], "Communication")
		cloud_file.save.assert_called_once()


def bound_link(doc: Document, email: str, binding: str | None = None) -> str:
	"""The email and email_sig parameters of a link bound to email (or carrying binding)."""
	from urllib.parse import quote

	if binding is None:
		binding = make_email_binding(doc.doctype, str(doc.name), email)
	return f"&email={quote(email)}&{EMAIL_BINDING_PARAM}={binding}"


class TestEmailBinding(EsignTestCase):
	"""The HMAC that binds a recipient's email to the document in the signing link."""

	def test_valid_binding_returns_the_email(self):
		binding = make_email_binding(TEST_DOCTYPE, str(self.doc.name), SIGNER)
		self.assertEqual(len(binding), 64)
		self.assertEqual(get_bound_email(TEST_DOCTYPE, self.doc.name, SIGNER, binding), SIGNER)

	def test_binding_is_an_hmac_keyed_with_a_secret_derived_from_the_site_key(self):
		from frappe.utils.password import get_encryption_key

		key = hmac.new(
			get_encryption_key().encode(), b"esign_webforms:recipient-email-binding", hashlib.sha256
		).digest()
		message = f"{TEST_DOCTYPE}\x00{self.doc.name}\x00{SIGNER}".encode()
		self.assertEqual(
			make_email_binding(TEST_DOCTYPE, str(self.doc.name), SIGNER),
			hmac.new(key, message, hashlib.sha256).hexdigest(),
		)
		# Another site (another encryption key) makes another binding.
		with patch("frappe.utils.password.get_encryption_key", return_value="another-site-key"):
			other = make_email_binding(TEST_DOCTYPE, str(self.doc.name), SIGNER)
		self.assertNotEqual(other, make_email_binding(TEST_DOCTYPE, str(self.doc.name), SIGNER))

	def test_email_is_normalized(self):
		binding = make_email_binding(TEST_DOCTYPE, str(self.doc.name), " Esign-Signer@Example.COM ")
		self.assertEqual(binding, make_email_binding(TEST_DOCTYPE, str(self.doc.name), SIGNER))
		self.assertEqual(
			get_bound_email(TEST_DOCTYPE, self.doc.name, "Esign-Signer@Example.com", binding),
			"Esign-Signer@Example.com",
		)

	def test_tampered_binding_is_refused(self):
		binding = make_email_binding(TEST_DOCTYPE, str(self.doc.name), SIGNER)
		other_doc = make_agreement()
		tampered = ("0" if binding[0] != "0" else "1") + binding[1:]
		cases = {
			"another email": (self.doc.name, OUTSIDER, binding),
			"another document": (other_doc.name, SIGNER, binding),
			"a changed binding": (self.doc.name, SIGNER, tampered),
			"a shortened binding": (self.doc.name, SIGNER, binding[:32]),
			"a non-ASCII binding": (self.doc.name, SIGNER, "é" * 64),
		}
		for case, (docname, email, sig) in cases.items():
			with self.subTest(case):
				self.assertIsNone(get_bound_email(TEST_DOCTYPE, docname, email, sig))

	def test_missing_parts_are_refused(self):
		binding = make_email_binding(TEST_DOCTYPE, str(self.doc.name), SIGNER)
		self.assertIsNone(get_bound_email(TEST_DOCTYPE, self.doc.name, SIGNER, None))
		self.assertIsNone(get_bound_email(TEST_DOCTYPE, self.doc.name, SIGNER, ""))
		self.assertIsNone(get_bound_email(TEST_DOCTYPE, self.doc.name, "", binding))
		self.assertIsNone(get_bound_email(TEST_DOCTYPE, None, SIGNER, binding))
		# Not one valid address: never bound, whatever the binding.
		for email in ("not an email", f"{SIGNER}, {OUTSIDER}"):
			sig = make_email_binding(TEST_DOCTYPE, str(self.doc.name), email)
			self.assertIsNone(get_bound_email(TEST_DOCTYPE, self.doc.name, email, sig))

	def test_comparison_is_constant_time(self):
		binding = make_email_binding(TEST_DOCTYPE, str(self.doc.name), SIGNER)
		with patch.object(esign_web_form.hmac, "compare_digest", wraps=hmac.compare_digest) as compare:
			get_bound_email(TEST_DOCTYPE, self.doc.name, SIGNER, binding)
		compare.assert_called_once()


class TestVerifiedSigningPage(EsignTestCase):
	"""The signing page with a bound link, and with Require Verified Email."""

	def render_context(self, **form_dict: Any) -> tuple[str, Any]:
		"""The page's HTML and the context frappe's web form code received."""
		path = f"{WEB_FORM_ROUTE}/{self.doc.name}/edit"
		with (
			signing_request(path=path, method="GET", name=self.doc.name, **form_dict),
			patch("frappe.utils.get_assets_json", return_value={}),
			patch("frappe.website.doctype.web_form.web_form.WebForm.add_custom_context_and_script") as custom,
		):
			content = get_response_content(path)
		context = custom.call_args.args[0] if custom.call_args else None
		return content, context

	def link_params(self, email: str = SIGNER, binding: str | None = None) -> dict[str, str]:
		if binding is None:
			binding = make_email_binding(TEST_DOCTYPE, str(self.doc.name), email)
		return {"email": email, EMAIL_BINDING_PARAM: binding}

	def email_field(self, context: Any) -> dict:
		return next(
			field for field in context.web_form_doc["web_form_fields"] if field["fieldname"] == "signer_email"
		)

	def test_bound_link_prefills_the_email_and_says_it_is_verified(self):
		frappe.set_user("Guest")
		content, context = self.render_context(key=self.key, **self.link_params())
		self.assertIn("esign-layout", content)
		self.assertIn(f"Signing as {SIGNER}, verified by your email link", content)
		self.assertEqual(context.reference_doc["signer_email"], SIGNER)
		# Without Require Verified Email the signer can still change it.
		self.assertFalse(self.email_field(context).get("read_only"))

	def test_unbound_email_parameter_is_not_called_verified(self):
		frappe.set_user("Guest")
		content, context = self.render_context(key=self.key, email=SIGNER)
		self.assertIn("esign-layout", content)
		self.assertNotIn("verified by your email link", content)
		self.assertEqual(context.reference_doc["signer_email"], SIGNER)

	def test_required_verified_email_refuses_a_link_without_a_binding(self):
		self.web_form.db_set("esign_require_verified_email", 1)
		frappe.set_user("Guest")
		for params in ({}, {"email": SIGNER}):
			with self.subTest(params=params):
				content, _context = self.render_context(key=self.key, **params)
				self.assertNotIn("esign-layout", content)
				self.assertIn("can only be signed through the link emailed to its signer", content)

	def test_required_verified_email_refuses_a_tampered_link(self):
		self.web_form.db_set("esign_require_verified_email", 1)
		frappe.set_user("Guest")
		binding = make_email_binding(TEST_DOCTYPE, str(self.doc.name), SIGNER)
		for params in (
			self.link_params(email=OUTSIDER, binding=binding),
			self.link_params(binding=binding[:-1] + ("0" if binding[-1] != "0" else "1")),
		):
			with self.subTest(params=params):
				content, _context = self.render_context(key=self.key, **params)
				self.assertNotIn("esign-layout", content)
				self.assertIn("This signing link has been changed", content)

	def test_required_verified_email_also_needs_the_share_key(self):
		self.web_form.db_set("esign_require_verified_email", 1)
		frappe.set_user("Guest")
		content, _context = self.render_context(**self.link_params())
		self.assertNotIn("esign-layout", content)

	def test_required_verified_email_locks_the_email_field(self):
		self.web_form.db_set("esign_require_verified_email", 1)
		frappe.set_user("Guest")
		content, context = self.render_context(key=self.key, **self.link_params())
		self.assertIn("esign-layout", content)
		self.assertEqual(context.reference_doc["signer_email"], SIGNER)
		self.assertEqual(self.email_field(context)["read_only"], 1)

	def test_signer_email_field_is_the_one_locked(self):
		wf = self.reload_web_form()
		wf.append("web_form_fields", {"fieldname": "title", "fieldtype": "Data", "label": "Your Email"})
		wf.esign_require_verified_email = 1
		add_signer_fields(wf, name=None, email="title")
		frappe.set_user("Guest")
		_content, context = self.render_context(key=self.key, **self.link_params())
		fields = {field["fieldname"]: field for field in context.web_form_doc["web_form_fields"]}
		self.assertEqual(context.reference_doc["title"], SIGNER)
		self.assertEqual(fields["title"]["read_only"], 1)
		self.assertFalse(fields["signer_email"].get("read_only"))

	def test_consent_checkbox_with_default_and_custom_text(self):
		frappe.set_user("Guest")
		content, _context = self.render_context(key=self.key)
		self.assertIn('id="esign-consent"', content)
		self.assertIn("I agree to sign this document electronically.", content)

		frappe.set_user("Administrator")
		self.web_form.db_set("esign_consent_text", "I agree to <b>e-sign</b> & accept the terms.")
		frappe.set_user("Guest")
		content, _context = self.render_context(key=self.key)
		self.assertIn("I agree to &lt;b&gt;e-sign&lt;/b&gt; &amp; accept the terms.", content)
		self.assertNotIn("I agree to sign this document electronically.", content)


class TestVerifiedAccept(EsignTestCase):
	"""accept with a bound link, Require Verified Email and the consent to sign electronically."""

	def accept(self, data: str, consent: Any = 1, link: str = "", key: str | None = None):
		referrer = f"https://example.com/{WEB_FORM_ROUTE}/{self.doc.name}/edit?key={key or self.key}{link}"
		with signing_request(referrer=referrer), patch("frappe.enqueue") as enqueue:
			result = accept(self.web_form_name, data, esign_consent=consent)
		return result, enqueue

	def require_verified_email(self) -> None:
		self.web_form.db_set("esign_require_verified_email", 1)
		frappe.clear_document_cache("Web Form", self.web_form_name)

	def test_consent_is_required(self):
		frappe.set_user("Guest")
		for consent in (0, "0", "", None):
			with (
				self.subTest(consent=consent),
				self.assertRaisesRegex(frappe.ValidationError, "To sign, tick"),
			):
				self.accept(form_data(self.doc, signature=SIGNATURE), consent=consent)
		self.doc.reload()
		self.assertFalse(self.doc.signature)

	def test_consent_text_and_time_are_recorded(self):
		frappe.set_user("Guest")
		_result, enqueue = self.accept(form_data(self.doc, signature=SIGNATURE), consent="1")
		audit = enqueue.call_args.kwargs["audit_data"]
		self.assertEqual(audit["consent_text"], "I agree to sign this document electronically.")
		self.assertTrue(audit["consent_timestamp"])

		frappe.set_user("Administrator")
		self.web_form.db_set("esign_consent_text", "  I consent to electronic records and signatures.  ")
		frappe.set_user("Guest")
		_result, enqueue = self.accept(form_data(self.doc, signature=SIGNATURE))
		audit = enqueue.call_args.kwargs["audit_data"]
		self.assertEqual(audit["consent_text"], "I consent to electronic records and signatures.")

	def test_required_verified_email_refuses_a_missing_binding(self):
		self.require_verified_email()
		frappe.set_user("Guest")
		for link in ("", f"&email={SIGNER}"):
			with (
				self.subTest(link=link),
				self.assertRaisesRegex(frappe.PermissionError, "can only be signed through the link"),
			):
				self.accept(form_data(self.doc, signature=SIGNATURE), link=link)
		self.doc.reload()
		self.assertFalse(self.doc.signature)

	def test_required_verified_email_refuses_a_tampered_binding(self):
		self.require_verified_email()
		frappe.set_user("Guest")
		binding = make_email_binding(TEST_DOCTYPE, str(self.doc.name), SIGNER)
		with self.assertRaisesRegex(frappe.PermissionError, "has been changed"):
			self.accept(
				form_data(self.doc, signature=SIGNATURE), link=bound_link(self.doc, OUTSIDER, binding)
			)
		self.doc.reload()
		self.assertFalse(self.doc.signature)

	def test_frappes_own_accept_cannot_skip_the_signing_checks(self):
		# frappe's web form accept is whitelisted for guests as well. With only a share key it
		# must not save the document: it checks no consent, no binding and no locked email.
		from frappe.website.doctype.web_form.web_form import accept as frappe_accept

		self.require_verified_email()
		frappe.set_user("Guest")
		referrer = f"https://example.com/{WEB_FORM_ROUTE}/{self.doc.name}/edit?key={self.key}"
		for request in (signing_request(referrer=referrer), signing_request(key=self.key)):
			with request, self.assertRaises(frappe.PermissionError):
				frappe_accept(
					self.web_form_name, form_data(self.doc, signature=SIGNATURE, signer_email=OUTSIDER)
				)
		frappe.set_user("Administrator")
		self.doc.reload()
		self.assertFalse(self.doc.signature)
		self.assertNotEqual(self.doc.signer_email, OUTSIDER)

	def test_required_verified_email_refuses_a_new_document(self):
		self.require_verified_email()
		frappe.set_user("Guest")
		data = json.dumps({"doctype": TEST_DOCTYPE, "signature": SIGNATURE})
		with self.assertRaises(frappe.PermissionError):
			self.accept(data, link=bound_link(self.doc, SIGNER))

	def test_required_verified_email_ignores_a_changed_email(self):
		self.require_verified_email()
		frappe.set_user("Guest")
		_result, enqueue = self.accept(
			form_data(self.doc, signature=SIGNATURE, signer_email="someone.else@example.com"),
			link=bound_link(self.doc, SIGNER),
		)
		self.doc.reload()
		self.assertEqual(self.doc.signer_email, SIGNER)
		audit = enqueue.call_args.kwargs["audit_data"]
		self.assertEqual(audit["signer_email"], SIGNER)
		self.assertTrue(audit["signer_email_verified"])
		self.assertEqual(audit["verified_via"], "recipient link")
		self.assertEqual(audit["verified_email"], SIGNER)

	def test_required_verified_email_ignores_a_changed_signer_email_field(self):
		wf = self.reload_web_form()
		wf.esign_require_verified_email = 1
		add_signer_fields(wf)
		frappe.set_user("Guest")
		_result, enqueue = self.accept(
			form_data(self.doc, signature=SIGNATURE, signer_name="Sam Signer", signer_email=OUTSIDER),
			link=bound_link(self.doc, SIGNER),
		)
		self.doc.reload()
		self.assertEqual(self.doc.signer_email, SIGNER)
		audit = enqueue.call_args.kwargs["audit_data"]
		self.assertEqual(audit["signer_email"], SIGNER)
		self.assertEqual(audit["signer_name"], "Sam Signer")
		self.assertTrue(audit["signer_email_verified"])

	def test_bound_email_is_recorded_as_verified_without_the_setting(self):
		frappe.set_user("Guest")
		_result, enqueue = self.accept(
			form_data(self.doc, signature=SIGNATURE), link=bound_link(self.doc, SIGNER)
		)
		audit = enqueue.call_args.kwargs["audit_data"]
		self.assertEqual(audit["signer_email"], SIGNER)
		self.assertTrue(audit["signer_email_verified"])
		self.assertEqual(audit["verified_via"], "recipient link")

	def test_without_the_setting_a_changed_email_is_recorded_unverified(self):
		add_signer_fields(self.reload_web_form())
		frappe.set_user("Guest")
		_result, enqueue = self.accept(
			form_data(self.doc, signature=SIGNATURE, signer_email="typed@example.com"),
			link=bound_link(self.doc, SIGNER),
		)
		self.doc.reload()
		self.assertEqual(self.doc.signer_email, "typed@example.com")
		audit = enqueue.call_args.kwargs["audit_data"]
		self.assertEqual(audit["signer_email"], "typed@example.com")
		self.assertFalse(audit["signer_email_verified"])
		self.assertIsNone(audit["verified_via"])
		self.assertEqual(audit["verified_email"], SIGNER)

	def test_unbound_or_tampered_email_parameter_is_not_verified(self):
		frappe.set_user("Guest")
		binding = make_email_binding(TEST_DOCTYPE, str(self.doc.name), SIGNER)
		for link in (f"&email={SIGNER}", bound_link(self.doc, OUTSIDER, binding)):
			with self.subTest(link=link):
				_result, enqueue = self.accept(form_data(self.doc, signature=SIGNATURE), link=link)
				audit = enqueue.call_args.kwargs["audit_data"]
				self.assertFalse(audit["signer_email_verified"])
				self.assertIsNone(audit["verified_via"])
				self.assertIsNone(audit["verified_email"])


class TestSignerName(EsignTestCase):
	"""Only the name the signer typed is recorded, never a User's looked up by email."""

	def collect(self, wf: EsignWebForm) -> AuditData:
		with signing_request():
			return esign_web_form._collect_audit_data(self.doc, wf, "Standard")

	def test_guest_typing_a_users_email_is_not_named_after_that_user(self):
		frappe.set_user("Guest")
		# Without a Signer Name Field (the email comes from the form's Email field)...
		self.doc.signer_email = SIGNER
		audit = self.collect(self.reload_web_form())
		self.assertEqual(audit["signer_email"], SIGNER)
		self.assertIsNone(audit["signer_name"])

		# ...and with one left empty.
		add_signer_fields(self.reload_web_form())
		self.doc.signer_name = ""
		audit = self.collect(self.reload_web_form())
		self.assertEqual(audit["signer_email"], SIGNER)
		self.assertIsNone(audit["signer_name"])

	def test_bound_link_to_a_users_email_does_not_name_the_user(self):
		frappe.set_user("Guest")
		self.doc.signer_email = None
		with signing_request():
			audit = esign_web_form._collect_audit_data(
				self.doc, self.reload_web_form(), "Standard", bound_email=SIGNER
			)
		self.assertTrue(audit["signer_email_verified"])
		self.assertIsNone(audit["signer_name"])

	def test_logged_in_user_signing_as_themselves_without_a_name_field(self):
		frappe.set_user(SIGNER)
		self.doc.signer_email = None
		audit = self.collect(self.reload_web_form())
		self.assertEqual(audit["signer_email"], SIGNER)
		self.assertEqual(audit["signer_name"], "esign-signer")

		# Signing for another address is not signing as themselves.
		self.doc.signer_email = OUTSIDER
		audit = self.collect(self.reload_web_form())
		self.assertEqual(audit["signer_email"], OUTSIDER)
		self.assertIsNone(audit["signer_name"])

	def test_logged_in_user_with_an_empty_name_field_is_not_named(self):
		add_signer_fields(self.reload_web_form())
		frappe.set_user(SIGNER)
		self.doc.signer_name = None
		self.doc.signer_email = SIGNER
		audit = self.collect(self.reload_web_form())
		self.assertEqual(audit["signer_email"], SIGNER)
		self.assertIsNone(audit["signer_name"])

	def test_typed_name_is_recorded(self):
		add_signer_fields(self.reload_web_form())
		frappe.set_user(SIGNER)
		self.doc.signer_name = "Sam  Signer"
		self.doc.signer_email = SIGNER
		self.assertEqual(self.collect(self.reload_web_form())["signer_name"], "Sam Signer")


class TestVerificationRows(IntegrationTestCase):
	def test_rows_for_each_verification_state(self):
		self.assertEqual(
			esign_web_form.verification_rows(
				{"signer_email_verified": True, "verified_via": "recipient link"}
			),
			[("Verification", "Email verified via recipient link")],
		)
		self.assertEqual(
			esign_web_form.verification_rows(
				{"signer_email_verified": False, "verified_email": "a@example.com"}
			),
			[("Link Sent To", "a@example.com, verified via recipient link")],
		)
		self.assertEqual(esign_web_form.verification_rows({"signer_email": "a@example.com"}), [])
