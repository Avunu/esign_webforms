// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import type { ShotSpec } from "./shots.d.ts";

// The demo from esign_webforms/demo.py: DEMO-AGR-001 waits for a signature, DEMO-AGR-002
// was signed through the "service-agreement" eSign web form.
const SIGNING_PAGE = "/service-agreement/DEMO-AGR-001/edit";
const UNSIGNED = "/app/service-agreement/DEMO-AGR-001";
const SIGNED = "/app/service-agreement/DEMO-AGR-002";
const WEB_FORMS = "/app/web-form";

// The signing page is ready once the agreement's preview is rendered in the shadow root and
// the web form has built its fields.
const PAGE_READY =
	"!!(window.frappe && frappe.web_form && frappe.web_form.fields_dict && frappe.web_form.fields_dict.signature" +
	" && document.getElementById('shadow-host')?.shadowRoot?.querySelector('#print-content:not(.hide) .agreement'))";
const SIGNATURE = "frappe.web_form.fields_dict.signature";

// The signature the demo's signed agreement carries (STROKES in esign_webforms/demo.py), drawn
// on the signature pad as Catmull-Rom curves through its control points, scaled to the canvas.
const STROKES = [
	[
		[148, 92],
		[140, 140],
		[130, 185],
		[122, 212],
		[104, 218],
		[94, 206],
		[112, 196],
		[166, 188],
		[206, 160],
		[212, 124],
		[184, 98],
		[136, 92],
		[90, 106],
	],
	[
		[206, 200],
		[222, 176],
		[236, 170],
		[230, 196],
		[244, 200],
		[258, 174],
		[268, 172],
		[262, 198],
		[276, 200],
		[290, 176],
		[302, 174],
		[296, 198],
		[312, 202],
		[326, 184],
	],
	[
		[354, 118],
		[366, 200],
		[384, 150],
		[398, 200],
		[416, 116],
		[428, 198],
		[438, 102],
		[448, 96],
		[442, 198],
		[456, 172],
		[470, 170],
		[472, 198],
		[486, 198],
		[494, 176],
		[498, 198],
		[510, 196],
		[518, 128],
		[522, 200],
		[536, 196],
		[546, 102],
		[558, 96],
		[552, 236],
		[542, 248],
		[536, 230],
		[566, 184],
		[576, 176],
		[580, 198],
		[594, 190],
		[606, 178],
		[596, 170],
		[586, 186],
		[598, 200],
		[614, 196],
		[626, 110],
		[636, 104],
		[630, 198],
		[644, 198],
		[662, 184],
		[650, 174],
		[638, 190],
		[652, 202],
		[670, 182],
		[678, 98],
		[680, 200],
		[694, 194],
	],
	[
		[110, 242],
		[270, 232],
		[470, 238],
		[660, 226],
	],
];
const DRAW = `(() => {
	const control = ${SIGNATURE};
	const rect = control.pad_canvas.getBoundingClientRect();
	const sx = rect.width / 750, sy = rect.height / 292;
	const smooth = (points) => {
		const p = [points[0], ...points, points[points.length - 1]];
		const out = [];
		for (let i = 1; i < p.length - 2; i++) {
			for (let s = 0; s < 8; s++) {
				const t = s / 8;
				out.push([0, 1].map((k) => 0.5 * (2 * p[i][k] + (p[i + 1][k] - p[i - 1][k]) * t
					+ (2 * p[i - 1][k] - 5 * p[i][k] + 4 * p[i + 1][k] - p[i + 2][k]) * t * t
					+ (3 * p[i][k] - p[i - 1][k] - 3 * p[i + 1][k] + p[i + 2][k]) * t * t * t)));
			}
		}
		out.push(points[points.length - 1]);
		return out;
	};
	control.signature_pad.fromData(${JSON.stringify(STROKES)}.map((points) => ({
		penColor: "black", dotSize: 0, minWidth: 1.5, maxWidth: 3, velocityFilterWeight: 0.7,
		compositeOperation: "source-over",
		points: smooth(points).map(([x, y], i) => ({ x: x * sx, y: y * sy, time: i * 16, pressure: 0.5 })),
	})));
})()`;

// Fill the form and insert a typed signature, as the signer would with the Type tab.
const FILL = [
	{ type: { selector: '[data-fieldname="signer_name"] input', text: "Ana Torres" } },
	{ type: { selector: '[data-fieldname="signer_email"] input', text: "ana.torres@example.com" } },
	{ eval: "document.fonts.load('italic 120px Pacifico')" },
	{ wait: 1000 },
	{
		eval: `(() => { const c = ${SIGNATURE}; c.show_dialog(); c.select_mode("type"); c.typed_input.value = "Ana Torres"; c.update_typed_preview(); c.handle_insert(); })()`,
	},
	{ eval: "document.activeElement && document.activeElement.blur()" },
	{ wait: 800 },
];

const DESK_READY = (name: string) => `!!(window.cur_frm && cur_frm.doc && cur_frm.doc.name === "${name}")`;

export default {
	demo: { date: "2026-01-15", seed: 1 },
	shots: [
		{
			name: "signing-page",
			// The signing page is a website page, which has no dark theme.
			themes: ["light"],
			route: SIGNING_PAGE,
			alt: "The signing page: the agreement in its print format, and the signer's name, email and typed signature in the form beside it",
			waitForFn: PAGE_READY,
			actions: [{ wait: 800 }, ...FILL],
			// The "Signature added successfully" toast would cover the submit button.
			hide: [".es-toast-container"],
			readme: "hero",
			featured: true,
		},
		{
			name: "signature-pad",
			// The signing page is a website page, which has no dark theme.
			themes: ["light"],
			route: SIGNING_PAGE,
			alt: "The signature dialog's Draw tab with a handwritten signature, and the Type and Upload tabs beside it",
			waitForFn: PAGE_READY,
			actions: [
				{ wait: 800 },
				{ eval: `${SIGNATURE}.show_dialog()` },
				{ wait: 800 },
				{ eval: DRAW },
				{ wait: 500 },
			],
			readme: "feature",
			featured: true,
		},
		{
			name: "send-for-esign",
			route: UNSIGNED,
			alt: "The Send for eSign dialog on a draft agreement, with the recipient, the eSign email template, the web form and the message filled in",
			waitForFn: `${DESK_READY("DEMO-AGR-001")} && !!cur_frm.custom_buttons["Send for eSign"]`,
			actions: [
				// The browser blocks the desk's sounds without a user gesture, which throws.
				{ eval: "frappe.utils.play_sound = () => {}" },
				{ eval: 'cur_frm.custom_buttons["Send for eSign"].trigger("click")' },
				{ waitFor: '.modal.show [data-fieldname="web_form"] select' },
				{ wait: 800 },
				{ eval: 'cur_dialog.set_value("recipients", "orders@northwind.example.com")' },
				{ eval: 'cur_dialog.set_value("email_template", "Service Agreement for Signature")' },
				{ waitFor: '.modal.show [data-fieldname="esign_link_preview"] a' },
				{ wait: 1000 },
				{ eval: "document.activeElement && document.activeElement.blur()" },
			],
			// The link carries the document's share key, which is new on every demo site.
			mask: ['.modal.show [data-fieldname="esign_link_preview"] a'],
			readme: "feature",
			featured: true,
		},
		{
			name: "audit-trail",
			route: SIGNED,
			alt: "A signed agreement's timeline: the eSign card naming the signer, with the PDF's SHA-256 hash, the signer's email, IP address, web form, signed fields and browser",
			waitForFn: `${DESK_READY("DEMO-AGR-002")} && !!document.querySelector('.timeline-message-box[data-communication-type="eSign"]')`,
			actions: [
				{
					eval: 'document.querySelector(\'.timeline-message-box[data-communication-type="eSign"]\').scrollIntoView({ block: "center" })',
				},
				{ wait: 800 },
			],
			mask: [".frappe-timestamp"],
			readme: "feature",
			featured: true,
		},
		{
			name: "signer-settings",
			// The Web Form form's code editors start ace's syntax-check workers from blob: URLs,
			// which the network wait never sees finish, so the shot opens the form from the Web
			// Form list with a stand-in Worker: the editors work without their linting.
			route: WEB_FORMS,
			alt: "The eSign web form's settings: Submit on Response, Set Property After Response, and the Signer Name Field and Signer Email Field that name the form fields the audit trail records",
			waitForFn: "!!(window.cur_list && cur_list.doctype === 'Web Form')",
			actions: [
				{
					eval: "window.Worker = class { postMessage() {} terminate() {} addEventListener() {} removeEventListener() {} }",
				},
				{ eval: 'frappe.set_route("Form", "Web Form", "service-agreement")' },
				{ waitFor: '[data-fieldname="esign_signer_name_field"] select' },
				{ wait: 800 },
				// Opens the Settings tab; the highlight it puts on the field is taken off again.
				{ eval: 'cur_frm.scroll_to_field("esign_submit_on_response", false)' },
				{ wait: 800 },
				{ eval: "document.querySelectorAll('.highlight').forEach((el) => el.classList.remove('highlight'))" },
				{ eval: "document.activeElement && document.activeElement.blur()" },
			],
			mask: [".frappe-timestamp"],
			readme: "feature",
		},
	],
} satisfies ShotSpec;
