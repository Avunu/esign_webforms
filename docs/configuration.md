---
title: Configuration
description: Every setting eSign Web Forms reads, on Web Form, Email Template and the site, the permissions it checks, and everything the app adds to a site.
nav_title: Configuration
order: 2
updated: 2026-10-26
---

eSign Web Forms has no settings page of its own. Each web form carries its own eSign settings, an email template is marked for eSign with one check box, and a few standard Frappe settings decide the rest. This page lists them all, then lists everything the app adds to your site. For the steps in order, see [Set up a signing web form](signing-form.md).

## Web Form

The eSign fields appear on the **Web Form** form. **Enable eSign** sits below **Login required**; the three sections below show only while it is ticked. Every check box is unticked by default.

| Setting                           | Section               | What it does                                                                                                                                                                                                                                                                                |
| --------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Enable eSign**                  | Top of the form       | Turns the web form's edit page (`/<ROUTE>/<DOCUMENT>/edit`) into a signing page. Saving the web form with it ticked also ticks **Allow editing after submit**, which the signing page needs.                                                                                                |
| **Submit on Response**            | eSign Settings        | Submits the document when it is signed, if its DocType is submittable and it is still a draft.                                                                                                                                                                                              |
| **Only allow Signing on Mobile**  | eSign Settings        | On large screens, shows a QR code that opens the same page instead of the form. See [Sign on a phone](signing.md#sign-on-a-phone).                                                                                                                                                          |
| **Set Property After Response**   | eSign Settings        | A field of the document to set when it is signed. Only Select, Link, Data and Text fields are offered, and saving the web form with any other type is refused.                                                                                                                              |
| **Value To Be Set**               | eSign Settings        | The value written to that field, for example `Signed`.                                                                                                                                                                                                                                      |
| **Signer Name Field**             | Signer                | The form field the signer types their name into. Its value is recorded as the signer's name. Only the web form's own Data fields are offered. Empty: only a logged-in user signing as themselves is named, after their own User.                                                            |
| **Signer Email Field**            | Signer                | The form field the signer types their email into. A valid address in it is recorded as the signer's email, and the link's `email` parameter pre-fills it. Only the web form's own Data fields are offered. Empty: the email comes from the link, or a Data field whose options are `Email`. |
| **Require Verified Email**        | Signer                | Signs only through a link bound to its recipient, and locks the email field to the bound address. See [Verified email](verified-email.md#require-verified-email).                                                                                                                           |
| **Consent Text**                  | Signer                | The text of the consent checkbox the signer must tick. Empty: "I agree to sign this document electronically."                                                                                                                                                                               |
| **Send Notification on Response** | Notification Settings | Sends a Notification after signing, with the signed PDF attached and the audit trail added to the message.                                                                                                                                                                                  |
| **Notification**                  | Notification Settings | The Notification to send. Only enabled Notifications of the web form's DocType whose **Send Alert On** is Custom are offered, and only those whose **Channel** is Email are sent.                                                                                                           |

The signing page also uses these standard Web Form fields:

| Field                                                   | Used for                                                                                                                                                                            |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Select DocType**, **Route**, **Published**            | Which documents the form signs and the address of the signing page. **Send for eSign** offers only published eSign web forms of the DocType.                                        |
| Web Form Fields                                         | The fields the signer fills in. Add the Signature field here.                                                                                                                       |
| **Print Format**                                        | The format of the preview and of the signed PDF. Shown while **Enable eSign** or **Allow print** is ticked. Empty: Frappe's standard format.                                        |
| **Introduction**                                        | Shown under the title of the signing page until the document is signed.                                                                                                             |
| **Submit button label**                                 | The label of the submit button. Empty: **Sign & Submit**.                                                                                                                           |
| **Success title**, **Success message**, **Success URL** | The card shown after signing, and the page the signer is sent to five seconds later. Empty: **Submitted** and "Thank you for signing this document."                                |
| **Allow incomplete forms**                              | Lets a signer submit without the mandatory fields, as on any web form.                                                                                                              |
| **Show attachments**                                    | Lists the document's attachments under the form. A guest sees only the public ones, as on any Frappe web form. Frappe shows this check box only while **Login required** is ticked. |

## Email Template

| Setting           | What it does                                                                                                                                                                                   |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **eSign Request** | Offers the template in the **Send for eSign** dialog, which lists only templates with it ticked. The subject and message are rendered with the document, as Frappe renders any email template. |

## Site settings

| Setting                                 | Where              | What it does                                                                                                                                                                                                                             |
| --------------------------------------- | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Document Share Key Expiry (in Days)** | System Settings    | How long a signing link works. Each link carries a Frappe Document Share Key, which expires after this many days (30 by default; Frappe uses 90 when it is empty).                                                                       |
| Outgoing **Email Account**              | Email Account      | The **From** of the **Send for eSign** dialog. It picks the default outgoing account, or the only one there is. When the document has a **Company**, it offers only that company's accounts (ERPNext adds **Company** to Email Account). |
| `encryption_key`                        | `site_config.json` | The secret that recipient-bound links are signed with, through a key derived from it. Frappe creates it on first use. Changing it invalidates every bound link sent before.                                                              |
| **Send Print as PDF**                   | Print Settings     | Must stay ticked, as it is by default. Frappe's `attach_print`, which renders the signed copy, makes an HTML file instead of a PDF when it is unticked, and the signing page then finds no signed PDF to show or download.               |
| Background workers                      | The bench          | The signed PDF, the audit record and the notification are written by jobs on the `short` queue.                                                                                                                                          |

## Permissions

The app adds no roles. It checks these permissions:

| Action                                                | Who may do it                                                                                                                                                                                                                                                                 |
| ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Send a request with **Send for eSign**                | Anyone with **Email** permission on the document, as for Frappe's own email dialog. The button shows to anyone who opens the form when the DocType has a published eSign web form, and the link preview and sending check the permission.                                     |
| Open the signing page, its preview and the signed PDF | Anyone holding the link's valid share key, signed in or not. Without a key: a signed-in user the web form admits (the document's owner, website permission, or document permissions when the web form applies them), or a user with read or print permission on the document. |
| Sign an existing document                             | Anyone holding the share key, or a signed-in user with the web form's write permission or write permission on the document. With **Require Verified Email**, only through a link bound to its recipient.                                                                      |
| Download the signed PDF without a key                 | Signed-in users only, with the permissions above. A guest always needs the key.                                                                                                                                                                                               |

The signing endpoints are rate limited per IP address: signing 10 times a minute and the preview 30 times a minute per web form, and the signed PDF download 20 times a minute.

## For developers

### Choose which documents can be signed

By default a document can be sent for eSign when its DocType has a published eSign web form. An app can decide per document with a `can_esign` hook in its `hooks.py`: a map of DocType to methods that take `doc` and return a boolean. When a DocType has such methods, every one of them must return true, and the web form check is not made.

```python
can_esign = {"Quotation": ["my_app.esign.can_esign_quotation"]}
```

### Steer the dialog

A form script can define `get_email_account(frm, fieldname)` and `get_email_recipients(frm, fieldname)` form events on its DocType. The **Send for eSign** dialog uses the Email Account and the list of addresses they return instead of its own defaults.

### Signing links in templates

`get_esign_link(doc, web_form_name, print_format_name, recipient_email)` is available in Jinja (print formats, notifications, email templates) and as a whitelisted method. See [Links in your own templates](send-for-esign.md#links-in-your-own-templates).

## What the app adds to your site

This is the complete list, so you can see what installing or migrating changes.

### Fields and property setters

| DocType        | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Web Form       | **Enable eSign** (`esign_enabled`) after **Login required**. After **Allow delete**, three sections shown only with eSign enabled: **eSign Settings** (`esign_submit_on_response`, `esign_force_mobile`, `esign_update_field`, `esign_update_value`), **Signer** (`esign_signer_name_field`, `esign_require_verified_email`, `esign_signer_email_field`, `esign_consent_text`) and **Notification Settings** (`esign_send_notification`, `esign_notification`). |
| Web Form       | A property setter on **Print Format**: shown when `esign_enabled` or `allow_print` is set.                                                                                                                                                                                                                                                                                                                                                                      |
| Email Template | **eSign Request** (`esign_request`) after **Subject**, and a **Message Template** section break.                                                                                                                                                                                                                                                                                                                                                                |
| Communication  | `eSign` added to the **Communication Type** options, through a property setter.                                                                                                                                                                                                                                                                                                                                                                                 |

### Behavior

| Where                     | Change                                                                                                                                                                          |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Web Form controller       | Extended with `extend_doctype_class`: the signing page's context, the share-key access check, and the validation of the eSign settings.                                         |
| Email Template controller | Extended with `extend_doctype_class`, to carry the **eSign Request** field.                                                                                                     |
| Web Form form             | A `doctype_js` script that fills the **Set Property After Response**, **Signer Name Field** and **Signer Email Field** options and filters **Notification**.                    |
| Every desk form           | The **Send for eSign** button, on forms where `can_esign` says yes.                                                                                                             |
| Desk controls             | The Signature control (draw, type, upload) and the upload and font controls it uses replace Frappe's, through bundles loaded on every desk page, with the four signature fonts. |
| Timeline                  | An `additional_timeline_content` hook for every DocType, which shows each eSign Communication as a card.                                                                        |
| Jinja                     | The `get_esign_link` method.                                                                                                                                                    |
| Background jobs           | `attach_print_to_document` and `record_signature`, queued on `short` after each signing. The app has no scheduled jobs.                                                         |

### Endpoints

| Method                                                                 | Who may call it                | Does                                                            |
| ---------------------------------------------------------------------- | ------------------------------ | --------------------------------------------------------------- |
| `esign_webforms.esign.can_esign`                                       | Signed-in users                | Says whether the **Send for eSign** button shows                |
| `esign_webforms.esign.send_esign_email` (POST)                         | Users with email permission    | Sends the signing request                                       |
| `esign_webforms.esign.custom.web_form.get_esign_web_forms`             | Signed-in users                | Lists a DocType's published eSign web forms                     |
| `esign_webforms.esign.custom.web_form.get_esign_link`                  | Users with email permission    | Returns a signing link, never bound to a recipient              |
| `esign_webforms.esign.custom.email_template.get_esign_email_templates` | Signed-in users                | Lists the email templates with **eSign Request** ticked         |
| `esign_webforms.esign.custom.web_form.get_print_html`                  | Guests with the key, and users | The document preview of the signing page                        |
| `esign_webforms.esign.custom.web_form.accept`                          | Guests with the key, and users | Signs: saves the form, then queues the PDF and the audit record |
| `esign_webforms.esign.custom.web_form.download_signed_pdf`             | Guests with the key, and users | Serves the latest signed PDF and writes an Access Log entry     |

The same methods under the app's old `esign.*` paths are mapped to these by `override_whitelisted_methods`.
