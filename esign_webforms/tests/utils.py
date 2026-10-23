# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Fixtures shared by the eSign tests: a submittable test doctype, an eSign web form on it,
documents to sign and a request to sign them from."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from io import BytesIO
from typing import Any, cast

import frappe
from frappe.core.doctype.user.user import User
from frappe.model.document import Document
from frappe.utils import set_request
from pypdf import PdfWriter


class Agreement(Document):
	"""The test doctype's fields, for the type checker only: the doctype is custom, so its
	documents are plain Documents at runtime and this class is never instantiated."""

	title: str | None
	signer_name: str | None
	signer_email: str | None
	signature: str | None
	status: str | None
	rating: int
	agreed_on: str | None
	attachment: str | None


TEST_DOCTYPE = "eSign Test Agreement"
WEB_FORM_ROUTE = "esign-test-agreement"
OUTSIDER = "esign-outsider@example.com"
SIGNER = "esign-signer@example.com"

# A 1x1 transparent PNG, the shape the signature control posts.
SIGNATURE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
PLACEHOLDER_SIGNATURE = "/assets/frappe/images/signature-placeholder.png"


def make_pdf(pages: int = 1) -> bytes:
	"""A valid PDF: frappe checks an uploaded PDF parses before it saves the File."""
	writer = PdfWriter()
	for _ in range(pages):
		writer.add_blank_page(width=72, height=72)
	buffer = BytesIO()
	writer.write(buffer)
	return buffer.getvalue()


def ensure_test_doctype() -> None:
	"""Create the custom, submittable doctype the tests sign (a DDL change, so it commits)."""
	if frappe.db.exists("DocType", TEST_DOCTYPE):
		return
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": TEST_DOCTYPE,
			"module": "eSign",
			"custom": 1,
			"is_submittable": 1,
			"autoname": "hash",
			"fields": [
				{"fieldname": "title", "fieldtype": "Data", "label": "Title"},
				{
					"fieldname": "signer_name",
					"fieldtype": "Data",
					"label": "Signer Name",
					"allow_on_submit": 1,
				},
				{
					"fieldname": "signer_email",
					"fieldtype": "Data",
					"options": "Email",
					"label": "Signer Email",
					"allow_on_submit": 1,
				},
				{
					"fieldname": "signature",
					"fieldtype": "Signature",
					"label": "Signature",
					"allow_on_submit": 1,
				},
				{
					"fieldname": "status",
					"fieldtype": "Select",
					"options": "\nDraft\nSigned\nNotified",
					"label": "Status",
					"allow_on_submit": 1,
				},
				{"fieldname": "rating", "fieldtype": "Int", "label": "Rating", "allow_on_submit": 1},
				{"fieldname": "agreed_on", "fieldtype": "Date", "label": "Agreed On", "allow_on_submit": 1},
				{
					"fieldname": "attachment",
					"fieldtype": "Attach",
					"label": "Attachment",
					"allow_on_submit": 1,
				},
			],
			"permissions": [
				{
					"role": "System Manager",
					"read": 1,
					"write": 1,
					"create": 1,
					"delete": 1,
					"submit": 1,
					"cancel": 1,
					"email": 1,
					"print": 1,
					"share": 1,
				}
			],
		}
	).insert(ignore_permissions=True)


def ensure_user(email: str, roles: list[str] | None = None) -> None:
	"""A user with the given roles (none: a website user who can open no desk document)."""
	if frappe.db.exists("User", email):
		return
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"user_type": "System User" if roles else "Website User",
		}
	)
	user.insert(ignore_permissions=True)
	if roles:
		cast(User, user).add_roles(*roles)


def make_web_form(**kwargs: Any) -> Document:
	"""An eSign-enabled web form on the test doctype, replacing any left by an earlier test."""
	if frappe.db.exists("Web Form", {"route": WEB_FORM_ROUTE}):
		frappe.delete_doc(
			"Web Form",
			frappe.db.get_value("Web Form", {"route": WEB_FORM_ROUTE}),
			force=True,
			ignore_permissions=True,
		)
	web_form = frappe.get_doc(
		{
			"doctype": "Web Form",
			"title": "eSign Test Agreement",
			"route": WEB_FORM_ROUTE,
			"doc_type": TEST_DOCTYPE,
			"module": "eSign",
			"published": 1,
			"esign_enabled": 1,
			"web_form_fields": [
				{"fieldname": "signer_email", "fieldtype": "Data", "label": "Signer Email"},
				{"fieldname": "signature", "fieldtype": "Signature", "label": "Signature"},
			],
			**kwargs,
		}
	)
	web_form.insert(ignore_permissions=True)
	return web_form


def make_agreement(**kwargs: Any) -> Agreement:
	"""A draft document of the test doctype."""
	doc = frappe.get_doc({"doctype": TEST_DOCTYPE, "title": "Service agreement", **kwargs})
	doc.insert(ignore_permissions=True)
	return cast(Agreement, doc)


def get_agreement(name: str | None) -> Agreement:
	"""A fresh copy of a test document, without the flags the creating code left on it."""
	return cast(Agreement, frappe.get_doc(TEST_DOCTYPE, str(name)))


def share_key(doc: Document) -> str:
	return doc.get_document_share_key()


@contextmanager
def signing_request(
	path: str = f"/{WEB_FORM_ROUTE}",
	referrer: str | None = None,
	headers: dict[str, str] | None = None,
	method: str = "POST",
	**form_dict: Any,
) -> Generator[None]:
	"""Run the block inside a request from a signer's browser, as frappe would set it up."""
	all_headers = dict(headers or {})
	if referrer is not None:
		all_headers["Referer"] = referrer
	set_request(method=method, path=path, headers=all_headers, environ_base={"REMOTE_ADDR": "127.0.0.1"})
	frappe.local.request_ip = "127.0.0.1"
	frappe.local.form_dict = frappe._dict(form_dict)
	# The endpoints are rate limited per IP; the tests are one IP making many requests.
	if cache := frappe.cache:
		cache.delete_keys("rl:")
	try:
		yield
	finally:
		frappe.local.request = None
		frappe.local.request_ip = None
		frappe.local.form_dict = frappe._dict()


def form_data(doc: Document, **values: Any) -> str:
	"""The JSON the web form posts to accept."""
	return json.dumps({"doctype": doc.doctype, "name": doc.name, **values})


def make_email_account(name: str = "eSign Test Outgoing", email: str = "esign-out@example.com") -> str:
	"""An email account that sends nothing, for the sender links."""
	if not frappe.db.exists("Email Account", name):
		account = frappe.get_doc(
			{
				"doctype": "Email Account",
				"email_account_name": name,
				"email_id": email,
				"enable_outgoing": 0,
				"enable_incoming": 0,
			}
		)
		account.flags.ignore_validate = True
		account.insert(ignore_permissions=True)
	return name


def allow_esign(doc: frappe._dict) -> bool:
	"""A can_esign hook target that allows documents titled "Allowed"."""
	return doc.get("title") == "Allowed"
