# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""The desk side: sending a document for signature, the timeline, the hooks and install."""

import html
import json
import re
from typing import Any, cast
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import frappe
from frappe.core.doctype.communication.communication import Communication
from frappe.core.doctype.file.file import File
from frappe.model.base_document import get_controller
from frappe.tests import IntegrationTestCase

from esign_webforms.config import (
	add_field_options,
	after_install,
	after_migrate,
	after_uninstall,
	revert_field_options,
)
from esign_webforms.esign import can_esign, get_timeline_content, send_esign_email
from esign_webforms.esign.custom.email_template import EsignEmailTemplate, get_esign_email_templates
from esign_webforms.esign.custom.web_form import EsignWebForm, get_bound_email
from esign_webforms.tests.utils import (
	OUTSIDER,
	TEST_DOCTYPE,
	ensure_test_doctype,
	ensure_user,
	make_agreement,
	make_email_account,
	make_pdf,
	make_web_form,
)


def link_email(link: str, docname: str | None) -> str | None:
	"""The email a signing link binds to the test document, or None if it binds none."""
	params = parse_qs(urlparse(link).query)
	return get_bound_email(
		TEST_DOCTYPE, docname, (params.get("email") or [""])[0], (params.get("email_sig") or [""])[0]
	)


def communication_type_options() -> set[str]:
	return set((frappe.get_meta("Communication").get_field("communication_type").options or "").split("\n"))


class EsignDeskTestCase(IntegrationTestCase):
	def setUp(self) -> None:
		# Idempotent: the doctype and users are created once per site and kept.
		ensure_test_doctype()
		ensure_user(OUTSIDER)
		frappe.set_user("Administrator")
		self.web_form = make_web_form()
		self.doc = make_agreement()

	def tearDown(self) -> None:
		frappe.set_user("Administrator")


class TestHooks(EsignDeskTestCase):
	def test_controllers_are_extended_not_overridden(self):
		hooks = frappe.get_hooks(app_name="esign_webforms")
		self.assertEqual(
			hooks["extend_doctype_class"],
			{
				"Web Form": ["esign_webforms.esign.custom.web_form.EsignWebForm"],
				"Email Template": ["esign_webforms.esign.custom.email_template.EsignEmailTemplate"],
			},
		)
		self.assertNotIn("override_doctype_class", hooks)
		self.assertTrue(issubclass(get_controller("Web Form"), EsignWebForm))
		self.assertTrue(issubclass(get_controller("Email Template"), EsignEmailTemplate))

	def test_assets_are_named_as_their_bundles(self):
		hooks = frappe.get_hooks(app_name="esign_webforms")
		# .js entry names: --using-cached keys assets.json by the built file name, always .js.
		self.assertEqual(
			hooks["app_include_js"], ["esign_webforms.desk.bundle.js", "esign_webforms.control.bundle.js"]
		)
		self.assertEqual(
			hooks["app_include_css"], ["esign_webforms.control.bundle.css", "esign-fonts.bundle.css"]
		)

	def test_jinja_and_timeline_hooks(self):
		hooks = frappe.get_hooks(app_name="esign_webforms")
		self.assertIn("esign_webforms.esign.custom.web_form.get_esign_link", hooks["jinja"]["methods"])
		self.assertEqual(
			hooks["additional_timeline_content"]["*"], ["esign_webforms.esign.get_timeline_content"]
		)

	def test_esign_link_in_a_template(self):
		html = frappe.render_template(
			"{{ get_esign_link(doc, web_form) }}", {"doc": self.doc, "web_form": self.web_form.name}
		)
		self.assertIn(f"/esign-test-agreement/{self.doc.name}/edit?key=", html)


class TestCanEsign(EsignDeskTestCase):
	def test_enabled_by_a_published_esign_web_form(self):
		self.assertTrue(can_esign(TEST_DOCTYPE, self.doc.name))
		self.web_form.db_set("published", 0)
		self.assertFalse(can_esign(TEST_DOCTYPE, self.doc.name))

	def test_can_esign_hooks_decide(self):
		real_get_hooks = frappe.get_hooks

		def get_hooks(hook: str | None = None, *args: Any, **kwargs: Any):
			if hook == "can_esign":
				return {TEST_DOCTYPE: ["esign_webforms.tests.utils.allow_esign"]}
			return real_get_hooks(hook, *args, **kwargs)

		with patch("frappe.get_hooks", side_effect=get_hooks):
			self.assertTrue(can_esign(TEST_DOCTYPE, json.dumps({"title": "Allowed"})))
			self.assertFalse(can_esign(TEST_DOCTYPE, {"title": "Refused"}))


class TestSendEsignEmail(EsignDeskTestCase):
	def send(self, **kwargs: Any) -> dict:
		args: dict[str, Any] = {
			"doctype": TEST_DOCTYPE,
			"name": self.doc.name,
			"recipients": "signer@example.com, other@example.com",
			"subject": "Please sign",
			"message": "<p>Hello</p>",
			"web_form": self.web_form.name,
		}
		args.update(kwargs)
		with patch("frappe.sendmail") as sendmail:
			result = send_esign_email(**args)
		self.sendmail = sendmail
		return result

	def test_sends_the_link_and_records_a_communication(self):
		result = self.send(cc="cc@example.com", bcc=["bcc@example.com"], print_format="Standard")
		self.assertTrue(result["success"])
		self.assertIn(f"/esign-test-agreement/{self.doc.name}/edit?key=", result["esign_link"])
		self.assertIn("&format=Standard", result["esign_link"])

		comm = cast(Communication, frappe.get_doc("Communication", result["communication"]))
		self.assertEqual(comm.recipients, "signer@example.com, other@example.com")
		self.assertEqual(comm.cc, "cc@example.com")
		self.assertEqual(comm.bcc, "bcc@example.com")
		# The stored HTML escapes the link's "&".
		self.assertIn(result["esign_link"].split("&")[0], comm.content or "")

		mail = self.sendmail.call_args.kwargs
		self.assertTrue(mail["now"])
		self.assertIn(result["esign_link"], mail["content"])

	def sent_link(self, call: Any = None) -> str:
		"""The signing link in the email sendmail was (last) called with."""
		content = (call or self.sendmail.call_args).kwargs["content"]
		links = re.findall(r'href="([^"]*/edit\?key=[^"]+)"', content)
		self.assertEqual(len(links), 1, content)
		return html.unescape(links[0])

	def test_link_names_and_binds_a_single_recipient(self):
		result = self.send(recipients="Signer+1@example.com")
		link = self.sent_link()
		self.assertIn("&email=Signer%2B1%40example.com", link)
		self.assertEqual(link_email(link, self.doc.name), "Signer+1@example.com")
		# The sender's response names the recipient but carries no binding (see below).
		self.assertIn("&email=Signer%2B1%40example.com", result["esign_link"])
		self.assertIsNone(link_email(result["esign_link"], self.doc.name))

	def test_link_names_only_the_address_of_a_named_recipient(self):
		self.send(recipients="Dana Signer <dana@example.com>")
		link = self.sent_link()
		self.assertIn("&email=dana%40example.com&email_sig=", link)
		self.assertEqual(link_email(link, self.doc.name), "dana@example.com")

	def test_bound_link_reaches_only_the_recipient(self):
		# Whoever holds a bound link signs as its recipient, verified: neither the sender's
		# response nor the Communication, which anyone who reads the document can open,
		# may carry the binding. Only the email to the recipient does.
		for verified in (0, 1):
			with self.subTest(require_verified_email=verified):
				self.web_form.db_set("esign_require_verified_email", verified)
				result = self.send(recipients="signer@example.com")
				self.assertIn("email_sig=", self.sent_link())
				self.assertIn("&email=signer%40example.com", result["esign_link"])
				self.assertNotIn("email_sig", result["esign_link"])
				for name in result["communications"]:
					content = frappe.db.get_value("Communication", name, "content")
					self.assertIn("&amp;email=signer%40example.com", content)
					self.assertNotIn("email_sig", content)

	def test_link_to_several_recipients_names_none(self):
		result = self.send()
		self.assertNotIn("&email=", result["esign_link"])
		self.assertNotIn("email_sig", result["esign_link"])
		self.assertNotIn("email_sig", self.sent_link())

	def test_link_also_sent_to_others_is_not_bound(self):
		# Anyone else who gets the message could sign as the recipient with a bound link.
		for extra in ({"cc": "cc@example.com"}, {"bcc": "bcc@example.com"}, {"send_me_a_copy": 1}):
			with self.subTest(extra=extra):
				self.send(recipients="signer@example.com", **extra)
				self.assertIn("&email=signer%40example.com", self.sent_link())
				self.assertNotIn("email_sig", self.sent_link())
		self.send(recipients="signer@example.com", send_me_a_copy="0")
		self.assertIn("email_sig", self.sent_link())

	def test_verified_email_sends_each_recipient_their_own_link(self):
		self.web_form.db_set("esign_require_verified_email", 1)
		result = self.send(recipients="Ana <ana@example.com>, ben@example.com")

		self.assertEqual(self.sendmail.call_count, 2)
		self.assertEqual(len(result["communications"]), 2)
		self.assertEqual(result["communication"], result["communications"][0])
		sent = {}
		for call, name in zip(self.sendmail.call_args_list, result["communications"], strict=True):
			comm = cast(Communication, frappe.get_doc("Communication", name))
			sent[comm.recipients] = link_email(self.sent_link(call), self.doc.name)
			self.assertFalse(comm.cc)
			self.assertFalse(comm.bcc)
		self.assertEqual(
			sent, {"Ana <ana@example.com>": "ana@example.com", "ben@example.com": "ben@example.com"}
		)
		self.assertIn("&email=ana%40example.com", result["esign_link"])
		self.assertIsNone(link_email(result["esign_link"], self.doc.name))

	def test_verified_email_refuses_copies_and_bad_addresses(self):
		self.web_form.db_set("esign_require_verified_email", 1)
		for extra in ({"cc": "cc@example.com"}, {"bcc": ["bcc@example.com"]}, {"send_me_a_copy": True}):
			with (
				self.subTest(extra=extra),
				self.assertRaisesRegex(frappe.ValidationError, "own signing link"),
			):
				self.send(**extra)
		with (
			patch("frappe.sendmail") as sendmail,
			self.assertRaisesRegex(frappe.ValidationError, "not a valid email address"),
		):
			send_esign_email(
				doctype=TEST_DOCTYPE,
				name=str(self.doc.name),
				recipients="signer@example.com, not-an-address",
				subject="Please sign",
				message="<p>Hello</p>",
				web_form=str(self.web_form.name),
			)
		# Every address is checked before the first email goes out.
		sendmail.assert_not_called()

	def test_link_already_in_the_message_is_not_added_again(self):
		link = "https://example.com/already-there"
		with patch("esign_webforms.esign.custom.web_form.build_esign_link", return_value=link):
			result = self.send(message=f"<a href='{link}'>sign</a>", recipients=["signer@example.com"])
		content = frappe.db.get_value("Communication", result["communication"], "content")
		self.assertEqual(content.count(link), 1)
		self.assertNotIn("Sign Document", content)

	def test_copy_to_the_sender_and_email_account(self):
		frappe.db.set_value("User", "Administrator", "email", "admin@example.com")
		result = self.send(send_me_a_copy=True, email_account=make_email_account())
		comm = cast(Communication, frappe.get_doc("Communication", result["communication"]))
		self.assertEqual(comm.sender, "esign-out@example.com")
		self.assertIn("admin@example.com", comm.bcc or "")

	def test_invalid_requests_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.send(subject="")
		with self.assertRaises(frappe.ValidationError):
			self.send(name="missing")
		with self.assertRaises(frappe.ValidationError):
			self.send(web_form="No Such Web Form")
		with self.assertRaises(frappe.ValidationError):
			self.send(recipients=" , ")
		self.web_form.db_set("esign_enabled", 0)
		with self.assertRaises(frappe.ValidationError):
			self.send()

	def test_failed_link_is_refused(self):
		with (
			patch("esign_webforms.esign.custom.web_form.build_esign_link", return_value=""),
			self.assertRaises(frappe.ValidationError),
		):
			self.send()

	def test_sending_failure_is_logged(self):
		with (
			patch(
				"frappe.core.doctype.communication.communication.Communication.insert",
				side_effect=RuntimeError("smtp"),
			),
			self.assertRaises(frappe.ValidationError),
		):
			self.send()
		self.assertTrue(
			frappe.db.exists(
				"Error Log", {"method": f"eSign: Failed to send email for {TEST_DOCTYPE} {self.doc.name}"}
			)
		)

	def test_sender_needs_email_permission(self):
		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			self.send()


def desk_sprite_definitions(icon: str) -> int:
	"""How many times the desk's icon sprites (app_include_icons) define the symbol id."""
	count = 0
	for url in frappe.get_hooks("app_include_icons"):
		app, _, path = url.removeprefix("/assets/").partition("/")
		with open(frappe.get_app_path(app, "public", path)) as f:
			count += f.read().count(f'id="{icon}"')
	return count


class TestTimeline(EsignDeskTestCase):
	def test_esign_communications_become_timeline_cards(self):
		audit = {"signer_name": "Sam Signer", "signer_email": "sam@example.com", "pdf_hash": "ab" * 32}
		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "eSign",
				"subject": "Signed",
				"content": json.dumps(audit),
				"reference_doctype": TEST_DOCTYPE,
				"reference_name": self.doc.name,
			}
		).insert(ignore_permissions=True)
		pdf = cast(
			File,
			frappe.get_doc(
				{
					"doctype": "File",
					"file_name": "signed.pdf",
					"attached_to_doctype": "Communication",
					"attached_to_name": comm.name,
					"content": make_pdf(),
					"is_private": 1,
				}
			).insert(ignore_permissions=True),
		)
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "eSign",
				"subject": "Unreadable",
				"content": "not json",
				"sender": "fallback@example.com",
				"reference_doctype": TEST_DOCTYPE,
				"reference_name": self.doc.name,
			}
		).insert(ignore_permissions=True)

		cards = get_timeline_content(TEST_DOCTYPE, str(self.doc.name))
		self.assertEqual(len(cards), 2)
		by_signer = {card["template_data"]["signer_email"]: card for card in cards}
		signed = by_signer["sam@example.com"]["template_data"]
		self.assertEqual(signed["signer_name"], "Sam Signer")
		self.assertEqual(signed["pdf_hash"], "ab" * 32)
		self.assertEqual(signed["file_url"], pdf.file_url)
		self.assertEqual(by_signer["sam@example.com"]["template"], "esign_timeline")
		self.assertIsNone(by_signer["fallback@example.com"]["template_data"]["file_url"])
		self.assertEqual(get_timeline_content("ToDo", "nothing"), [])

	def add_esign_communication(self, audit: dict) -> None:
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "eSign",
				"subject": "Signed",
				"content": json.dumps(audit),
				"reference_doctype": TEST_DOCTYPE,
				"reference_name": self.doc.name,
			}
		).insert(ignore_permissions=True)

	def test_verification_and_consent_on_the_card(self):
		self.add_esign_communication(
			{
				"signer_email": "sam@example.com",
				"signer_email_verified": True,
				"verified_via": "recipient link",
				"verified_email": "sam@example.com",
				"consent_text": "I agree to sign this document electronically.",
				"consent_timestamp": "2026-10-16 11:59:58",
			}
		)
		data = get_timeline_content(TEST_DOCTYPE, str(self.doc.name))[0]["template_data"]
		self.assertTrue(data["email_verified"])
		self.assertIsNone(data["verified_email"])
		self.assertEqual(data["consent_text"], "I agree to sign this document electronically.")
		self.assertEqual(data["consent_timestamp"], "2026-10-16 11:59:58")

	def test_link_recipient_shown_when_the_signer_entered_another_email(self):
		self.add_esign_communication(
			{
				"signer_email": "typed@example.com",
				"signer_email_verified": False,
				"verified_email": "sam@example.com",
			}
		)
		data = get_timeline_content(TEST_DOCTYPE, str(self.doc.name))[0]["template_data"]
		self.assertFalse(data["email_verified"])
		self.assertEqual(data["verified_email"], "sam@example.com")

	def test_records_from_before_verification_show_none(self):
		self.add_esign_communication({"signer_email": "sam@example.com"})
		data = get_timeline_content(TEST_DOCTYPE, str(self.doc.name))[0]["template_data"]
		self.assertFalse(data["email_verified"])
		self.assertIsNone(data["verified_email"])
		self.assertIsNone(data["consent_text"])

	def test_timeline_template_shows_verification_and_consent(self):
		with open(
			frappe.get_app_path("esign_webforms", "public", "js", "templates", "esign_timeline.html")
		) as f:
			template = f.read()
		self.assertIn('__("Email verified via recipient link")', template)
		self.assertIn("{% if (email_verified) { %}", template)
		self.assertIn("{{ consent_text }}", template)

	def test_signer_controlled_values_are_escaped(self):
		payload = '<img src=x onerror="alert(1)">'
		audit = {
			"signer_name": payload,
			"signer_email": payload,
			"user_agent": payload,
			"ip_address": payload,
			"web_form": payload,
			"signed_fields": [payload],
			"verified_email": payload,
			"consent_text": payload,
			"consent_timestamp": payload,
		}
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "eSign",
				"subject": "Signed",
				"content": json.dumps(audit),
				"reference_doctype": TEST_DOCTYPE,
				"reference_name": self.doc.name,
			}
		).insert(ignore_permissions=True)

		data = get_timeline_content(TEST_DOCTYPE, str(self.doc.name))[0]["template_data"]
		escaped = "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"
		for key in (
			"signer_name",
			"signer_email",
			"user_agent",
			"ip_address",
			"web_form",
			"verified_email",
			"consent_text",
			"consent_timestamp",
		):
			self.assertEqual(data[key], escaped, key)
		self.assertEqual(data["signed_fields"], [escaped])
		self.assertIsNone(data["timestamp"])

	def test_timeline_icons_are_drawn_in_the_theme_colour(self):
		# Frappe colours an icon through its "icon" class; espresso's es-line-* symbols have no
		# colour of their own (the link icon was black on the dark theme), and a <use> of an id
		# the desk's sprites define twice draws the first one (es-line-download showed as a dot).
		with open(
			frappe.get_app_path("esign_webforms", "public", "js", "templates", "esign_timeline.html")
		) as f:
			icons = re.findall(r'<svg class="([^"]*)">\s*<use href="#([^"]+)"', f.read())
		self.assertEqual(len(icons), 2)
		for classes, icon in icons:
			self.assertIn("icon", classes.split(), icon)
			self.assertTrue(icon.startswith("icon-"), icon)
			self.assertEqual(desk_sprite_definitions(icon), 1, icon)


class TestEmailTemplate(EsignDeskTestCase):
	def test_esign_templates_and_context(self):
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": "eSign Test Request",
				"subject": "Please sign {{ name }}",
				"response": "Sign here",
				"esign_request": 1,
			}
		)
		if frappe.db.exists("Email Template", template.name):
			frappe.delete_doc("Email Template", template.name, force=True)
		template.insert(ignore_permissions=True)

		self.assertIn("Please sign {{ name }}", [t.subject for t in get_esign_email_templates()])
		loaded = cast(EsignEmailTemplate, frappe.get_doc("Email Template", str(template.name)))
		self.assertEqual(loaded.get_context(frappe._dict())["esign_request"], 1)


class TestInstall(EsignDeskTestCase):
	def test_install_and_migrate_add_the_communication_type(self):
		after_install()
		after_migrate()
		self.assertIn("eSign", communication_type_options())

	def test_uninstall_removes_it(self):
		self.addCleanup(after_install)
		after_uninstall()
		frappe.clear_cache(doctype="Communication")
		self.assertNotIn("eSign", communication_type_options())

	def test_field_options_are_added_once_and_reverted(self):
		add_field_options(TEST_DOCTYPE, "status", ["Countersigned"])
		add_field_options(TEST_DOCTYPE, "status", ["Countersigned"])
		setter = frappe.db.get_value(
			"Property Setter",
			{"doc_type": TEST_DOCTYPE, "field_name": "status", "property": "options"},
			"value",
		)
		self.assertEqual(setter.split("\n").count("Countersigned"), 1)

		revert_field_options(TEST_DOCTYPE, "status", ["Countersigned"])
		setter = frappe.db.get_value(
			"Property Setter",
			{"doc_type": TEST_DOCTYPE, "field_name": "status", "property": "options"},
			"value",
		)
		self.assertNotIn("Countersigned", setter.split("\n"))

	def test_reverting_the_last_option_deletes_the_property_setter(self):
		frappe.make_property_setter(
			{
				"doctype": TEST_DOCTYPE,
				"doctype_or_field": "DocField",
				"fieldname": "title",
				"property": "options",
				"value": "Only",
				"property_type": "Text",
			}
		)
		revert_field_options(TEST_DOCTYPE, "title", ["Only"])
		self.assertFalse(
			frappe.db.exists(
				"Property Setter", {"doc_type": TEST_DOCTYPE, "field_name": "title", "property": "options"}
			)
		)
		revert_field_options(TEST_DOCTYPE, "title", ["Only"])

	def test_unknown_field_is_ignored(self):
		add_field_options(TEST_DOCTYPE, "no_such_field", ["X"])
		self.assertFalse(
			frappe.db.exists("Property Setter", {"doc_type": TEST_DOCTYPE, "field_name": "no_such_field"})
		)
