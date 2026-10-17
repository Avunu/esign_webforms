# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import hashlib
import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import TypedDict, cast

import frappe
from frappe import _
from frappe.core.doctype.file.file import File
from frappe.core.doctype.file.utils import get_content_hash, remove_file_by_url
from frappe.core.doctype.user.user import User
from frappe.email.doctype.notification.notification import Notification
from frappe.model import numeric_fieldtypes
from frappe.model.docstatus import DocStatus
from frappe.model.document import Document
from frappe.rate_limiter import rate_limit
from frappe.twofactor import get_qr_svg_code
from frappe.types import DF
from frappe.utils import cint, escape_html, get_frappe_version, now
from frappe.website.doctype.web_form.web_form import WebForm as BaseWebForm
from frappe.www.printview import validate_print_permission


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
	"""Audit trail data captured at signing time."""

	timestamp: str
	ip_address: str | None
	user_agent: str | None
	signer_email: str | None
	signer_name: str | None
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


class EsignWebForm(BaseWebForm):
	"""eSign behaviour for Web Form, registered through `extend_doctype_class`.

	Frappe composes the final controller from the stock WebForm and every installed app's
	extension (payments registers one too), so this subclasses the stock WebForm only:
	subclassing another app's extension would break the class hierarchy whenever that app is
	installed after esign.
	"""

	# Custom fields from ../custom/web_form.json
	esign_enabled: DF.Check | None
	esign_force_mobile: DF.Check | None
	# A Select whose options are the target doctype's fields, set at runtime (web_form.js).
	esign_update_field: DF.Data | None
	esign_update_value: DF.Data | None
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
		# the fallback) passes any document that already carries ignore_permissions.
		validate_esign_key(key, doc)
		doc.flags.ignore_permissions = True

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

		# Pre-fill email field from URL param (e.g. when link was sent via email)
		email_param = frappe.form_dict.get("email", "")
		if email_param:
			email_fieldname = _find_email_fieldname(self)
			if email_fieldname and email_fieldname in form_fields:
				context.reference_doc[email_fieldname] = email_param

		super().add_custom_context_and_script(context)

		context.key = key  # Pass key to frontend for async API calls
		context.printview_url = (
			"/api/method/frappe.utils.print_format.download_pdf?"
			f"doctype={self.doc_type}&name={cur_doc_name}&format={print_format}&key={key}"
		)
		# Include eSign assets
		context.web_include_css.extend(
			[
				"esign.control.bundle.css",
				"esign.web.bundle.css",
				"/assets/esign/dist/esign-fonts.css",
			]
		)
		context.web_include_js.extend(
			[
				"esign.web.bundle.js",
			]
		)
		context.template = "esign/templates/esign.html"
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

				params = urlencode({"doctype": self.doc_type, "docname": cur_doc_name, "key": key})
				context.signed_pdf_url = (
					f"/api/method/esign.esign.custom.web_form.download_signed_pdf?{params}"
				)
				context.signed_pdf_name = signed_pdf.get("file_name")

		context.frappe_version = get_frappe_version()

		return context

	def validate(self):
		super().validate()

		# if esign is enabled, force allow_edit
		if self.esign_enabled:
			self.allow_edit = True

	def has_web_form_permission(self, doctype, name, ptype="read"):
		"""Override to allow eSign access for Guest users with valid keys"""
		# For eSign forms, check key-based access first
		if self.esign_enabled and name:
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
			subject = frappe.render_template(subject, context)  # nosemgrep: frappe-ssti

		message = frappe.render_template(notification.message, context) or ""  # nosemgrep: frappe-ssti

		# Append audit trail information to the notification email
		if audit_data:
			audit_rows = []
			if audit_data.get("signer_name"):
				audit_rows.append((_("Signer"), audit_data["signer_name"]))
			if audit_data.get("signer_email"):
				audit_rows.append((_("Email"), audit_data["signer_email"]))
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
	with open(file_doc.get_full_path(), "rb") as f:
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


@frappe.whitelist()
def get_esign_link(
	doc: Document | str | dict, web_form_name: str, print_format_name: str = "", recipient_email: str = ""
) -> str:
	"""Get the eSign Web Form link for a given document and web form name.

	Args:
		doc: The document (or JSON/dict) to generate the link for
		web_form_name: Name of the eSign-enabled Web Form
		print_format_name: Optional print format override
		recipient_email: Optional email of the intended signer; appended as
			``&email=`` so the web form can pre-fill a Data(Email) field and
			record the signer in the audit trail.
	"""
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
		# whoever holds it, so the caller must be allowed to email the document (as for
		# send_esign_email). Server-side callers (Jinja, Python) pass the Document itself.
		frappe.has_permission(doc.doctype, ptype="email", doc=doc, throw=True)

	try:
		web_form = EsignWebForm("Web Form", web_form_name)
		if not web_form.esign_enabled or web_form.doc_type != doc.doctype:
			return ""

		# Generate the URL
		from frappe.utils import get_url

		base_url = get_url().rstrip("/")
		share_key = doc.get_document_share_key()
		web_form_path = f"/{(web_form.route or '').lstrip('/')}/{doc.name}/edit"
		query_string = f"?key={share_key}"
		if print_format_name:
			query_string += f"&format={print_format_name}"
		if recipient_email:
			from urllib.parse import quote

			query_string += f"&email={quote(recipient_email)}"

		return f"{base_url}{web_form_path}{query_string}"

	except Exception as e:
		frappe.log_error(
			title=f"eSign: Failed to generate link for {doc.doctype} {doc.name} and Web Form {web_form_name}",
			message=e,
		)
		return ""


@frappe.whitelist(allow_guest=True)
@rate_limit(key="web_form", limit=30, seconds=60)
def get_print_html(
	doctype: str, docname: str, print_format: str = "standard", key: str = ""
) -> PrintHtmlResponse:
	"""Get the print HTML and styles for a document.

	This endpoint allows async loading of the document preview in eSign forms.
	It validates permissions using the document share key if provided.

	Args:
		doctype: The DocType of the document
		docname: The name of the document
		print_format: The print format to use (default: "standard")

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
	validate_esign_key(key, doc)
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


@frappe.whitelist(allow_guest=True)
@rate_limit(key="esign_download", limit=20, seconds=60)
def download_signed_pdf(doctype: str, docname: str, key: str = ""):
	"""Download a signed PDF attachment with key-based access validation.

	This endpoint allows Guest users to download private signed PDF files
	by validating access via the document share key instead of requiring login.

	Args:
		doctype: The DocType of the document
		docname: The name of the document
		key: The document share key for access validation

	Returns:
		The PDF file response
	"""
	from frappe.core.doctype.access_log.access_log import make_access_log
	from frappe.utils.response import send_private_file

	# Get the document without permission checks - we'll validate via share key
	doc = frappe.get_doc(doctype, docname)

	# Validate access via share key - require key for guest access. Without a key a user
	# needs print permission, which a document marked ignore_permissions would skip.
	validate_esign_key(key, doc, require_key=(frappe.session.user == "Guest"))

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
def get_esign_web_forms(doctype):
	"""Get all eSign-enabled web forms for a given doctype."""
	return frappe.get_all(
		"Web Form",
		filters={"doc_type": doctype, "esign_enabled": 1, "published": 1},
		fields=["name", "title", "route", "print_format"],
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


def _collect_audit_data(doc: Document, wf: EsignWebForm, print_format: str) -> AuditData:
	"""Collect audit trail data at the moment of signing.

	Signer email resolution order:
		1. ``email`` URL search param (set when the eSign link was emailed)
		2. A Data field with Options="Email" on the web form (filled by the signer)
		3. The logged-in Frappe user (if not Guest)
	"""
	# Get IP address from various possible headers (proxy-aware)
	ip_address = _get_client_ip()

	# Get user agent
	user_agent = None
	if hasattr(frappe, "request") and frappe.request:
		user_agent = frappe.request.headers.get("User-Agent")

	# --- Resolve signer email ---
	signer_email = None
	signer_name = None

	# 1. From the email URL search param (link was sent via email)
	email_param = extract_param_from_referrer("email")
	if email_param:
		signer_email = email_param

	# 2. From a Data(Email) field on the web form
	if not signer_email:
		email_fieldname = _find_email_fieldname(wf)
		if email_fieldname:
			field_value = doc.get(email_fieldname)
			signer_email = str(field_value) if field_value else None

	# 3. Fall back to the logged-in user
	if not signer_email and frappe.session.user and frappe.session.user != "Guest":
		signer_email = frappe.session.user

	# Resolve signer name from user record when we have an email that matches a User
	if signer_email:
		try:
			user_doc = cast(User, frappe.get_cached_doc("User", signer_email))
			signer_name = user_doc.full_name if user_doc else None
		except frappe.DoesNotExistError:
			pass

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
		web_form=str(wf.title or wf.name),
		print_format=print_format,
		signed_fields=signed_fields,
	)


def _enqueue_print_attachment(doc: Document, wf: EsignWebForm):
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
	audit_data = _collect_audit_data(doc, wf, print_format)

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


@frappe.whitelist(allow_guest=True)
@rate_limit(key="web_form", limit=10, seconds=60)
def accept(web_form, data):
	"""Custom accept function for eSign web forms that properly handles Guest permissions.

	This overrides the default web form accept to ensure that eSign forms with valid
	document share keys can be submitted by Guest users without permission errors.
	Also handles field updates, document submission, and PDF attachment in a single flow.
	"""
	from frappe.website.doctype.web_form.web_form import accept as base_accept

	data = frappe._dict(json.loads(data))

	# Check if this is an eSign-enabled web form
	wf = cast(EsignWebForm, frappe.get_lazy_doc("Web Form", web_form))

	# If not eSign-enabled, use the base accept function
	if not getattr(wf, "esign_enabled", False):
		return base_accept(web_form, json.dumps(data))

	# For eSign forms, we need to handle permissions specially
	doctype = wf.doc_type
	user = frappe.session.user

	# Extract key from referrer for permission validation
	if not frappe.form_dict.get("key"):
		frappe.form_dict.key = extract_param_from_referrer("key")

	# Validate the key if we have one and this is an update
	if data.name and frappe.form_dict.get("key"):
		try:
			# Validate the key gives us access to this document
			doc = frappe.get_doc(doctype, data.name)
			validate_print_permission(doc)
		except frappe.PermissionError, frappe.exceptions.LinkExpired:
			frappe.throw(_("Invalid or expired access key"), frappe.PermissionError)

	# An update needs the document's share key or web form write permission, as in frappe's
	# own accept; otherwise anyone who knows a document name could overwrite its form fields.
	if data.name and not wf.has_web_form_permission(doctype, data.name, "write"):
		frappe.throw(_("You are not permitted to update this document"), frappe.PermissionError)

	# Now proceed with the form submission using ignore_permissions
	files = []
	files_to_delete = []

	if wf.anonymous and frappe.session.user != "Guest":
		frappe.session.user = "Guest"

	try:
		if data.name and not wf.allow_edit:
			frappe.throw(_("You are not allowed to update this Web Form Document"))

		frappe.flags.in_web_form = True
		meta = frappe.get_meta(doctype)

		is_new = not data.name
		# For eSign forms, always get doc with ignore_permissions since we validated the key
		doc = frappe.get_doc(doctype, data.name) if data.name else frappe.new_doc(doctype)

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
			value = data.get(fieldname, "")

			if df and df.fieldtype in ("Attach", "Attach Image"):
				if value and "data:" in value and "base64" in value:
					files.append((fieldname, value))
					if not doc.name:
						doc.set(fieldname, "")
					continue

				elif not value and doc.get(fieldname):
					files_to_delete.append(doc.get(fieldname))

			doc.set(fieldname, value)

		# Apply eSign field update if configured
		if wf.esign_update_field and wf.esign_update_value is not None:
			try:
				if meta.has_field(wf.esign_update_field):
					df = meta.get_field(wf.esign_update_field)
					if df and df.fieldtype in ("Select", "Link", "Data", "Text"):
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
	_enqueue_print_attachment(doc, wf)

	# Clean up any local message log
	frappe.local.message_log = None

	return doc
