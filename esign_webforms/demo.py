# Copyright (c) 2026, Avunu LLC and contributors
# For license information, please see license.txt

"""Demo data for frappe-demo and the screenshots in docs/screenshots/.

The app has no DocTypes of its own: it adds eSign to Web Forms. The demo is a small,
submittable "Service Agreement" DocType with a Signature field, a print format for it, the
eSign web form customers sign it through and an eSign email template. Two agreements are
made: one waiting for a signature, and one that was signed, with its signed PDF and the
eSign audit record that `record_signature` writes after a real signing.
"""

import base64
import datetime
import hashlib
import io
from typing import Any

import frappe
from frappe.utils import add_days
from frappe.utils.pdf import get_pdf
from PIL import Image, ImageDraw

from esign_webforms.esign.custom.web_form import AuditData, RequestData, record_signature

DOCTYPE = "Service Agreement"
PRINT_FORMAT = "Service Agreement"
WEB_FORM = "service-agreement"
EMAIL_TEMPLATE = "Service Agreement for Signature"
UNSIGNED = "DEMO-AGR-001"
SIGNED = "DEMO-AGR-002"

TERMS = (
	"The provider delivers the service described above from the start date, and the customer "
	"pays the monthly fee within 15 days of each invoice. Either party may end the agreement "
	"with 30 days' written notice."
)

PRINT_HTML = """<div class="agreement">
	<div class="agreement-head">
		<h2>Service Agreement</h2>
		<div class="agreement-ref">{{ doc.name }}</div>
	</div>
	<p>This agreement is made between <strong>Lakeside IT Services</strong> (the provider) and
	<strong>{{ doc.customer }}</strong> (the customer).</p>
	<table class="agreement-table">
		<tr><th>Service</th><td>{{ doc.service }}</td></tr>
		<tr><th>Start date</th><td>{{ frappe.utils.formatdate(doc.start_date, "MMMM d, yyyy") }}</td></tr>
		<tr><th>Monthly fee</th><td>{{ doc.get_formatted("monthly_fee") }}</td></tr>
	</table>
	<h4>Terms</h4>
	<p>{{ doc.terms }}</p>
	<div class="agreement-sign">
		<div class="agreement-sign-box">
			{% if doc.signature and "signature-placeholder" not in doc.signature %}<img src="{{ doc.signature }}" alt="">{% endif %}
		</div>
		<div class="agreement-sign-line">
			{{ doc.signer_name or "Signature" }}{% if doc.signer_email %} &middot; {{ doc.signer_email }}{% endif %}
		</div>
	</div>
</div>"""

PRINT_CSS = """.agreement { font-size: 14px; line-height: 1.6; color: #1f272e; }
.agreement-head { display: flex; justify-content: space-between; align-items: baseline;
	border-bottom: 2px solid #1f272e; margin-bottom: 18px; }
.agreement-head h2 { margin: 0 0 6px; }
.agreement-ref { color: #687178; }
.agreement-table { width: 100%; margin: 16px 0; border-collapse: collapse; }
.agreement-table th, .agreement-table td { padding: 6px 8px; border-bottom: 1px solid #e2e6e9;
	text-align: left; }
.agreement-table th { width: 30%; color: #687178; font-weight: 500; }
.agreement-sign { margin-top: 40px; width: 60%; }
.agreement-sign-box { height: 90px; }
.agreement-sign-box img { height: 90px; }
.agreement-sign-line { border-top: 1px solid #1f272e; padding-top: 4px; color: #687178; }"""

# Email templates are rendered with the document's fields as the context, not as `doc`.
EMAIL_SUBJECT = "Service agreement {{ name }} for your signature"
EMAIL_MESSAGE = """<p>Hello,</p>
<p>Thank you for choosing us. Your service agreement for <strong>{{ service }}</strong>,
starting {{ frappe.utils.formatdate(start_date, "MMMM d, yyyy") }}, is ready to sign.</p>
<p>Use the button below to read it and sign it on any device.</p>"""

# The signing request and signer the signed agreement's audit record describes. The values
# are the ones the signing page records (_collect_audit_data); 203.0.113.0/24 is a
# documentation range.
SIGNER_EMAIL = "dana.whitfield@example.com"
SIGNER_AGENT = (
	"Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
	"(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)
REQUEST: RequestData = {
	"host_url": "http://localhost/",
	"scheme": "http",
	"host": "localhost",
	"headers": {"User-Agent": SIGNER_AGENT},
	"method": "POST",
}


# A signature, "Dana Whitfield", as the pen strokes' control points on the 750 x 292 canvas
# the signature control saves. marketplace/screenshots.ts draws the same strokes on the pad.
STROKES: list[list[tuple[int, int]]] = [
	[
		(148, 92),
		(140, 140),
		(130, 185),
		(122, 212),
		(104, 218),
		(94, 206),
		(112, 196),
		(166, 188),
		(206, 160),
		(212, 124),
		(184, 98),
		(136, 92),
		(90, 106),
	],
	[
		(206, 200),
		(222, 176),
		(236, 170),
		(230, 196),
		(244, 200),
		(258, 174),
		(268, 172),
		(262, 198),
		(276, 200),
		(290, 176),
		(302, 174),
		(296, 198),
		(312, 202),
		(326, 184),
	],
	[
		(354, 118),
		(366, 200),
		(384, 150),
		(398, 200),
		(416, 116),
		(428, 198),
		(438, 102),
		(448, 96),
		(442, 198),
		(456, 172),
		(470, 170),
		(472, 198),
		(486, 198),
		(494, 176),
		(498, 198),
		(510, 196),
		(518, 128),
		(522, 200),
		(536, 196),
		(546, 102),
		(558, 96),
		(552, 236),
		(542, 248),
		(536, 230),
		(566, 184),
		(576, 176),
		(580, 198),
		(594, 190),
		(606, 178),
		(596, 170),
		(586, 186),
		(598, 200),
		(614, 196),
		(626, 110),
		(636, 104),
		(630, 198),
		(644, 198),
		(662, 184),
		(650, 174),
		(638, 190),
		(652, 202),
		(670, 182),
		(678, 98),
		(680, 200),
		(694, 194),
	],
	[(110, 242), (270, 232), (470, 238), (660, 226)],
]


def smooth(points: list[tuple[int, int]], steps: int = 8) -> list[tuple[float, float]]:
	"""A Catmull-Rom curve through the control points, as the line a pen would draw."""
	padded = [points[0], *points, points[-1]]
	curve: list[tuple[float, float]] = []
	for i in range(1, len(padded) - 2):
		p0, p1, p2, p3 = padded[i - 1], padded[i], padded[i + 1], padded[i + 2]
		for step in range(steps):
			t = step / steps
			x, y = (
				0.5
				* (
					2 * p1[k]
					+ (p2[k] - p0[k]) * t
					+ (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t * t
					+ (3 * p1[k] - p0[k] - 3 * p2[k] + p3[k]) * t * t * t
				)
				for k in (0, 1)
			)
			curve.append((x, y))
	curve.append((float(points[-1][0]), float(points[-1][1])))
	return curve


def signature_png() -> str:
	"""The strokes as the PNG data URL the signature control stores, in black ink."""
	scale = 4
	image = Image.new("RGBA", (750 * scale, 292 * scale), (0, 0, 0, 0))
	draw = ImageDraw.Draw(image)
	for stroke in STROKES:
		points = [(x * scale, y * scale) for x, y in smooth(stroke)]
		draw.line(points, fill=(0, 0, 0, 255), width=4 * scale, joint="curve")
	image = image.resize((750, 292), Image.Resampling.LANCZOS)
	buffer = io.BytesIO()
	image.save(buffer, format="PNG")
	return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def render_pdf(doc: Any) -> bytes:
	"""The agreement in its print format, as a PDF.

	The signing job renders it with `frappe.attach_print`, which needs the bench's built
	assets; frappe-demo runs before `bench build`, so the demo renders the print format's
	HTML itself and converts it with the same PDF generator.
	"""
	# PRINT_HTML is this module's own constant, not user input.
	html = frappe.render_template(PRINT_HTML, {"doc": doc})  # nosemgrep: frappe-ssti
	return get_pdf(f"<style>{PRINT_CSS}</style>{html}")


def _ensure_doctype() -> None:
	if frappe.db.exists("DocType", DOCTYPE):
		return
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": DOCTYPE,
			"module": "eSign",
			"custom": 1,
			"is_submittable": 1,
			"track_changes": 1,
			"title_field": "customer",
			"fields": [
				{
					"fieldname": "customer",
					"fieldtype": "Data",
					"label": "Customer",
					"reqd": 1,
					"in_list_view": 1,
				},
				{"fieldname": "service", "fieldtype": "Data", "label": "Service", "in_list_view": 1},
				{"fieldname": "start_date", "fieldtype": "Date", "label": "Start Date"},
				{"fieldname": "monthly_fee", "fieldtype": "Currency", "label": "Monthly Fee"},
				{"fieldname": "column_break_terms", "fieldtype": "Column Break"},
				{
					"fieldname": "status",
					"fieldtype": "Select",
					"label": "Status",
					"options": "Draft\nSent\nSigned",
					"default": "Draft",
					"in_list_view": 1,
					"allow_on_submit": 1,
				},
				{"fieldname": "terms", "fieldtype": "Small Text", "label": "Terms"},
				{"fieldname": "signing_section", "fieldtype": "Section Break", "label": "Signature"},
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
				{"fieldname": "column_break_signature", "fieldtype": "Column Break"},
				{
					"fieldname": "signature",
					"fieldtype": "Signature",
					"label": "Signature",
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


def _ensure_print_format() -> None:
	if frappe.db.exists("Print Format", PRINT_FORMAT):
		return
	frappe.get_doc(
		{
			"doctype": "Print Format",
			"name": PRINT_FORMAT,
			"doc_type": DOCTYPE,
			"module": "eSign",
			"standard": "No",
			"custom_format": 1,
			"print_format_type": "Jinja",
			"html": PRINT_HTML,
			"css": PRINT_CSS,
		}
	).insert(ignore_permissions=True)


def _ensure_web_form() -> None:
	if frappe.db.exists("Web Form", WEB_FORM):
		return
	frappe.get_doc(
		{
			"doctype": "Web Form",
			"name": WEB_FORM,
			"title": "Service Agreement",
			"route": WEB_FORM,
			"doc_type": DOCTYPE,
			"module": "eSign",
			"published": 1,
			"login_required": 0,
			"allow_edit": 1,
			"esign_enabled": 1,
			"print_format": PRINT_FORMAT,
			"esign_submit_on_response": 1,
			"esign_update_field": "status",
			"esign_update_value": "Signed",
			"introduction_text": "Read the agreement, then sign it below.",
			"button_label": "Sign & Submit",
			"success_title": "Agreement signed",
			"success_message": "Thank you. A copy of the signed agreement is on its way.",
			"web_form_fields": [
				{"fieldname": "signer_name", "fieldtype": "Data", "label": "Full Name", "reqd": 1},
				{
					"fieldname": "signer_email",
					"fieldtype": "Data",
					"label": "Email",
					"options": "Email",
					"reqd": 1,
				},
				{"fieldname": "signature", "fieldtype": "Signature", "label": "Signature", "reqd": 1},
			],
		}
	).insert(ignore_permissions=True)


def _ensure_email_template() -> None:
	if frappe.db.exists("Email Template", EMAIL_TEMPLATE):
		return
	frappe.get_doc(
		{
			"doctype": "Email Template",
			"name": EMAIL_TEMPLATE,
			"subject": EMAIL_SUBJECT,
			"use_html": 1,
			"response_html": EMAIL_MESSAGE,
			"esign_request": 1,
		}
	).insert(ignore_permissions=True)


def _make_agreement(name: str, values: dict[str, Any]) -> Any:
	return frappe.get_doc({"doctype": DOCTYPE, "terms": TERMS, **values}).insert(
		ignore_permissions=True, set_name=name
	)


def _sign(name: str, today: datetime.date) -> None:
	"""Sign the agreement as the signing page does, then record it as its jobs do: the signed
	PDF on the document, and `record_signature`'s eSign Communication with the audit trail."""
	doc = frappe.get_doc(DOCTYPE, name)
	doc.update(
		{
			"signer_name": "Dana Whitfield",
			"signer_email": SIGNER_EMAIL,
			"signature": signature_png(),
			"status": "Signed",
		}
	)
	doc.submit()

	stamp = f"{today.strftime('%Y%m%d')}_104215"
	content = render_pdf(doc)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{name}_signed_{stamp}.pdf",
			"attached_to_doctype": DOCTYPE,
			"attached_to_name": name,
			"folder": "Home/Attachments",
			"is_private": True,
			"content": content,
		}
	).insert(ignore_permissions=True)

	audit: AuditData = {
		"timestamp": f"{today.isoformat()} 10:42:15",
		"ip_address": "203.0.113.42",
		"user_agent": SIGNER_AGENT,
		"signer_email": SIGNER_EMAIL,
		"signer_name": None,
		"web_form": "Service Agreement",
		"print_format": PRINT_FORMAT,
		"signed_fields": ["Signature"],
	}
	record_signature(
		doctype=DOCTYPE,
		name=name,
		file_name=str(file_doc.name),
		pdf_hash=hashlib.sha256(content).hexdigest(),
		request_data=REQUEST,
		audit_data=audit,
	)


def setup(ctx):
	"""Create the demo once; `ctx["today"]` dates the agreements and the signing."""
	today = ctx["today"]
	_ensure_doctype()
	_ensure_print_format()
	_ensure_web_form()
	_ensure_email_template()

	if not frappe.db.exists(DOCTYPE, UNSIGNED):
		_make_agreement(
			UNSIGNED,
			{
				"customer": "Northwind Bakery",
				"service": "Managed IT support, 12 workstations",
				"start_date": add_days(today, 14),
				"monthly_fee": 1450,
				"status": "Sent",
			},
		)

	if not frappe.db.exists(DOCTYPE, SIGNED):
		_make_agreement(
			SIGNED,
			{
				"customer": "Harbor Dental Group",
				"service": "Website hosting and maintenance",
				"start_date": add_days(today, 7),
				"monthly_fee": 320,
			},
		)
		_sign(SIGNED, today)
