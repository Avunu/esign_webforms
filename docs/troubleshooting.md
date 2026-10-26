---
title: Limitations and troubleshooting
description: The known limits of eSign Web Forms, and the messages it shows to signers, senders and administrators, with their causes and fixes.
nav_title: Troubleshooting
order: 8
updated: 2026-10-26
---

## Limitations

- **Not a digital signature.** The PDF is not signed with a certificate, and it carries no visual audit page. Its SHA-256 hash and the audit data are stored in Frappe, in the eSign Communication and on the timeline card, and in the notification email when one is sent.
- **A Send for eSign email to several recipients names nobody,** unless the web form requires a verified email. One link goes to everyone in **To**, so it has no `email` parameter, and the signer's email is recorded only from the form's email field or their login. A single recipient's link is bound to their address only when nobody else (**CC**, **BCC**, **Send me a copy**) gets the message. Turn on **Require Verified Email**, send to one recipient at a time, or bind a link with `get_esign_link` and a recipient email in a template only that recipient gets.
- **A verified email proves the link, not the person.** See [What a verified email proves](verified-email.md#what-a-verified-email-proves). The name recorded is only what the signer typed, and on a web form with a **Signer Email Field** but without **Require Verified Email**, the email is what they typed, verified only when it matches the link's bound address.
- **A bound link must reach only its recipient.** A bound link in a Notification or a print format is readable by everyone who can read the document. See [Keep bound links private](verified-email.md#keep-bound-links-private).
- **Bound links do not expire on their own.** They stop working when the document's share key expires, or all at once when the site's `encryption_key` changes.
- **A form with no Signature field never shows as completed,** and a document whose signature fields are already filled opens as completed even if it was not signed through the app.
- **Only allow Signing on Mobile goes by screen width,** not by touch support: the form is hidden on large screens and shown on small ones.
- **Notifications** are sent only for an enabled Notification of the web form's DocType, with **Send Alert On** Custom and **Channel** Email. Others are skipped and an error is logged.
- **Old method paths.** Calls to the `esign.*` method paths of the app's earlier name still work through `override_whitelisted_methods`. They will be removed in a later release.

## Troubleshooting

### The signed PDF and the timeline card never appear

The document is saved with the signature, but no PDF is attached and no eSign card shows. The PDF and the card are written by background jobs on the `short` queue: check that the bench's workers are running (`bench doctor` lists them) and look in the **Error Log** and the **RQ Job** list for a failed `attach_print_to_document` or `record_signature`. A print format that cannot be rendered to PDF fails the first job.

If an attachment named `<DOCUMENT>_signed_<YYYYMMDD>_<HHMMSS>.html` appears instead of a PDF, **Send Print as PDF** is unticked in **Print Settings**. Tick it; documents signed before keep the HTML copy, and their signing page shows no signed PDF.

### The signing page refuses the link

| Message                                                                                                                                                                                | Cause and fix                                                                                                                                                                                                             |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Link Expired**: "The link has expired"                                                                                                                                               | The share key in the link is older than **Document Share Key Expiry (in Days)** in System Settings. Send a new link.                                                                                                      |
| "Invalid or expired document access key"                                                                                                                                               | The `key` parameter is not a share key of this document, often because the link was cut or edited. Send a new link.                                                                                                       |
| "No signed PDF found for this document"                                                                                                                                                | The document has no signed PDF yet: the background job has not run, or it failed. See [The signed PDF and the timeline card never appear](#the-signed-pdf-and-the-timeline-card-never-appear).                            |
| "Document access key required"                                                                                                                                                         | A guest asked for the signed PDF without a key. Use the link with its `key`.                                                                                                                                              |
| **Signing Link Required**: "This document can only be signed through the link emailed to its signer. Open the link from your email, or ask the sender to send it again."               | The web form has **Require Verified Email** and the link has no binding: it was copied from the dialog's preview or the document's Communication, or the page was opened without a link. Send it with **Send for eSign**. |
| **Invalid Signing Link**: "This signing link has been changed, or it was not sent for this document. Open the link from your email exactly as it is, or ask the sender for a new one." | The `email` or `email_sig` parameter was changed, the link belongs to another document, or the site's `encryption_key` changed since it was sent. Send a new link.                                                        |
| "You hit the rate limit because of too many requests. Please try after sometime."                                                                                                      | Frappe's rate limit: more than 10 signings, 30 previews or 20 downloads a minute from one address. Wait a minute.                                                                                                         |

### Signing is refused

| Message                                                           | Cause and fix                                                                                                                                                          |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Consent Required**: "To sign, tick the box: …"                  | The consent checkbox was not ticked. The page asks first with "Tick the consent to sign electronically before you sign."                                               |
| "Invalid or expired access key"                                   | The share key failed when the form was submitted, for example because it expired while the page was open. Send a new link.                                             |
| "You are not permitted to update this document"                   | The request had no valid share key, and the user has neither the web form's nor the document's write permission.                                                       |
| "You must login to submit this form"                              | A guest submitted a new document through a web form with **Login required**.                                                                                           |
| Frappe's "… Not allowed to change … after submission from … to …" | The document is submitted and the Signature field, or another field on the form, does not have **Allow on Submit** ticked. Tick it on each field the web form changes. |

### Send for eSign

| Message                                                                                                                                                                          | Cause and fix                                                                                                                          |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| No **Send for eSign** button                                                                                                                                                     | The DocType has no web form that is published and has **Enable eSign** ticked, or an app's `can_esign` hook said no for this document. |
| "Please save the document before sending for eSign."                                                                                                                             | Save the document first.                                                                                                               |
| "No eSign-enabled web forms found for …"                                                                                                                                         | A `can_esign` hook allowed the document, but the DocType has no published eSign web form.                                              |
| **One Link per Signer**: "… requires a verified email, so each recipient gets their own signing link. Put everyone who signs in To, and leave CC, BCC and Send me a copy empty." | The web form has **Require Verified Email**. Clear **CC**, **BCC** and **Send me a copy**.                                             |
| "… is not a valid email address"                                                                                                                                                 | With **Require Verified Email**, every address in **To** must be one valid address.                                                    |
| "Invalid eSign web form for this document type"                                                                                                                                  | The chosen web form no longer has **Enable eSign** ticked, or belongs to another DocType.                                              |
| "Failed to generate eSign link"                                                                                                                                                  | The link could not be built. The **Error Log** has an entry titled "eSign: Failed to generate link for …" with the cause.              |
| "Failed to send eSign email: …"                                                                                                                                                  | The email could not be sent. Check the **From** Email Account and the outgoing mail settings; the **Error Log** has the details.       |
| An empty **Email Template** list                                                                                                                                                 | No Email Template has **eSign Request** ticked.                                                                                        |
| An empty **From** list                                                                                                                                                           | No Email Account has outgoing email enabled, or none belongs to the document's company.                                                |

The method can also answer "Missing required parameters for eSign email", "No valid recipients provided", "Document … not found" or "Web Form … not found" when it is called with incomplete or stale arguments.

### Saving the web form is refused

| Message                                                                            | Cause and fix                                                                                                           |
| ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| "Set Property After Response can only set a Select, Link, Data, Text field, not …" | Pick a field of one of those types, or clear the setting.                                                               |
| "Signer Name Field must be one of this web form's fields, not …"                   | The field was removed from the web form. Pick another or clear the setting. The same applies to **Signer Email Field**. |
| "Signer Name Field can only be a Data field, not …"                                | The field's type changed. Pick a Data field. The same applies to **Signer Email Field**.                                |

### The notification is not sent

The signing went through but the Notification's email did not arrive. Look in the **Error Log** for one of these titles:

| Error Log title                            | Fix                                                                                            |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| "eSign: Notification doctype mismatch"     | Pick a Notification whose **Document Type** is the web form's DocType.                         |
| "eSign: Notification event not Custom"     | Set the Notification's **Send Alert On** to Custom.                                            |
| "eSign: Notification disabled"             | Tick **Enabled** on the Notification.                                                          |
| "eSign: Notification channel not Email"    | Set the Notification's **Channel** to Email.                                                   |
| "eSign: Failed to send notification for …" | Rendering or sending failed; the entry has the error. Check the subject and message templates. |

A Notification whose recipients resolve to nobody sends nothing and logs nothing.

### Set Property After Response did not change the field

If **Set Property After Response** did not change the field, the **Error Log** may have "eSign: Failed to set field …". A field that is no longer one of the allowed types is skipped silently: open the web form and save it to see the validation message.

### The signing page shows "Failed to load document preview."

The preview could not be rendered. The usual causes are an error in the print format or an expired key; open the document's print view in the desk with the same print format to see the error.
