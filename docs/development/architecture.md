---
title: How it works
description: "The design behind eSign Web Forms: the Web Form extension, the signing page, share keys and email bindings, the signing endpoint and the background jobs."
nav_title: How it works
order: 10
updated: 2026-10-26
---

This page describes the design behind the code, for developers. For commands and the build, see [Develop eSign Web Forms](README.md).

## The pieces

| Piece              | Built with                                                                                                       | Entry point                                                                   |
| ------------------ | ---------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Web Form extension | `EsignWebForm`, composed onto Frappe's Web Form controller with `extend_doctype_class`                           | `esign_webforms/esign/custom/web_form.py`                                     |
| Signing page       | A Jinja template, and a script that subclasses Frappe's `WebForm` to post to the app's `accept`                  | `templates/esign_webforms.html`, `public/js/web/esign_web.ts`                 |
| Send for eSign     | A desk dialog on every form for which `can_esign` says yes, and `send_esign_email` on the server                 | `public/js/esign_desk.ts`, `esign_webforms/esign/__init__.py`                 |
| Signature control  | A replacement for Frappe's `ControlSignature`, built with `signature_pad` and `hast-util-to-dom`                 | `public/js/controls/signature.ts`                                             |
| Audit trail        | Two background jobs, an eSign Communication, and an `additional_timeline_content` hook with a microtemplate card | `web_form.py`, `esign/__init__.py`, `public/js/templates/esign_timeline.html` |

`EsignWebForm` subclasses the stock `WebForm` only. Frappe v16 composes the final controller from the stock class and every installed app's extension (the payments app registers one too), so subclassing another extension would break whenever that app is installed after this one. `EsignEmailTemplate` does the same for Email Template.

## The signing page

A signing link is `/<ROUTE>/<DOCUMENT>/edit?key=<SHARE_KEY>`, with optional `format` (print format), `email` and `email_sig` parameters. `build_esign_link` makes it, with a share key from Frappe's `Document.get_document_share_key`.

`EsignWebForm.get_context` takes over when the web form has **Enable eSign** and the request names a document. It loads the document without a permission check, then calls `validate_esign_access`: a `key` is checked as a Document Share Key of that document (Frappe's `validate_key`, which raises `LinkExpired` for an expired key); without one, a signed-in user the web form's own rules admit is let in (owner, website permission, or document permissions when the web form applies them), and anyone else needs Frappe's print permission. Only after that is the document marked `ignore_permissions`, because Frappe's website permission check passes any document that already carries the flag.

It then resolves the email binding (below), builds the web form context with `login_required` off and editing on, makes the email field read-only when a verified email is required, pre-fills the email field from the link, and swaps the template for `esign_webforms.html` with the app's bundles. `is_completed` is true when every Signature field of the web form has a value other than Frappe's placeholder image; the page then shows **Document Signed** and the latest signed PDF instead of the form.

The preview is not part of the page. `esign_webform_script.ts` asks `get_print_html` for the print format's HTML and styles and renders them into a declarative shadow root, so the print format's styles do not touch the page, and scales it to the pane's width.

`has_web_form_permission` is overridden so that a share key admits a guest. It admits reads anywhere, but a write only when `accept` sets `frappe.flags.esign_key_write`: Frappe's own web form `accept`, which guests may also call, asks the same question before saving, and would otherwise skip the consent, the binding and the locked email field.

## Email bindings

`email_sig` is `HMAC-SHA256(k, doctype ‖ name ‖ email)`, with the parts joined by a NUL byte and the email trimmed and lower-cased. `k` is `HMAC-SHA256(encryption_key, "esign_webforms:recipient-email-binding")`, so it is per site and never the encryption key itself. `get_bound_email` returns the address only when the binding matches, compared with `hmac.compare_digest`. `_require_bound_email` raises **Signing Link Required** or **Invalid Signing Link** when the web form has **Require Verified Email** and there is no valid binding.

`send_esign_email` decides which links are bound: one bound link per recipient for a web form that requires a verified email, otherwise one link to everyone, carrying the address when there is one recipient and bound only when nobody else gets the message. `strip_email_binding` removes `email_sig` from the Communication it records and from the link it returns. `get_esign_link` binds only when it is given a `Document` (from Jinja or Python), never when it is called over HTTP with a JSON reference.

## Signing

The signing page posts to `esign_webforms.esign.custom.web_form.accept` rather than Frappe's. It reads `key`, `email`, `email_sig` and `format` from the `Referer`, since the form posts from the signing page's address, and then, in order:

1. Checks the share key with Frappe's print permission, and that the request may write the document: the share key (through `has_web_form_permission` with `esign_key_write`), the web form's write permission, or write permission on the DocType.
2. Checks the email binding, refusing a missing or invalid one when the web form requires a verified email.
3. Checks `esign_consent`, refusing to sign without it, and stamps the consent time.
4. Writes the web form's fields, replaces the email field with the bound address when a verified email is required, applies **Set Property After Response**, sets `docstatus` to 1 for **Submit on Response**, and saves once with `ignore_permissions`. `ignore_validate_constants` lets a signature land in a field that is set only once.
5. Collects the audit data (`_collect_audit_data`) and queues `attach_print_to_document` on `short`, after commit, with a job id per document and `deduplicate`, so a second signing while the first job is still queued does not queue another.

`attach_print_to_document` renders the PDF with Frappe's `attach_print` in the link's print format, hashes it, and inserts a private File on the document (setting `content_hash` explicitly, and the `s3_key` under cloud_storage). It then queues `record_signature`, again after commit: the File has to be committed before the Communication updates the document's `_comments`, because doing both in one transaction deadlocked under cloud_storage.

`record_signature` inserts the eSign Communication with the audit data as JSON, attaches a copy of the PDF to it (or, under cloud_storage, adds a `file_association` row to the same File), and sends the web form's Notification through `_send_esign_notification`. That function renders the Notification as Frappe does, attaches the signed PDF instead of a fresh print, appends the escaped audit table, records the email as a Communication and applies the Notification's set-property-after-alert.

Both jobs run under `_job_request`, which gives them the signing request's host, scheme and headers through `frappe.local.request`, so the PDF renderer and URL helpers work in a worker.

## The audit data

`AuditData` holds `timestamp`, `ip_address`, `user_agent`, `signer_email`, `signer_name`, `signer_email_verified`, `verified_via`, `verified_email`, `consent_text`, `consent_timestamp`, `web_form`, `print_format` and `signed_fields`; `record_signature` adds `pdf_hash` and `file_name`.

The signer's email is the bound address when the web form requires a verified email. Otherwise it is the valid address in the **Signer Email Field** when one is set; failing that setting, the bound address or the `email` parameter, then a Data field with options `Email`; and finally the signed-in user. It is verified when it equals the bound address. The name is only what the signer typed into the **Signer Name Field**; without that field, a signed-in user whose signer email is their own login is named after their User. A User is never looked up from an address the signer may have typed.

The IP address is read from `CF-Connecting-IP`, `X-Real-IP` or the first entry of `X-Forwarded-For`, then the connection.

`get_timeline_content` turns each eSign Communication into a card. Frappe's microtemplates print `{{ }}` unescaped, and the signer controls several values (user agent, email, form fields), so every value is HTML-escaped on the server first.

## Downloads

`download_signed_pdf` needs the share key from a guest. It serves the PDF attached to the latest eSign Communication, or else the latest `*_signed_*.pdf` attached to the document, and writes an Access Log entry. A cloud_storage file is served by redirecting to cloud_storage's `/api/method/share` with a sharing link the app sets on the File, because cloud_storage's `retrieve` checks permissions a guest with a key does not have.

## Install hooks

`config/__init__.py` adds `eSign` to Communication's `communication_type` options through a property setter on `after_install` and `after_migrate`, and removes it on `after_uninstall`. The custom fields are data in `esign/custom/*.json` with `sync_on_migrate`; their effect is listed in [Configuration](../configuration.md#what-the-app-adds-to-your-site).
