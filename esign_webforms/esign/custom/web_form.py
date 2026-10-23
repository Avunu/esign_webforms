# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import TypedDict, cast

import frappe
from frappe import _
from frappe.core.doctype.file.file import File
from frappe.core.doctype.file.utils import get_content_hash, remove_file_by_url
from frappe.email.doctype.notification.notification import Notification
from frappe.model import numeric_fieldtypes
from frappe.model.docstatus import DocStatus
from frappe.model.document import Document
from frappe.rate_limiter import rate_limit
from frappe.twofactor import get_qr_svg_code
from frappe.types import DF
from frappe.utils import cint, escape_html, get_frappe_version, now, validate_email_address
from frappe.website.doctype.web_form.web_form import WebForm as BaseWebForm
from frappe.www.printview import validate_print_permission

# The field types "Set Property After Response" (esign_update_field) can set; web_form.js
# offers only these.
UPDATE_FIELD_TYPES = ("Select", "Link", "Data", "Text")

# The field types the Signer Name Field and Signer Email Field (esign_signer_name_field,
# esign_signer_email_field) can name; web_form.js offers only the form's fields of these types.
SIGNER_FIELD_TYPES = ("Data",)

# The longest signer name recorded, as frappe's User full_name and Communication
# sender_full_name hold it.
SIGNER_NAME_LENGTH = 140

# The signing link's parameter that binds its `email` parameter to the document: an HMAC of
# the document and the address, keyed with a secret derived from the site's encryption key.
EMAIL_BINDING_PARAM = "email_sig"

# How a recorded signer email was verified (AuditData.verified_via).
VERIFIED_VIA_LINK = "recipient link"

# The consent checkbox's text when the web form sets none (esign_consent_text).
DEFAULT_CONSENT_TEXT = "I agree to sign this document electronically."


class PrintHtmlResponse(TypedDict):
	"""Response from get_print_html endpoint."""

	print_html: str
	print_style: str


def validate_esign_key(key: str, doc: Document, require_key: bool = False) -> bool:
	"""Validate document share key for eSign access.

	Args:
		key: The share key to validate
		doc: The document to validate access for
		require_key: If True, raises error when no key provided. If False, falls back
			to standard permission check when no key.

	Returns:
		True if access is granted (either via valid key or fallback permissions)

	Raises:
		frappe.PermissionError: If key is invalid/expired or no access granted
	"""
	from frappe.www.printview import validate_key

	if key:
		# validate_key returns False if key not found, None if valid
		if validate_key(key, doc) is False:
			frappe.throw(_("Invalid or expired document access key"), frappe.PermissionError)
		return True

	if require_key:
		frappe.throw(_("Document access key required"), frappe.PermissionError)

	# No key provided - fall back to standard permission check
	validate_print_permission(doc)
	return True


class RequestData(TypedDict):
	host_url: str | None
	scheme: str
	host: str | None
	headers: dict
	method: str | None


class AuditData(TypedDict):
	"""Audit trail data captured at signing time.

	signer_email_verified is true when signer_email is the address the signing link was bound
	to (verified_via says how); verified_email is that address, recorded whenever the link
	carried a valid binding, even if the signer entered another address. consent_text is the
	electronic-signature consent the signer agreed to, and consent_timestamp when the server
	received it.
	"""

	timestamp: str
	ip_address: str | None
	user_agent: str | None
	signer_email: str | None
	signer_name: str | None
	signer_email_verified: bool
	verified_via: str | None
	verified_email: str | None
	consent_text: str | None
	consent_timestamp: str | None
	web_form: str
	print_format: str
	signed_fields: list[str]


def extract_param_from_referrer(param: str = "") -> str:
	"""Extract 'key' parameter from HTTP Referer header safely."""
	referrer = frappe.get_request_header("Referer")

	if not referrer:
		return ""

	try:
		from urllib.parse import parse_qs, urlparse

		parsed_url = urlparse(referrer)
		query_params = parse_qs(parsed_url.query, keep_blank_values=False)

		# Get the first non-empty key value
		return query_params.get(param, [""])[0]

	except Exception as e:
		frappe.log_error(title=f"eSign: Failed to parse referrer URL: {referrer}", message=e)
		return ""


def _fieldname(row: Document) -> str | None:
	"""A web form row's fieldname.

	Frappe declares WebFormField.fieldname (and Notification.set_property_after_alert) as
	`Literal[None]`, its type for a Select whose options are only filled in at runtime, so
	the value is read through `get`, which is untyped.
	"""
	return row.get("fieldname")


def _find_email_fieldname(wf: EsignWebForm) -> str | None:
	"""Find the fieldname of a Data field with Options='Email' on the web form.

	Checks the underlying doctype meta for the field options, since web form
	field rows don't always carry ``options`` from the doctype definition.

	Returns the fieldname if found, otherwise ``None``.
	"""
	meta = frappe.get_meta(wf.doc_type)
	for field in wf.web_form_fields:
		fieldname = _fieldname(field)
		if field.fieldtype == "Data" and fieldname:
			df = meta.get_field(fieldname)
			if df and df.fieldtype == "Data" and (df.options or "").strip().lower() == "email":
				return fieldname
	return None


def _signer_fieldname(wf: EsignWebForm, setting: str) -> str | None:
	"""The fieldname a Signer Name or Signer Email Field setting names, if it is still one of
	the web form's Data fields (the form may have changed since the setting was saved)."""
	fieldname = wf.get(setting)
	if not fieldname:
		return None
	for field in wf.web_form_fields:
		if _fieldname(field) == fieldname and field.fieldtype in SIGNER_FIELD_TYPES:
			return fieldname
	return None


def _normalize_email(email: str | None) -> str:
	"""An address as the email binding and its comparisons read it: trimmed, in lower case."""
	return (email or "").strip().lower()


def _binding_key() -> bytes:
	"""The key email bindings are signed with.

	Derived from the site's encryption key (frappe creates one on first use), so it is secret,
	differs per site and is not the encryption key itself. Rotating the encryption key
	invalidates every bound link sent before.
	"""
	from frappe.utils.password import get_encryption_key

	return hmac.new(
		get_encryption_key().encode(), b"esign_webforms:recipient-email-binding", hashlib.sha256
	).digest()


def make_email_binding(doctype: str, docname: str, email: str) -> str:
	"""The HMAC-SHA256 that binds email to one document, as the link's `email_sig` parameter.

	It covers the doctype, the document name and the address (normalized), so it cannot be
	moved to another document or another address. It does not replace the share key, which
	still decides whether the link opens the document at all and when it expires.
	"""
	message = "\x00".join((doctype, str(docname), _normalize_email(email))).encode()
	return hmac.new(_binding_key(), message, hashlib.sha256).hexdigest()


def strip_email_binding(link: str) -> str:
	"""link without its `email_sig` binding, for every copy of it that is not the email to its
	recipient: the sender's API response and the Communication any reader of the document sees.
	Whoever holds the binding signs as the recipient, verified."""
	return re.sub(rf"[?&]{EMAIL_BINDING_PARAM}=[0-9A-Fa-f]*", "", link)


def _is_single_email(value: str | None) -> bool:
	"""Whether value is one valid email address. validate_email_address accepts a list of
	them, separated by commas, and returns the valid ones joined the same way."""
	if not value or "," in value:
		return False
	return validate_email_address(value) == value


def get_bound_email(doctype: str, docname: str | None, email: str | None, binding: str | None) -> str | None:
	"""The link's email when binding is its valid HMAC for this document, otherwise None.

	The comparison is constant time, so the response time does not reveal how much of a
	guessed binding was right.
	"""
	email = (email or "").strip()
	if not binding or not docname or not _is_single_email(email):
		return None
	expected = make_email_binding(doctype, docname, email)
	if hmac.compare_digest(expected.encode(), binding.strip().encode()):
		return email
	return None


def _require_bound_email(
	wf: EsignWebForm, doctype: str, docname: str | None, email: str | None, binding: str | None
) -> str | None:
	"""The link's bound email, or None when it has no valid binding.

	With the web form's Require Verified Email on, a missing or invalid binding is refused
	instead, with a message the signer can act on.
	"""
	bound = get_bound_email(doctype, docname, email, binding)
	if bound or not wf.get("esign_require_verified_email"):
		return bound
	if binding:
		frappe.throw(
			_(
				"This signing link has been changed, or it was not sent for this document. Open the "
				"link from your email exactly as it is, or ask the sender for a new one."
			),
			frappe.PermissionError,
			title=_("Invalid Signing Link"),
		)
	frappe.throw(
		_(
			"This document can only be signed through the link emailed to its signer. Open the link "
			"from your email, or ask the sender to send it again."
		),
		frappe.PermissionError,
		title=_("Signing Link Required"),
	)


def _email_fieldname(wf: EsignWebForm) -> str | None:
	"""The form field that holds the signer's email: the Signer Email Field, or else a Data
	field whose options are Email."""
	return _signer_fieldname(wf, "esign_signer_email_field") or _find_email_fieldname(wf)


def get_consent_text(wf: EsignWebForm) -> str:
	"""The consent checkbox's text: the web form's own, or the default in the signer's language."""
	return (wf.get("esign_consent_text") or "").strip() or _(DEFAULT_CONSENT_TEXT)


class EsignWebForm(BaseWebForm):
	"""eSign behaviour for Web Form, registered through `extend_doctype_class`.

	Frappe composes the final controller from the stock WebForm and every installed app's
	extension (payments registers one too), so this subclasses the stock WebForm only:
	subclassing another app's extension would break the class hierarchy whenever that app is
	installed after esign_webforms.
	"""

	# Custom fields from ../custom/web_form.json
	esign_enabled: DF.Check | None
	esign_force_mobile: DF.Check | None
	# A Select whose options are the target doctype's fields, set at runtime (web_form.js).
	esign_update_field: DF.Data | None
	esign_update_value: DF.Data | None
	# Selects whose options are the web form's own Data fields, set at runtime (web_form.js).
	esign_signer_name_field: DF.Data | None
	esign_signer_email_field: DF.Data | None
	esign_require_verified_email: DF.Check | None
	esign_consent_text: DF.SmallText | None
	esign_submit_on_response: DF.Check | None
	esign_send_notification: DF.Check | None
	esign_notification: DF.Link | None

	def _get_signed_pdf(self, doc: Document) -> dict | None:
		"""Get the most recent signed PDF attachment for the document.

		Looks for PDFs attached via the eSign Communication record.
		"""
		# First try to find an eSign Communication for this document
		comm = frappe.get_all(
			"Communication",
			filters={
				"reference_doctype": doc.doctype,
				"reference_name": doc.name,
				"communication_type": "eSign",
			},
			fields=["name"],
			order_by="creation desc",
			limit=1,
		)

		if comm:
			# Get the PDF attached to the Communication
			pdf_file = frappe.get_all(
				"File",
				filters={
					"attached_to_doctype": "Communication",
					"attached_to_name": comm[0].name,
					"file_name": ("like", "%.pdf"),
				},
				fields=["name", "file_name", "file_url"],
				order_by="creation desc",
				limit=1,
			)
			if pdf_file:
				return pdf_file[0]

		# Fallback: look for signed PDFs attached directly to the document
		pdf_file = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": doc.doctype,
				"attached_to_name": doc.name,
				"file_name": ("like", "%_signed_%.pdf"),
			},
			fields=["name", "file_name", "file_url"],
			order_by="creation desc",
			limit=1,
		)
		if pdf_file:
			return pdf_file[0]

		return None

	def _check_signature_exists(self, doc: Document) -> bool:
		"""Check if all signature fields in the web form already have values."""
		signature_fields = [
			_fieldname(field) for field in self.web_form_fields if field.fieldtype == "Signature"
		]

		# If no signature fields, not applicable
		if not signature_fields:
			return False

		# Check if ALL signature fields have non-empty values
		for fieldname in signature_fields:
			value = doc.get(fieldname)
			if not value or str(value) == "/assets/frappe/images/signature-placeholder.png":
				return False

		return True

	def get_context(self, context):
		cur_doc_name = frappe.form_dict.get("name", context.doc_name)
		if not self.esign_enabled or not cur_doc_name or frappe.form_dict.is_list:
			super().get_context(context)
			return context

		key = frappe.form_dict.get("key", "")

		# Get document without permission check - we'll validate via share key
		doc = frappe.get_doc(self.doc_type, cur_doc_name)

		# Validate access via share key or fallback to standard permissions. The document is
		# only marked permission-free afterwards: frappe's website permission check (part of
		# the fallback) passes any document that already carries ignore_permissions. Without a
		# key, the web form's own rules (owner, website permission, document permissions) also
		# let a user in, as in frappe's web form and in accept; the preview and the signed-PDF
		# download apply the same rule through the web form name the page passes them.
		validate_esign_access(key, doc, self)
		doc.flags.ignore_permissions = True

		# The recipient's email, when the link binds it to this document. With Require
		# Verified Email, a link without a valid binding is refused here.
		email_param = frappe.form_dict.get("email", "")
		bound_email = _require_bound_email(
			self, self.doc_type, cur_doc_name, email_param, frappe.form_dict.get(EMAIL_BINDING_PARAM)
		)
		lock_email = bool(bound_email and self.esign_require_verified_email)
		email_fieldname = _email_fieldname(self)

		# Allow public access to the web form if validation passes
		print_format = frappe.form_dict.get("format", self.print_format) or "standard"

		web_form_doc: dict = self.as_dict(no_nulls=True)
		web_form_doc.update(
			{
				"login_required": False,
				"allow_edit": True,
				"allow_multiple": True,
				"allow_delete": True,
				"in_edit_mode": True,
			}
		)
		if lock_email and email_fieldname:
			# The signer cannot change the address the link was sent to; accept ignores a
			# changed one too, so this is only for the signer's benefit.
			for field in web_form_doc.get("web_form_fields") or []:
				if field.get("fieldname") == email_fieldname:
					field["read_only"] = 1
		context.web_form_doc = web_form_doc
		super().load_form_data(context)
		super().load_translations(context)
		super().add_metatags(context)
		context.doctype = self.doc_type
		context.name = cur_doc_name
		context.print_format = print_format
		form_fields: set[str] = {
			fieldname for field in self.web_form_fields if (fieldname := _fieldname(field))
		}
		form_fields.add("name")
		form_fields.add("doctype")
		context.reference_doc = {k: v for k, v in doc.as_dict().items() if k in form_fields}

		# Pre-fill email field from URL param (e.g. when link was sent via email). Unless the
		# web form requires a verified email, this only fills the form: the signer can change
		# it, and what is saved is what they submit.
		prefill = bound_email or email_param
		if prefill and email_fieldname and email_fieldname in form_fields:
			context.reference_doc[email_fieldname] = prefill
		context.esign_verified_email = bound_email or ""
		context.esign_consent_text = get_consent_text(self)

		super().add_custom_context_and_script(context)

		context.key = key  # Pass key to frontend for async API calls
		context.esign_web_form = self.name  # Lets the async calls apply the keyless web form rules
		context.printview_url = (
			"/api/method/frappe.utils.print_format.download_pdf?"
			f"doctype={self.doc_type}&name={cur_doc_name}&format={print_format}&key={key}"
		)
		# Include eSign assets
		context.web_include_css.extend(
			[
				"esign_webforms.control.bundle.css",
				"esign_webforms.web.bundle.css",
				"esign-fonts.bundle.css",
			]
		)
		context.web_include_js.extend(
			[
				"esign_webforms.web.bundle.js",
			]
		)
		context.template = "esign_webforms/templates/esign_webforms.html"
		if self.esign_force_mobile:
			context.force_mobile = True
			context.qrcode_svg = get_qr_svg_code(frappe.request.url).decode()

		# Check if document has already been signed (all signature fields have values)
		context.is_completed = self._check_signature_exists(doc)

		# If completed, get the signed PDF URL instead of rendering print preview
		if context.is_completed:
			signed_pdf = self._get_signed_pdf(doc)
			if signed_pdf:
				# Build the download URL through our key-validated endpoint
				from urllib.parse import urlencode

				params = urlencode(
					{
						"doctype": self.doc_type,
						"docname": cur_doc_name,
						"key": key,
						"web_form": self.name,
					}
				)
				context.signed_pdf_url = (
					f"/api/method/esign_webforms.esign.custom.web_form.download_signed_pdf?{params}"
				)
				context.signed_pdf_name = signed_pdf.get("file_name")

		context.frappe_version = get_frappe_version()

		return context

	def validate(self):
		super().validate()

		# if esign is enabled, force allow_edit
		if self.esign_enabled:
			self.allow_edit = True
			self.validate_update_field()
			self.validate_signer_fields()

	def validate_update_field(self):
		"""Refuse a Set Property After Response field that accept would not set."""
		if not self.esign_update_field or not self.doc_type:
			return
		df = frappe.get_meta(self.doc_type).get_field(self.esign_update_field)
		if df and df.fieldtype not in UPDATE_FIELD_TYPES:
			frappe.throw(
				_("Set Property After Response can only set a {0} field, not {1} ({2}).").format(
					", ".join(_(fieldtype) for fieldtype in UPDATE_FIELD_TYPES),
					_(df.label or df.fieldname),
					_(df.fieldtype),
				)
			)

	def validate_signer_fields(self):
		"""Refuse a Signer Name or Signer Email Field that is not a Data field of this form.

		The audit trail only records what the signer typed into the form, so the field has to
		be one of the web form's own fields.
		"""
		form_fieldtypes = {
			fieldname: field.fieldtype for field in self.web_form_fields if (fieldname := _fieldname(field))
		}
		for setting, label in (
			("esign_signer_name_field", _("Signer Name Field")),
			("esign_signer_email_field", _("Signer Email Field")),
		):
			fieldname = self.get(setting)
			if not fieldname:
				continue
			if fieldname not in form_fieldtypes:
				frappe.throw(
					_("{0} must be one of this web form's fields, not {1}.").format(label, fieldname)
				)
			if form_fieldtypes[fieldname] not in SIGNER_FIELD_TYPES:
				frappe.throw(
					_("{0} can only be a {1} field, not {2} ({3}).").format(
						label,
						", ".join(_(fieldtype) for fieldtype in SIGNER_FIELD_TYPES),
						fieldname,
						_(form_fieldtypes[fieldname]),
					)
				)

	def has_web_form_permission(self, doctype, name, ptype="read"):
		"""Override to allow eSign access for Guest users with valid keys"""
		# For eSign forms, check key-based access first. The share key lets a signer read the
		# document anywhere, but write it only through this app's accept, which also checks
		# the consent and the recipient binding: frappe's own web form accept (whitelisted for
		# guests too) asks this same question before saving, and would skip both.
		if self.esign_enabled and name and (ptype == "read" or frappe.flags.esign_key_write):
			# Try to get the key from form_dict or extract from referrer
			if not frappe.form_dict.get("key"):
				frappe.form_dict.key = extract_param_from_referrer("key")

			# Validate via share key if provided
			key = frappe.form_dict.get("key")
			if key:
				try:
					doc = frappe.get_doc(doctype, name)
					validate_esign_key(key, doc, require_key=True)
					return True
				except frappe.PermissionError:
					# Invalid key - fall through to normal permission check
					pass

		# Fall back to parent method
		return super().has_web_form_permission(doctype, name, ptype)


def _signer_field_value(doc: Document, wf: EsignWebForm, setting: str) -> str | None:
	"""The value the signer submitted in the field a Signer Name or Signer Email Field setting
	names, stripped, or None when the setting is unset or the field is empty."""
	fieldname = _signer_fieldname(wf, setting)
	if not fieldname:
		return None
	value = doc.get(fieldname)
	value = " ".join(str(value).split()) if value else ""
	return value or None


def _get_esign_web_form(web_form: EsignWebForm | str, doctype: str) -> EsignWebForm | None:
	"""The eSign-enabled web form for doctype, or None if web_form is not one."""
	if isinstance(web_form, str):
		if not frappe.db.exists("Web Form", web_form):
			return None
		web_form = cast(EsignWebForm, frappe.get_cached_doc("Web Form", web_form))
	if not web_form.get("esign_enabled") or web_form.get("doc_type") != doctype:
		return None
	return web_form


def validate_esign_access(
	key: str, doc: Document, web_form: EsignWebForm | str | None = None, require_key: bool = False
) -> bool:
	"""Validate access to an eSign document for the signing page and its endpoints.

	A key is checked as the share key. Without one, a logged-in user the eSign web form's own
	rules admit (owner, website permission, document permissions) is let in, so the page, its
	preview and its signed-PDF download agree; anyone else falls back to validate_esign_key.

	Args:
		key: The share key, or an empty string
		doc: The document being accessed
		web_form: The eSign web form (or its name) the request comes from, if any
		require_key: Passed on to validate_esign_key when the web form rules do not admit

	Raises:
		frappe.PermissionError: If access is not granted
	"""
	if not key and web_form and frappe.session.user != "Guest":
		wf = _get_esign_web_form(web_form, doc.doctype)
		if wf and BaseWebForm.has_web_form_permission(wf, doc.doctype, str(doc.name), "read"):
			return True
	return validate_esign_key(key, doc, require_key=require_key)


def verification_rows(audit_data: AuditData | dict) -> list[tuple[str, str]]:
	"""How the signer's email was verified, as label and text rows for the notification email
	(the timeline card shows the same in esign_timeline.html)."""
	if audit_data.get("signer_email_verified"):
		# The only way an email is verified (verified_via is VERIFIED_VIA_LINK).
		return [(_("Verification"), _("Email verified via recipient link"))]
	if verified_email := audit_data.get("verified_email"):
		# The link was bound to one address, and the signer entered another.
		return [(_("Link Sent To"), _("{0}, verified via recipient link").format(verified_email))]
	return []


_UNSET = object()


def _send_esign_notification(
	notification_name: str,
	doc: Document,
	file_doc: File,
	audit_data: AuditData | None = None,
	pdf_hash: str | None = None,
):
	"""Send a notification with the validated signed PDF attached.

	Instead of letting the notification regenerate the PDF via attach_print,
	we directly attach the already-validated signed PDF file.
	Appends the eSign audit trail to the email body for external verification.
	"""
	from email.utils import formataddr

	from frappe.core.doctype.communication.email import _make as make_communication
	from frappe.email.doctype.notification.notification import get_context

	try:
		notification = cast(Notification, frappe.get_doc("Notification", notification_name))

		# Validate notification configuration
		if notification.document_type != doc.doctype:
			frappe.log_error(
				title="eSign: Notification doctype mismatch",
				message=f"Notification '{notification_name}' is for {notification.document_type}, not {doc.doctype}",
			)
			return

		if notification.event != "Custom":
			frappe.log_error(
				title="eSign: Notification event not Custom",
				message=f"Notification '{notification_name}' event is '{notification.event}', expected 'Custom'",
			)
			return

		if not notification.enabled:
			frappe.log_error(
				title="eSign: Notification disabled",
				message=f"Notification '{notification_name}' is not enabled",
			)
			return

		# Build context the way Notification.send() does
		context = get_context(doc)
		context.update({"alert": notification, "comments": None})
		if doc.get("_comments"):
			context["comments"] = json.loads(str(doc.get("_comments", "[]")))

		if notification.is_standard:
			notification.load_standard_properties(context)

		# Only handle Email channel - other channels don't support file attachments in the same way
		if notification.channel != "Email":
			frappe.log_error(
				title="eSign: Notification channel not Email",
				message=f"eSign notification with signed PDF attachment only supports Email channel, not '{notification.channel}'",
			)
			return

		# Render subject and message. Both come from the Notification, which only System
		# Managers author: the same trusted source frappe's own Notification.send_an_email
		# renders them from, with the same sandboxed environment.
		subject = notification.subject
		if subject and "{" in subject:
			# A System Manager's template (above), not user input.
			subject = frappe.render_template(subject, context)  # nosemgrep: frappe-ssti

		# A System Manager's template (above), not user input.
		message = frappe.render_template(notification.message, context) or ""  # nosemgrep: frappe-ssti

		# Append audit trail information to the notification email
		if audit_data:
			audit_rows = []
			if audit_data.get("signer_name"):
				audit_rows.append((_("Signer"), audit_data["signer_name"]))
			if audit_data.get("signer_email"):
				audit_rows.append((_("Email"), audit_data["signer_email"]))
			audit_rows.extend(verification_rows(audit_data))
			if audit_data.get("consent_text"):
				audit_rows.append((_("Consent"), audit_data["consent_text"]))
			if audit_data.get("consent_timestamp"):
				audit_rows.append((_("Consent Given At"), audit_data["consent_timestamp"]))
			if audit_data.get("timestamp"):
				audit_rows.append((_("Signed At"), audit_data["timestamp"]))
			if audit_data.get("ip_address"):
				audit_rows.append((_("IP Address"), audit_data["ip_address"]))
			if audit_data.get("user_agent"):
				audit_rows.append((_("User Agent"), audit_data["user_agent"]))
			if audit_data.get("signed_fields"):
				audit_rows.append((_("Signed Fields"), ", ".join(audit_data["signed_fields"])))
			if pdf_hash:
				audit_rows.append((_("PDF SHA-256"), pdf_hash))

			if audit_rows:
				# The values come from the signer's request (user agent, email parameter), so
				# they are escaped before going into the HTML body.
				table_rows = "".join(
					f'<tr><td style="padding:4px 8px;font-weight:bold;white-space:nowrap;vertical-align:top;">{label}</td>'
					f'<td style="padding:4px 8px;word-break:break-all;">{escape_html(str(value))}</td></tr>'
					for label, value in audit_rows
				)
				message += (
					f'<div style="margin-top:20px;padding:15px;background-color:#f8f9fa;'
					f'border-left:4px solid #6c757d;border-radius:4px;">'
					f'<h4 style="margin:0 0 10px 0;color:#495057;">{_("eSign Audit Trail")}</h4>'
					f'<table style="border-collapse:collapse;font-size:13px;">{table_rows}</table>'
					f"</div>"
				)

		# Get recipients
		recipients, cc, bcc = notification.get_list_of_recipients(doc, context)
		if not (recipients or cc or bcc):
			return

		# Build sender
		sender = None
		if notification.sender and notification.sender_email:
			sender = formataddr((notification.sender, notification.sender_email))

		# Use the validated signed PDF as the attachment instead of regenerating
		attachments = [{"file_url": file_doc.file_url}]

		# Create communication record
		communication = None
		if doc.doctype != "Communication":
			communication = make_communication(
				doctype=doc.doctype,
				name=doc.name,
				content=message,
				subject=subject,
				sender=sender,
				recipients=recipients,
				communication_medium="Email",
				send_email=False,
				attachments=attachments,
				cc=cc,
				bcc=bcc,
				communication_type="Automated Message",
			).get("name")

		# Send the email with the validated PDF attached
		frappe.sendmail(
			recipients=recipients,
			subject=str(subject),
			sender=sender or "",
			cc=cc,
			bcc=bcc,
			message=message or "",
			reference_doctype=doc.doctype,
			reference_name=doc.name,
			attachments=attachments,
			expose_recipients="header",
			print_letterhead=False,
			communication=communication,
		)

		# Handle set_property_after_alert if configured
		fieldname = notification.get("set_property_after_alert")  # Literal[None] in frappe's types
		if fieldname:
			allow_update = True
			field_df = doc.meta.get_field(fieldname)
			if doc.docstatus.is_submitted() and field_df and not field_df.allow_on_submit:
				allow_update = False
			try:
				if allow_update and not doc.flags.in_notification_update:
					value: str | int | float | None = notification.property_value
					if field_df and field_df.fieldtype in numeric_fieldtypes:
						value = cint(value or 0)

					doc.reload()
					doc.set(fieldname, value)
					doc.flags.updater_reference = {
						"doctype": notification.doctype,
						"docname": notification.name,
						"label": _("via eSign Notification"),
					}
					doc.flags.in_notification_update = True
					doc.save(ignore_permissions=True)
					doc.flags.in_notification_update = False
			except Exception:
				frappe.log_error(title="eSign: Document update failed after notification")

	except Exception as e:
		frappe.log_error(
			title=f"eSign: Failed to send notification for {doc.doctype} {doc.name}",
			message=str(e),
		)


@contextmanager
def _job_request(request_data: RequestData) -> Generator[None]:
	"""Give a background job the signing request's host, scheme and headers.

	The PDF renderer and URL helpers read them from `frappe.local.request`. Only the
	context-local request is set: assigning `frappe.request` would replace the module-level
	LocalProxy for the rest of the worker process and leak into later jobs.
	"""
	mock_request = frappe._dict(
		{
			"headers": request_data.get("headers", {}),
			"host_url": request_data["host_url"],
			"host": request_data.get("host"),
			"method": request_data.get("method", "GET"),
			"cache_control": frappe._dict({"no_cache": True}),
			"scheme": request_data.get("scheme", "https"),
		}
	)
	prev_request = getattr(frappe.local, "request", _UNSET)
	frappe.local.request = mock_request
	try:
		yield
	finally:
		if prev_request is _UNSET:
			if hasattr(frappe.local, "request"):
				del frappe.local.request
		else:
			frappe.local.request = prev_request


def _read_file_bytes(file_doc: File) -> bytes:
	"""The stored bytes of a local File. File.get_content decodes anything that decodes as
	text (a PDF often does, as windows-1252), and writing that back would change the bytes."""
	# The path is the File document's own, and get_full_path refuses an unsafe one (is_safe_path).
	with open(file_doc.get_full_path(), "rb") as f:  # nosemgrep: frappe-security-file-traversal
		return f.read()


def _is_cloud_storage_file(file_doc: File) -> bool:
	"""Whether cloud_storage's File extension (s3_key, file_association) is installed."""
	return hasattr(file_doc, "s3_key") and hasattr(file_doc, "file_association")


def record_signature(
	doctype: str,
	name: str,
	file_name: str,
	pdf_hash: str,
	request_data: RequestData,
	audit_data: AuditData,
	notification_name: str | None = None,
):
	"""Background job: record the signing on the document's timeline.

	Creates the eSign Communication (audit data as JSON, shown through the
	additional_timeline_content hook), links the signed PDF to it and, when the web form
	names one, sends the notification with that PDF attached.
	"""
	with _job_request(request_data):
		doc = frappe.get_doc(doctype, name)
		file_doc = cast(File, frappe.get_doc("File", file_name))

		# Create Communication record for timeline display with audit data as JSON
		audit_content = json.dumps(
			{
				**audit_data,
				"pdf_hash": pdf_hash,
				"file_name": file_doc.file_name,
			}
		)

		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "eSign",
				"subject": f"Document signed: {doc.name}",
				"content": audit_content,
				"reference_doctype": doc.doctype,
				"reference_name": doc.name,
				"sender": audit_data.get("signer_email"),
				"sender_full_name": audit_data.get("signer_name"),
				"communication_date": datetime.now(),
				"sent_or_received": "Received",
			}
		)
		comm.insert(ignore_permissions=True)

		# Associate the PDF with the Communication
		if _is_cloud_storage_file(file_doc):
			# For cloud_storage, add a file_association instead of duplicating the file
			from frappe.utils import get_datetime

			file_doc.append(
				"file_association",
				{
					"link_doctype": "Communication",
					"link_name": comm.name,
					"user": frappe.session.user,
					"timestamp": get_datetime(),
				},
			)
			file_doc.save(ignore_permissions=True)
		else:
			# For standard Frappe, create a separate file attachment
			comm_file_doc = cast(
				File,
				frappe.get_doc(
					{
						"doctype": "File",
						"file_name": file_doc.file_name,
						"attached_to_doctype": "Communication",
						"attached_to_name": comm.name,
						"folder": "Home/Attachments",
						"is_private": True,
						"content": _read_file_bytes(file_doc),
						"content_hash": file_doc.content_hash,
					}
				),
			)
			comm_file_doc.save(ignore_permissions=True)

		# Trigger notification with the validated signed PDF attached
		if notification_name:
			_send_esign_notification(notification_name, doc, file_doc, audit_data, pdf_hash)


def attach_print_to_document(
	doc: Document,
	print_format: str,
	request_data: RequestData,
	audit_data: AuditData,
	notification_name: str | None = None,
):
	"""Background job: render the signed PDF and attach it to the document.

	The audit trail (the Communication, its copy of the PDF and the notification) is written
	by `record_signature`, a second job queued to start once this job's transaction has
	committed. The File has to be committed before the Communication updates the document's
	`_comments`: cloud storage's file association may have changed the document too, and
	doing both in one transaction deadlocked.
	"""
	from frappe import attach_print

	with _job_request(request_data):
		# Refetch the document to ensure latest data
		doc.reload()

		# Generate the PDF
		timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
		print_data = attach_print(
			doctype=doc.doctype,
			name=doc.name,
			file_name=f"{doc.name}_signed_{timestamp_str}",
			print_format=print_format,
			doc=doc,
			print_letterhead=False,
		)

		# Compute SHA-256 hash of the PDF content
		pdf_content = print_data["fcontent"]
		pdf_hash = hashlib.sha256(pdf_content).hexdigest()

		# Attach the signed PDF to the document
		# Note: content_hash must be set explicitly for cloud_storage deduplication to work,
		# as cloud_storage's validate() doesn't call the core File validate which generates it
		file_doc = cast(
			File,
			frappe.get_doc(
				{
					"doctype": "File",
					"file_name": print_data["fname"],
					"attached_to_doctype": doc.doctype,
					"attached_to_name": doc.name,
					"folder": "Home/Attachments",
					"is_private": True,
					"content": pdf_content,
					"content_hash": get_content_hash(pdf_content),
				}
			),
		)
		file_doc.insert(ignore_permissions=True)

		if _is_cloud_storage_file(file_doc):
			# Extract s3_key from the file_url and persist it
			s3_key = str(file_doc.file_url or "").replace("/api/method/retrieve?key=", "")
			if s3_key:
				file_doc.db_set("s3_key", s3_key)

	frappe.enqueue(
		record_signature,
		queue="short",
		timeout=300,
		enqueue_after_commit=True,
		doctype=doc.doctype,
		name=doc.name,
		file_name=file_doc.name,
		pdf_hash=pdf_hash,
		request_data=request_data,
		audit_data=audit_data,
		notification_name=notification_name,
	)


def build_esign_link(
	doc: Document,
	web_form_name: str,
	print_format_name: str = "",
	recipient_email: str = "",
	bind: bool = True,
) -> str:
	"""The signing link for doc through the eSign web form, or "" when the form does not fit.

	With recipient_email, the link carries it as its `email` parameter and, when bind is true
	and it is one valid address, the `email_sig` binding that lets the signing page treat it
	as verified (see make_email_binding). send_esign_email passes bind=False when the same
	message also goes to other people, since anyone holding the link could then sign as the
	recipient.
	"""
	try:
		web_form = EsignWebForm("Web Form", web_form_name)
		if not web_form.esign_enabled or web_form.doc_type != doc.doctype:
			return ""

		# Generate the URL
		from urllib.parse import quote

		from frappe.utils import get_url

		base_url = get_url().rstrip("/")
		share_key = doc.get_document_share_key()
		web_form_path = f"/{(web_form.route or '').lstrip('/')}/{doc.name}/edit"
		query_string = f"?key={share_key}"
		if print_format_name:
			query_string += f"&format={print_format_name}"
		recipient_email = (recipient_email or "").strip()
		if recipient_email:
			query_string += f"&email={quote(recipient_email)}"
			if bind and _is_single_email(recipient_email):
				binding = make_email_binding(doc.doctype, str(doc.name), recipient_email)
				query_string += f"&{EMAIL_BINDING_PARAM}={binding}"

		return f"{base_url}{web_form_path}{query_string}"

	except Exception as e:
		frappe.log_error(
			title=f"eSign: Failed to generate link for {doc.doctype} {doc.name} and Web Form {web_form_name}",
			message=e,
		)
		return ""


@frappe.whitelist()
def get_esign_link(
	doc: Document | str | dict, web_form_name: str, print_format_name: str = "", recipient_email: str = ""
) -> str:
	"""Get the eSign Web Form link for a given document and web form name.

	Args:
		doc: The document (or JSON/dict) to generate the link for
		web_form_name: Name of the eSign-enabled Web Form
		print_format_name: Optional print format override
		recipient_email: Optional email of the intended signer. The link carries it as
			``&email=``, so the signing page pre-fills the form's email field with it. From
			Jinja or Python (doc is a Document) it also carries an ``&email_sig=`` binding,
			and the audit trail records the address as verified by the recipient link: send
			such a link to that recipient only. A request (doc is JSON or a dict) never gets
			the binding, since the caller, not the recipient, would hold it and could sign
			as them; send_esign_email emails a bound link instead.
	"""
	from_request = not isinstance(doc, Document)
	if isinstance(doc, str):
		try:
			doc = json.loads(doc)
		except Exception as e:
			return str(e)

	if isinstance(doc, dict):
		try:
			doc = frappe.get_doc(doc["doctype"], doc["name"])
		except Exception as e:
			return str(e)
		# A reference from a request: the link carries a share key that opens the document to
		# whoever holds it, and with recipient_email a binding that vouches for the address, so
		# the caller must be allowed to email the document (as for send_esign_email).
		# Server-side callers (Jinja, Python) pass the Document itself.
		frappe.has_permission(doc.doctype, ptype="email", doc=doc, throw=True)

	return build_esign_link(doc, web_form_name, print_format_name, recipient_email, bind=not from_request)


# Reviewed guest endpoint: validate_esign_access needs the share key, or the web form's or print permission.
@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
@rate_limit(key="web_form", limit=30, seconds=60)
def get_print_html(
	doctype: str, docname: str, print_format: str = "standard", key: str = "", web_form: str = ""
) -> PrintHtmlResponse:
	"""Get the print HTML and styles for a document.

	This endpoint allows async loading of the document preview in eSign forms.
	It validates permissions using the document share key if provided.

	Args:
		doctype: The DocType of the document
		docname: The name of the document
		print_format: The print format to use (default: "standard")
		key: The document share key, if any
		web_form: The eSign web form the page belongs to; without a key, its rules can admit
			the user (see validate_esign_access)

	Returns:
		PrintHtmlResponse with print_html and print_style
	"""
	from frappe.www.printview import (
		get_print_format_doc,
		get_print_style,
		get_rendered_template,
		set_link_titles,
	)

	# set the key, if provided
	if key:
		frappe.form_dict.key = key

	# Get the document without permission checks - we'll validate via share key
	doc = frappe.get_doc(doctype, docname)

	# Validate access via share key or fallback to standard permissions. This has to run
	# before the document or the request is marked permission-free: without a key, the
	# fallback is the standard print permission check, which ignore_print_permissions turns
	# off and which passes a document that carries ignore_permissions.
	validate_esign_access(key, doc, web_form)
	doc.flags.ignore_permissions = True

	# Access is granted: skip the renderer's own permission checks, which would only add
	# msgprint warnings for a Guest holding a valid key.
	frappe.flags.ignore_print_permissions = True

	# Get print format document
	meta = frappe.get_meta(doctype)
	print_format_doc = get_print_format_doc(print_format, meta=meta)
	set_link_titles(doc)

	# Get rendered print HTML
	print_html = get_rendered_template(
		doc=doc,
		print_format=print_format_doc,
		meta=meta,
		trigger_print=False,
		no_letterhead=bool(frappe.form_dict.get("no_letterhead")),
		letterhead=frappe.form_dict.get("letterhead"),
		settings=None,
	)

	# Get print styles
	print_style = get_print_style(
		style=frappe.form_dict.get("style"),
		print_format=print_format_doc,
	)

	# Clean up any local message log
	frappe.local.message_log = None

	return PrintHtmlResponse(
		print_html=print_html,
		print_style=print_style,
	)


# Reviewed guest endpoint: validate_esign_access needs the share key, or the web form's or print permission.
@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
@rate_limit(key="esign_download", limit=20, seconds=60)
def download_signed_pdf(doctype: str, docname: str, key: str = "", web_form: str = ""):
	"""Download a signed PDF attachment with key-based access validation.

	This endpoint allows Guest users to download private signed PDF files
	by validating access via the document share key instead of requiring login.

	Args:
		doctype: The DocType of the document
		docname: The name of the document
		key: The document share key for access validation
		web_form: The eSign web form the page belongs to; without a key, its rules can admit
			a logged-in user (see validate_esign_access)

	Returns:
		The PDF file response
	"""
	from frappe.core.doctype.access_log.access_log import make_access_log
	from frappe.utils.response import send_private_file

	# Get the document without permission checks - we'll validate via share key
	doc = frappe.get_doc(doctype, docname)

	# Validate access via share key - require key for guest access. Without a key a user
	# needs the web form's permission or print permission, which a document marked
	# ignore_permissions would skip.
	validate_esign_access(key, doc, web_form, require_key=(frappe.session.user == "Guest"))

	# Find the signed PDF for this document
	# First try to find an eSign Communication for this document
	comm = frappe.get_all(
		"Communication",
		filters={
			"reference_doctype": doctype,
			"reference_name": docname,
			"communication_type": "eSign",
		},
		fields=["name"],
		order_by="creation desc",
		limit=1,
	)

	pdf_file = None
	if comm:
		# Get the PDF attached to the Communication
		pdf_file = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Communication",
				"attached_to_name": comm[0].name,
				"file_name": ("like", "%.pdf"),
			},
			fields=["name", "file_name", "file_url", "is_private"],
			order_by="creation desc",
			limit=1,
		)

	if not pdf_file:
		# Fallback: look for signed PDFs attached directly to the document
		pdf_file = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": doctype,
				"attached_to_name": docname,
				"file_name": ("like", "%_signed_%.pdf"),
			},
			fields=["name", "file_name", "file_url", "is_private"],
			order_by="creation desc",
			limit=1,
		)

	if not pdf_file:
		frappe.throw(_("No signed PDF found for this document"), frappe.DoesNotExistError)

	file_doc = pdf_file[0]
	file_url = file_doc.get("file_url", "")

	# Log access for audit trail
	make_access_log(
		doctype="File",
		document=file_doc.get("name"),
		file_type="pdf",
	)

	# Handle cloud storage files — the /api/method/retrieve endpoint runs a permission
	# check (frappe.has_permission) that fails for Guest users authenticating via an
	# eSign print key.  The /api/method/share endpoint, however, generates a presigned
	# URL without any permission gate, so we set a sharing_link on the File and redirect
	# there instead.
	if file_url.startswith("/api/method/retrieve"):
		full_file = frappe.get_doc("File", file_doc.get("name"))
		sharing_link = full_file.get("sharing_link")
		if not sharing_link:
			# The same key format cloud_storage's own get_sharing_link writes.
			sharing_link = str(uuid.uuid4().int >> 64)
			full_file.db_set("sharing_link", sharing_link)
			# A GET request is rolled back at its end unless it asks to commit; the link must
			# exist by the time the browser follows the redirect.
			frappe.local.flags.commit = True
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = f"/api/method/share?key={sharing_link}"
		return

	# Handle private vs public files (local storage)
	if file_doc.get("is_private") and file_url.startswith("/private/files/"):
		# Extract the path after /private
		private_path = file_url.split("/private", 1)[1]
		return send_private_file(private_path)
	else:
		# For public files, redirect to the file URL
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = file_url


@frappe.whitelist()
def get_esign_web_forms(doctype: str):
	"""Get all eSign-enabled web forms for a given doctype."""
	return frappe.get_all(
		"Web Form",
		filters={"doc_type": doctype, "esign_enabled": 1, "published": 1},
		fields=["name", "title", "route", "print_format", "esign_require_verified_email"],
	)


def _get_client_ip() -> str | None:
	"""Get client IP address, accounting for proxies and load balancers."""
	if not hasattr(frappe, "request") or not frappe.request:
		return None

	headers = frappe.request.headers

	# Check various proxy headers in order of preference
	proxy_headers = [
		"CF-Connecting-IP",  # Cloudflare
		"X-Real-IP",  # Nginx proxy
		"X-Forwarded-For",  # Standard proxy header (may contain multiple IPs)
	]

	for header in proxy_headers:
		value = headers.get(header)
		if value:
			# X-Forwarded-For may contain multiple IPs, take the first (client)
			if "," in value:
				return value.split(",")[0].strip()
			return value.strip()

	# Fall back to remote_addr
	return getattr(frappe.request, "remote_addr", None)


def _collect_audit_data(
	doc: Document,
	wf: EsignWebForm,
	print_format: str,
	bound_email: str | None = None,
	consent_text: str | None = None,
	consent_timestamp: str | None = None,
) -> AuditData:
	"""Collect audit trail data at the moment of signing.

	bound_email is the address the signing link was bound to (see get_bound_email), if it
	carried a valid binding; consent_text and consent_timestamp record the signer's consent
	to sign electronically, as accept received it.

	Signer email resolution order:
		0. With Require Verified Email on the web form, the bound email, and nothing else
		1. With a Signer Email Field set on the web form, the valid address the signer
		submitted in it; the link's ``email`` parameter is then not used
		2. Without one, the bound email, or else the ``email`` URL search param (set when the
		eSign link was emailed)
		3. Without one, a Data field with Options="Email" on the web form (filled by the signer)
		4. The logged-in Frappe user (if not Guest)

	The email is recorded as verified (verified_via "recipient link") when it is the bound
	email.

	Signer name: only what the signer typed into the web form's Signer Name Field. A User's
	name is never looked up from an address, which the signer may have typed. Only on a web
	form without a Signer Name Field, a logged-in user signing as themselves (the signer
	email is their own login) is named after their own User.
	"""
	# Get IP address from various possible headers (proxy-aware)
	ip_address = _get_client_ip()

	# Get user agent
	user_agent = None
	if hasattr(frappe, "request") and frappe.request:
		user_agent = frappe.request.headers.get("User-Agent")

	# --- Resolve signer email ---
	signer_email = None

	if bound_email and wf.esign_require_verified_email:
		# 0. The web form only accepts the address the link was sent to.
		signer_email = bound_email
	elif _signer_fieldname(wf, "esign_signer_email_field"):
		# 1. The web form names the field the signer's email is in: record only what the
		# signer submitted there. It is their own input, so only a valid address is recorded.
		field_email = _signer_field_value(doc, wf, "esign_signer_email_field")
		if _is_single_email(field_email):
			signer_email = field_email
	else:
		# 2. From the email URL search param (link was sent via email): the bound one, or
		# else the parameter, which is the signer's own input, so only a valid address is
		# recorded.
		email_param = bound_email or extract_param_from_referrer("email")
		if _is_single_email(email_param):
			signer_email = email_param

		# 3. From a Data(Email) field on the web form
		if not signer_email:
			email_fieldname = _find_email_fieldname(wf)
			if email_fieldname:
				field_value = doc.get(email_fieldname)
				signer_email = str(field_value) if field_value else None

	# 4. Fall back to the logged-in user
	if not signer_email and frappe.session.user and frappe.session.user != "Guest":
		signer_email = frappe.session.user

	verified = bool(bound_email and _normalize_email(signer_email) == _normalize_email(bound_email))

	# The name the signer typed into the web form's Signer Name Field
	signer_name = _signer_field_value(doc, wf, "esign_signer_name_field")
	if signer_name:
		signer_name = signer_name[:SIGNER_NAME_LENGTH]
	elif (
		not _signer_fieldname(wf, "esign_signer_name_field")
		and frappe.session.user != "Guest"
		and _normalize_email(signer_email) == _normalize_email(frappe.session.user)
	):
		# No name field to type into: a logged-in user signing as themselves is named after
		# their own User record, never after one an address points to.
		full_name = frappe.db.get_value("User", frappe.session.user, "full_name")
		signer_name = str(full_name)[:SIGNER_NAME_LENGTH] if full_name else None

	# Identify which signature fields were filled
	signed_fields = []
	signature_fieldtypes = ("Signature", "SignaturePad")
	for field in wf.web_form_fields:
		if field.fieldtype in signature_fieldtypes:
			fieldname = _fieldname(field)
			if fieldname and doc.get(fieldname):
				signed_fields.append(field.label or fieldname)

	return AuditData(
		timestamp=now(),
		ip_address=ip_address,
		user_agent=user_agent,
		signer_email=signer_email,
		signer_name=signer_name,
		signer_email_verified=verified,
		verified_via=VERIFIED_VIA_LINK if verified else None,
		verified_email=bound_email or None,
		consent_text=consent_text,
		consent_timestamp=consent_timestamp,
		web_form=str(wf.title or wf.name),
		print_format=print_format,
		signed_fields=signed_fields,
	)


def _enqueue_print_attachment(
	doc: Document,
	wf: EsignWebForm,
	bound_email: str | None = None,
	consent_text: str | None = None,
	consent_timestamp: str | None = None,
):
	"""Enqueue background job to attach signed PDF to the document."""
	# Determine the print format to use
	print_format = extract_param_from_referrer("format")
	if not print_format:
		print_format = wf.print_format or "standard"

	# Extract only serializable data from request
	request = getattr(frappe.local, "request", None)
	headers = getattr(request, "headers", None)
	request_data: RequestData = {
		"host_url": getattr(request, "host_url", None),
		"scheme": getattr(request, "scheme", "https"),
		"host": getattr(request, "host", None),
		"headers": dict(headers) if headers is not None else {},
		"method": getattr(request, "method", None),
	}

	# Collect audit data
	audit_data = _collect_audit_data(doc, wf, print_format, bound_email, consent_text, consent_timestamp)

	# Get notification name if configured
	notification_name = None
	if wf.esign_send_notification and wf.esign_notification:
		notification_name = wf.esign_notification

	frappe.enqueue(
		attach_print_to_document,
		queue="short",
		job_id=f"attach_print_to_{doc.doctype}_{doc.name}",
		deduplicate=True,
		timeout=300,
		enqueue_after_commit=True,
		doc=doc,
		print_format=print_format,
		request_data=request_data,
		audit_data=audit_data,
		notification_name=notification_name,
	)


# Reviewed guest endpoint, as frappe's own web form accept: an update needs the share key or
# a write permission, and a new document only what the web form allows.
@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
@rate_limit(key="web_form", limit=10, seconds=60)
def accept(web_form: str, data: str, esign_consent: str | int | None = None):
	"""Custom accept function for eSign web forms that properly handles Guest permissions.

	This overrides the default web form accept to ensure that eSign forms with valid
	document share keys can be submitted by Guest users without permission errors.
	Also handles field updates, document submission, and PDF attachment in a single flow.

	Args:
		web_form: The web form's name
		data: The form's values, as JSON
		esign_consent: Truthy when the signer ticked the consent to sign electronically;
			an eSign web form refuses to sign without it
	"""
	from frappe.website.doctype.web_form.web_form import accept as base_accept

	form = frappe._dict(json.loads(data))

	# Check if this is an eSign-enabled web form
	wf = cast(EsignWebForm, frappe.get_lazy_doc("Web Form", web_form))

	# If not eSign-enabled, use the base accept function
	if not getattr(wf, "esign_enabled", False):
		return base_accept(web_form, json.dumps(form))

	# For eSign forms, we need to handle permissions specially
	doctype = wf.doc_type
	user = frappe.session.user

	# Extract key from referrer for permission validation
	if not frappe.form_dict.get("key"):
		frappe.form_dict.key = extract_param_from_referrer("key")

	# Validate the key if we have one and this is an update
	if form.name and frappe.form_dict.get("key"):
		try:
			# Validate the key gives us access to this document
			doc = frappe.get_doc(doctype, form.name)
			validate_print_permission(doc)
		except frappe.PermissionError, frappe.exceptions.LinkExpired:
			frappe.throw(_("Invalid or expired access key"), frappe.PermissionError)

	# An update needs the document's share key, web form write permission or DocType write
	# permission: the three ways frappe's own accept lets an update through (the last one by
	# saving with permission checks on). Otherwise anyone who knows a document name could
	# overwrite its form fields.
	if form.name:
		# The share key admits a write here only (see EsignWebForm.has_web_form_permission).
		frappe.flags.esign_key_write = True
		try:
			allowed = wf.has_web_form_permission(doctype, form.name, "write")
		finally:
			frappe.flags.esign_key_write = False
		if not allowed and not frappe.has_permission(doctype, "write", form.name):
			frappe.throw(_("You are not permitted to update this document"), frappe.PermissionError)

	# The address the signing link was sent to, when the link binds it to this document. With
	# Require Verified Email, a link without a valid binding (or a new document, which no
	# link names) is refused here, before anything is written.
	bound_email = _require_bound_email(
		wf,
		doctype,
		form.name,
		extract_param_from_referrer("email"),
		extract_param_from_referrer(EMAIL_BINDING_PARAM),
	)

	# Consent to sign electronically (ESIGN Act, UETA): the signer ticks it on the signing
	# page, and the text they agreed to is recorded with the time it was received.
	consent_text = get_consent_text(wf)
	if not cint(esign_consent):
		frappe.throw(
			_("To sign, tick the box: {0}").format(consent_text),
			title=_("Consent Required"),
		)
	consent_timestamp = now()

	# Now proceed with the form submission using ignore_permissions
	files = []
	files_to_delete = []

	if wf.anonymous and frappe.session.user != "Guest":
		frappe.session.user = "Guest"

	try:
		if form.name and not wf.allow_edit:
			frappe.throw(_("You are not allowed to update this Web Form Document"))

		frappe.flags.in_web_form = True
		meta = frappe.get_meta(doctype)

		is_new = not form.name
		# For eSign forms, always get doc with ignore_permissions since we validated the key
		doc = frappe.get_doc(doctype, form.name) if form.name else frappe.new_doc(doctype)

		# Set ignore_mandatory flag if allow_incomplete is enabled
		if wf.allow_incomplete:
			doc.flags.ignore_mandatory = True

		# Allow setting set_only_once fields (like signatures) that haven't been set yet.
		# eSign forms are specifically designed to allow first-time setting of signature
		# fields on submitted documents via key-based access.
		doc.flags.ignore_validate_constants = True

		# Set web form field values
		for field in wf.web_form_fields:
			fieldname = _fieldname(field)
			df = meta.get_field(fieldname)
			value = form.get(fieldname, "")

			if df and df.fieldtype in ("Attach", "Attach Image"):
				if value and "data:" in value and "base64" in value:
					files.append((fieldname, value))
					if not doc.name:
						doc.set(fieldname, "")
					continue

				elif not value and doc.get(fieldname):
					files_to_delete.append(doc.get(fieldname))

			doc.set(fieldname, value)

		# The verified address replaces whatever was submitted in the email field: the page
		# shows it read-only, and a request that changed it is not believed.
		if bound_email and wf.esign_require_verified_email and (email_fieldname := _email_fieldname(wf)):
			doc.set(email_fieldname, bound_email)

		# Apply eSign field update if configured
		if wf.esign_update_field and wf.esign_update_value is not None:
			try:
				if meta.has_field(wf.esign_update_field):
					df = meta.get_field(wf.esign_update_field)
					if df and df.fieldtype in UPDATE_FIELD_TYPES:
						doc.set(wf.esign_update_field, wf.esign_update_value)
			except Exception as e:
				frappe.log_error(
					title=f"eSign: Failed to set field {wf.esign_update_field} on {doc.doctype}",
					message=str(e),
				)

		# Set docstatus for submission if configured (before save)
		should_submit = (
			wf.esign_submit_on_response and doc.docstatus == 0 and getattr(doc.meta, "is_submittable", False)
		)
		if should_submit:
			doc.flags.ignore_permissions = True
			doc.docstatus = DocStatus(1)

		# For new documents, we need to insert first before attaching files
		if is_new:
			if wf.login_required and frappe.session.user == "Guest":
				frappe.throw(_("You must login to submit this form"))

			ignore_mandatory = bool(files or wf.allow_incomplete)
			doc.insert(ignore_permissions=True, ignore_mandatory=ignore_mandatory)

		# Handle file attachments - these require the doc to exist first
		if files:
			for f in files:
				fieldname, filedata = f

				# remove earlier attached file (if exists)
				if doc.get(fieldname):
					remove_file_by_url(str(doc.get(fieldname)), doctype=doctype, name=doc.name)

				# save new file
				filename, dataurl = filedata.split(",", 1)
				_file = cast(
					File,
					frappe.get_doc(
						{
							"doctype": "File",
							"file_name": filename,
							"attached_to_doctype": doctype,
							"attached_to_name": doc.name,
							"content": dataurl,
							"decode": True,
						}
					),
				)
				_file.save(ignore_permissions=True)

				# update the doc with file URL
				doc.set(fieldname, _file.file_url)

		# Single save for all changes (existing docs or new docs with files)
		if not is_new or files:
			doc.save(ignore_permissions=True)

		# Clean up deleted files
		if files_to_delete:
			for f in files_to_delete:
				if f:
					remove_file_by_url(f, doctype=doctype, name=doc.name)
	finally:
		# Restore user session if needed (also on error, so the request isn't left as Guest)
		if wf.anonymous and frappe.session.user == "Guest" and user:
			frappe.session.user = user

	frappe.flags.web_form_doc = doc

	# Enqueue PDF attachment as background job
	_enqueue_print_attachment(doc, wf, bound_email, consent_text, consent_timestamp)

	# Clean up any local message log
	frappe.local.message_log = None

	return doc
