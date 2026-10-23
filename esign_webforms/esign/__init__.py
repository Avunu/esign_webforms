# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

import contextlib
import json

import frappe

# Imported as a module and looked up at call time, so a patched get_attachments (cloud_storage
# replaces it) is the one called.
import frappe.desk.form.load
from frappe import _
from frappe.core.doctype.communication.communication import Communication
from frappe.utils import cint, escape_html, now, validate_email_address

# Communication type for eSign audit trail
ESIGN_COMMUNICATION_TYPE = "eSign"


def _escape(value: object) -> str | None:
	"""A stored audit value, HTML-escaped for the timeline card (None stays None)."""
	return None if value is None else escape_html(str(value))


def get_timeline_content(doctype: str, docname: str) -> list[dict]:
	"""Return eSign audit trail entries for the document timeline.

	This hook is called by Frappe's timeline rendering to add custom
	timeline entries showing eSign signing events with audit details.
	"""
	communications = frappe.get_all(
		"Communication",
		filters={
			"reference_doctype": doctype,
			"reference_name": docname,
			"communication_type": ESIGN_COMMUNICATION_TYPE,
		},
		fields=[
			"creation",
			"name",
			"communication_date",
			"content",
			"sender",
			"sender_full_name",
		],
		order_by="creation desc",
	)

	timeline_contents = []
	for comm in communications:
		# Parse the JSON content for audit data
		audit_data = {}
		if comm.content:
			with contextlib.suppress(json.JSONDecodeError, TypeError):
				audit_data = json.loads(comm.content)

		# Get the attached signed PDF file URL using the patched get_attachments
		# This works for both standard Frappe and cloud_storage setups
		file_url = None
		attachments = frappe.desk.form.load.get_attachments("Communication", comm.name)
		for attachment in attachments:
			if attachment.get("file_name", "").endswith(".pdf"):
				file_url = attachment.get("file_url")
				break

		timeline_contents.append(
			{
				"icon": "edit",
				"is_card": True,
				"creation": comm.communication_date or comm.creation,
				"template": "esign_timeline",
				# The timeline template prints these unescaped ({{ }} is raw in frappe's
				# microtemplates), and the signer controls several of them (user agent, email
				# parameter, form fields), so every value is escaped here.
				"template_data": {
					"creation": str(comm.creation),
					"file_url": _escape(file_url),
					"signer_name": _escape(audit_data.get("signer_name") or comm.sender_full_name),
					"signer_email": _escape(audit_data.get("signer_email") or comm.sender),
					"email_verified": bool(audit_data.get("signer_email_verified")),
					# The address the link was bound to, shown only when the signer entered another.
					"verified_email": None
					if audit_data.get("signer_email_verified")
					else _escape(audit_data.get("verified_email")),
					"consent_text": _escape(audit_data.get("consent_text")),
					"consent_timestamp": _escape(audit_data.get("consent_timestamp")),
					"timestamp": _escape(audit_data.get("timestamp")),
					"ip_address": _escape(audit_data.get("ip_address")),
					"user_agent": _escape(audit_data.get("user_agent")),
					"web_form": _escape(audit_data.get("web_form")),
					"print_format": _escape(audit_data.get("print_format")),
					"signed_fields": [_escape(field) for field in audit_data.get("signed_fields") or []],
					"pdf_hash": _escape(audit_data.get("pdf_hash")),
				},
			}
		)

	return timeline_contents


@frappe.whitelist()
def can_esign(doctype: str, doc: str | dict) -> bool:
	"""Check if eSign is enabled for the given document type and document."""
	hooks = frappe.get_hooks("can_esign", {}).get(doctype)
	if hooks:
		if isinstance(doc, str):
			doc = frappe._dict(json.loads(doc))

		for method in hooks:
			# The methods are the installed apps' can_esign hooks, never a request argument.
			result = frappe.call(method, doc=doc)  # nosemgrep: frappe-codeinjection-eval
			if not result:
				return False
		return True

	esign_web_form = frappe.db.exists(
		"Web Form", dn={"doc_type": doctype, "published": 1, "esign_enabled": 1}
	)

	return bool(esign_web_form)


def _split_addresses(value: str | list[str] | None) -> list[str]:
	"""A To, CC or BCC value (comma-separated or a list) as a list of addresses."""
	if not value:
		return []
	if isinstance(value, str):
		return [address.strip() for address in value.split(",") if address.strip()]
	return list(value)


def _make_link(doc, web_form: str, print_format: str | None, recipient_email: str, bind: bool = True) -> str:
	"""The signing link (see build_esign_link), refusing to send an email without one."""
	from esign_webforms.esign.custom.web_form import build_esign_link

	esign_link = build_esign_link(doc, web_form, print_format or "", recipient_email, bind)
	if not esign_link:
		frappe.throw(_("Failed to generate eSign link"))
	return esign_link


def _send_esign_message(
	doc,
	recipients_list: list[str],
	cc_list: list[str],
	bcc_list: list[str],
	subject: str,
	message: str,
	esign_link: str,
	print_format: str | None,
	send_me_a_copy: bool,
	email_account: str | None,
) -> str:
	"""Send one eSign request email and record it as a Communication; returns its name."""
	from esign_webforms.esign.custom.web_form import strip_email_binding

	doctype, name = doc.doctype, doc.name

	# Prepare email content with eSign link
	email_content = message

	# Add eSign link to the email content if not already present
	if esign_link not in email_content:
		link_html = f"""
		<div style="margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-left: 4px solid #007bff; border-radius: 4px;">
			<h4 style="margin: 0 0 10px 0; color: #007bff;">{_("eSign Required")}</h4>
			<p style="margin: 0 0 10px 0;">{_("Please click the link below to review and sign the document:")}</p>
			<a href="{esign_link}"
				style="display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 4px; font-weight: bold;"
				target="_blank">
				{_("Sign Document")}
			</a>
		</div>
		"""
		email_content += link_html

	try:
		# Resolve sender from email account if provided
		sender = frappe.session.user
		if email_account:
			account_email = frappe.db.get_value("Email Account", email_account, "email_id")
			if account_email:
				sender = account_email

		# Create communication record
		comm = Communication(
			{
				"doctype": "Communication",
				"communication_type": "Automated Message",
				"communication_medium": "Email",
				"sent_or_received": "Sent",
				"email_status": "Open",
				"subject": subject,
				# The recipient gets the link with its email binding; the record anyone who
				# reads the document can open keeps the link without it.
				"content": email_content.replace(esign_link, strip_email_binding(esign_link)),
				"sender": sender,
				"email_account": email_account or None,
				"recipients": ", ".join(recipients_list),
				"cc": ", ".join(cc_list) if cc_list else "",
				"bcc": ", ".join(bcc_list) if bcc_list else "",
				"reference_doctype": doctype,
				"reference_name": name,
				"status": "Linked",
				"email_template": None,
				"has_attachment": 0,
				"communication_date": now(),
			}
		)
		comm.insert(ignore_permissions=True)

		# Send the email
		send_mail_args = comm.sendmail_input_dict(
			print_html=None,
			print_format=print_format,
			send_me_a_copy=send_me_a_copy,
			print_letterhead=False,
			is_inbound_mail_communcation=False,
			print_language=None,
		)

		send_mail_args["content"] = email_content

		frappe.sendmail(now=True, **send_mail_args)

		return str(comm.name)

	except Exception as e:
		frappe.log_error(title=f"eSign: Failed to send email for {doctype} {name}", message=str(e))
		frappe.throw(_("Failed to send eSign email: {0}").format(str(e)))
		raise  # frappe.throw always raises; this says so to the type checker


@frappe.whitelist(methods=["POST"])
def send_esign_email(
	doctype: str,
	name: str,
	recipients: str | list[str],
	subject: str,
	message: str,
	web_form: str,
	cc: str | list[str] | None = None,
	bcc: str | list[str] | None = None,
	print_format: str | None = None,
	send_me_a_copy: bool = False,
	email_account: str | None = None,
):
	"""Send eSign email with embedded eSign link"""

	# Validate inputs
	if not all([doctype, name, recipients, subject, message, web_form]):
		frappe.throw(_("Missing required parameters for eSign email"))

	# Get the document
	try:
		doc = frappe.get_doc(doctype, name)
	except frappe.DoesNotExistError:
		frappe.throw(_("Document {0} {1} not found").format(doctype, name))

	# The email carries a share key that opens the document to its recipients, so the sender
	# needs the same permission frappe's own email dialog asks for.
	frappe.has_permission(doctype, ptype="email", doc=name, throw=True)

	# Validate web form
	from esign_webforms.esign.custom.web_form import EsignWebForm, strip_email_binding

	try:
		web_form_doc = EsignWebForm("Web Form", web_form)
		if not web_form_doc.esign_enabled or web_form_doc.doc_type != doctype:
			frappe.throw(_("Invalid eSign web form for this document type"))
	except frappe.DoesNotExistError:
		frappe.throw(_("Web Form {0} not found").format(web_form))

	# A request may send the checkbox as "0" or "1".
	send_me_a_copy = bool(cint(send_me_a_copy))
	recipients_list = _split_addresses(recipients)
	if not recipients_list:
		frappe.throw(_("No valid recipients provided"))
	cc_list = _split_addresses(cc)
	bcc_list = _split_addresses(bcc)

	# Add current user to recipients if send_me_a_copy is True
	if send_me_a_copy and frappe.session.user != "Guest":
		user_email = str(frappe.db.get_value("User", frappe.session.user, "email"))
		if user_email and user_email not in recipients_list:
			bcc_list.append(user_email)

	# Each message and the link it carries. A link bound to a recipient's email (see
	# make_email_binding) makes the audit trail record that address as verified, so it may
	# only reach that recipient: anyone else holding it could sign as them.
	messages: list[tuple[list[str], str]] = []
	if web_form_doc.esign_require_verified_email:
		# Every signer needs their own bound link: one email per recipient, to them alone.
		if cc_list or bcc_list or send_me_a_copy:
			frappe.throw(
				_(
					"{0} requires a verified email, so each recipient gets their own signing link. "
					"Put everyone who signs in To, and leave CC, BCC and Send me a copy empty."
				).format(web_form_doc.title or web_form),
				title=_("One Link per Signer"),
			)
		for recipient in recipients_list:
			address = validate_email_address(recipient)
			if not address or "," in address:
				frappe.throw(_("{0} is not a valid email address").format(recipient))
			messages.append(([recipient], _make_link(doc, web_form, print_format, address)))
	else:
		# One message to everyone. With a single recipient, the link carries their address
		# so the signing page pre-fills it; it is bound (verified) only when nobody else gets
		# the message. One link sent to several recipients cannot name the one who signs.
		# Only the address is used, so a "Name <address>" recipient still pre-fills a valid
		# email (and an invalid one names nobody).
		recipient_email = validate_email_address(recipients_list[0]) if len(recipients_list) == 1 else ""
		sole_recipient = not (cc_list or bcc_list or send_me_a_copy)
		messages.append(
			(recipients_list, _make_link(doc, web_form, print_format, recipient_email, sole_recipient))
		)

	communications = [
		_send_esign_message(
			doc,
			to,
			cc_list,
			bcc_list,
			subject,
			message,
			esign_link,
			print_format,
			send_me_a_copy,
			email_account,
		)
		for to, esign_link in messages
	]

	return {
		"success": True,
		"message": _("eSign request sent successfully"),
		"communication": communications[0],
		"communications": communications,
		# Without the binding: only the recipient's email carries it (see strip_email_binding).
		"esign_link": strip_email_binding(messages[0][1]),
	}
