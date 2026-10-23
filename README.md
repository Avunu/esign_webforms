<!-- Copyright (c) 2026, Avunu LLC and contributors
For license information, please see license.txt-->

<!-- frappe-nix:begin header -->

<div align="center">

<img src="esign_webforms/public/images/esign_webforms-logo.svg" width="80" alt="">

# eSign Web Forms

Electronic signatures on Frappe documents through web forms, with signed PDFs

[![CI](https://github.com/Avunu/esign_webforms/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/Avunu/esign_webforms/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/Avunu/esign_webforms)](https://github.com/Avunu/esign_webforms/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](license.txt)
[![Frappe v16](https://img.shields.io/badge/Frappe-v16-blue)](https://github.com/frappe/frappe/tree/version-16)

<picture>
  <img src="docs/screenshots/signing-page-light.webp" alt="The signing page: the agreement in its print format, and the signer's name, email, typed signature and the ticked consent to sign electronically in the form beside it">
</picture>

</div>

<!-- frappe-nix:end header -->

## Overview

Quotes, orders, waivers and agreements often need a customer's signature before work can start. eSign Web Forms collects that signature inside Frappe instead of printing, scanning or paying for a separate e-signature service. You send the signer a link from the document, they read the document and sign it on their phone or computer without logging in, and the signed PDF comes back to the document with a record of who signed and when.

It works with any DocType, standard or custom, that has a Signature field and a web form. The app adds eSign settings to **Web Form** and **Email Template**; it has no DocTypes of its own.

## Features

- **A signing page for any DocType.** Turn on **Enable eSign** for a web form and its edit page becomes a signing page: the document in its print format on one side, the web form's fields and its submit button on the other (the web form's **Button Label** names it, for example "Sign & Submit"). Signers can also download the unsigned PDF.
- **Guest signing through share links.** The link carries the document's share key, so the signer needs no account. Frappe's **Document Share Key Expiry** system setting decides how long a key is valid. The signing endpoints are rate limited.
- **Draw, type or upload a signature.** The app replaces Frappe's Signature control, in the desk and on the signing page, with a dialog that offers a drawing pad, a typed signature in one of four bundled script fonts (Pacifico, Dancing Script, Great Vibes, Caveat), or an uploaded image.
- **Send for eSign from the document.** Forms whose DocType has a published eSign web form get a **Send for eSign** button. Its dialog picks the sending email account, recipients, CC and BCC, an eSign email template, the web form and the print format, and previews the link. If the message does not already contain the link, a **Sign Document** button is added to the email. When **To** holds a single address, the link carries it as its `email` parameter, bound to the document when nobody else gets the message. For a web form that requires a verified email, each recipient in **To** gets their own email with their own bound link.
- **Recipient-bound links.** A link sent to one recipient carries an `email_sig` parameter, an HMAC-SHA256 of the document and the recipient's address keyed with a secret derived from the site's encryption key. The signing page and the signing endpoint check it in constant time, so the address in the link cannot be changed or moved to another document, and the audit trail records it as "Email verified via recipient link".
- **Require Verified Email.** A web form can sign only through such a bound link: the page refuses a link without a valid binding, the email field is filled from the link and read-only, and the server records the bound address whatever the form submits.
- **Consent to sign electronically.** The signing page has a required "I agree to sign this document electronically" checkbox, with text a web form can replace. The server refuses to sign without it, and the consent text and the time it was given are recorded in the audit trail, on the timeline card and in the notification email.
- **Signed PDFs.** After signing, a background job renders the document in the web form's print format, attaches the PDF to the document as a private file and records its SHA-256 hash.
- **Audit trail in the timeline.** Each signing creates an eSign Communication with the signer's name and email, whether the email was verified, the consent they gave, IP address and browser, the time, the web form, the print format, the fields signed and the PDF hash. It shows as a card in the document timeline, "Document signed by" the signer, with links to open and download the signed PDF.
- **Guest signers by name.** A web form can name the fields its signer types their name and email into, and the audit trail records what the guest entered there, so a signer without an account is named in the timeline card and the notification email, not only by email. The name recorded is only the one the signer typed: it is never looked up from a User with a matching email.
- **Actions after signing.** A web form can set a field to a value (for example, **Status** to "Signed"), submit the document, and send a Notification with the signed PDF attached and the audit trail added to the email.
- **Completed documents.** Once every signature field on the form is filled, the signing page shows a **Document Signed** card instead of the form, with the signed PDF and a download button once the PDF exists.
- **Signing on a phone.** **Only allow Signing on Mobile** hides the form on large screens and shows a QR code that opens the same page on a phone.
- **cloud_storage support.** With the cloud_storage app, the signed PDF is linked to the eSign record instead of copied, and guest downloads go through a sharing link.

<!-- frappe-nix:begin compatibility -->

## Compatibility

| Frappe | Branch       |
| ------ | ------------ |
| v16    | `version-16` |

<!-- frappe-nix:end compatibility -->

<!-- frappe-nix:begin installation -->

## Installation

On Frappe Cloud, install eSign Web Forms from the [Frappe marketplace](https://cloud.frappe.io/marketplace/apps/esign_webforms).

On a bench of your own:

```bash
bench get-app https://github.com/Avunu/esign_webforms --branch version-16
bench --site <site> install-app esign_webforms
```

<!-- frappe-nix:end installation -->

Until the first release creates the `version-16` branch, install from `develop` instead: `bench get-app https://github.com/Avunu/esign_webforms --branch develop`.

## Configuration

1. **The DocType.** Give the DocType you want signed a **Signature** field. To sign documents that are already submitted, tick **Allow on Submit** on the Signature field and on every other field the web form changes.
2. **The web form.** Create a **Web Form** for the DocType and tick **Enable eSign**. Add the Signature field, and any fields the signer should fill in, such as their name and email (Data fields; give the email field the options `Email`). Then set:
   - **Print Format**, the web form's own field, which shows once eSign is enabled: the format of the preview and of the signed PDF.
   - In the **eSign Settings** section:
     - **Submit on Response**: submit the document when it is signed (submittable DocTypes only).
     - **Set Property After Response** and **Value To Be Set**: set a Select, Link, Data or Text field to a value when the document is signed. Only those fields are offered, and saving the web form with any other field is refused.
     - **Only allow Signing on Mobile**: show a QR code instead of the form on large screens.
   - In the **Signer** section, which names the signer in the audit trail:
     - **Signer Name Field**: the form field the signer types their name into. Its value is recorded as the signer's name.
     - **Signer Email Field**: the form field the signer types their email into. A valid address in it is recorded as the signer's email, and the link's `email` parameter pre-fills it.
     - **Require Verified Email**: sign only through a link bound to its recipient (see How It Works). A link without a valid binding is refused with a message asking the signer to open the link from their email, the email field (the Signer Email Field, or else a Data field whose options are `Email`) is filled from the link and read-only, and the server records the bound address and ignores any other the form submits. Signing without a link (a logged-in owner, a new document from the web form) is refused too. Send for eSign then sends one email per recipient in **To**, each with their own link, and refuses CC, BCC and **Send me a copy**, which would hand someone else a recipient's link.
     - **Consent Text**: the text of the consent checkbox the signer must tick. Left empty, it is "I agree to sign this document electronically."

     The Signer Name and Signer Email Fields offer only the web form's own Data fields, and saving the web form with any other field is refused. Make the fields mandatory on the web form if every signer must give them. When they are not set, the signer's email comes from the link's `email` parameter or a Data field whose options are `Email`. Without a Signer Name Field, only a logged-in user signing as themselves is named, after their own User; a guest is not named.

   - In the **Notification Settings** section, **Send Notification on Response** and **Notification**: send an enabled Notification of this DocType whose event is **Custom** and whose channel is **Email**, with the signed PDF attached.

   Enabling eSign also turns on **Allow Editing After Submit** for the web form, which the signing page needs.

3. **The email template.** Create an **Email Template** and tick **eSign Request** so the Send for eSign dialog offers it. Its subject and message are rendered with the document, as Frappe's email templates are.
4. **Outgoing email.** The Send for eSign dialog sends through an outgoing **Email Account**. It picks the default outgoing account, or the only one there is. When the document has a **Company**, it offers only that company's accounts (ERPNext adds the Company field to Email Account).

The signed PDF and the timeline entry are written by background jobs on the `short` queue, so the bench's workers must be running.

### For developers

- **Choosing which documents can be signed.** By default a document can be sent for eSign when its DocType has a published eSign web form. An app can decide per document with a `can_esign` hook, a map of DocType to methods that take `doc` and return a boolean:

  ```python
  can_esign = {"Quotation": ["my_app.esign.can_esign_quotation"]}
  ```

- **Steering the dialog.** A form script can define `get_email_account(frm, fieldname)` and `get_email_recipients(frm, fieldname)` form events. The dialog uses the account and the recipient list they return instead of its own defaults.
- **Links in templates.** `get_esign_link(doc, web_form_name, print_format_name, recipient_email)` is available in Jinja (print formats, notifications, email templates) and as a whitelisted method (which needs email permission on the document). With `recipient_email`, the link carries the address and its `email_sig` binding: the signing page pre-fills the form's email field with it and the audit trail records it as verified when the signer signs with it. Send such a link to that recipient only, since whoever holds it signs as them.

## How It Works

- The app extends the **Web Form** and **Email Template** controllers through `extend_doctype_class` and adds their eSign fields as custom fields. `after_install` and `after_migrate` add `eSign` as a Communication type.
- A signing link is `/<web form route>/<document>/edit?key=<share key>`, with optional `format` (print format), `email` and `email_sig` parameters. The web form's `get_context` checks the key, or without one whether the logged-in user may open the document through the web form or print it, and renders the app's signing page. The page loads the document preview from `get_print_html` into a shadow root, so the print format's styles do not touch the page.
- `email_sig` binds `email` to the document: it is `HMAC-SHA256(k, doctype ‖ document name ‖ email)`, with the email trimmed and lower-cased, and `k` derived from the site's `encryption_key` (`HMAC-SHA256(encryption_key, "esign_webforms:recipient-email-binding")`), so it is per site and never the encryption key itself. The server compares it with `hmac.compare_digest`. The share key is still checked first and still decides whether the link opens the document and when it expires; the binding only vouches for the address. Rotating the site's encryption key invalidates the bindings of links sent before.
- Signing posts the form to the app's own `accept` endpoint rather than Frappe's. It checks the share key or the user's permission, then the email binding (refusing a missing or invalid one when the web form requires a verified email), then the consent (`esign_consent`, refused when not given), writes the form's fields (with the bound address in the email field when a verified email is required), applies **Set Property After Response** and **Submit on Response**, and saves the document in one go.
- After the save commits, `attach_print_to_document` renders and attaches the PDF. It then queues `record_signature`, which creates the eSign Communication with the audit data as JSON, attaches a copy of the PDF to it (or, with cloud_storage, an association to the same file), and sends the configured Notification. The `additional_timeline_content` hook turns each eSign Communication into the timeline card.
- The signer's email is the bound address when the web form requires a verified email. Otherwise it comes from the web form's **Signer Email Field** when one is set (the link's `email` parameter only pre-fills it and is not recorded on its own), otherwise from the link's `email` parameter, then from a Data field with options `Email` on the form; failing those, from the logged-in user. It is recorded as verified (`signer_email_verified: true`, `verified_via: "recipient link"`) when it is the address the link was bound to; the bound address is recorded as `verified_email` whenever the link carried a valid binding, so a signer who typed another address shows as "Link sent to …". Their name is what they typed into the **Signer Name Field**; without that field, a logged-in user whose email is their own login is named after their own User, and anyone else is not named. The audit data also holds `consent_text` and `consent_timestamp`. All of it is recorded in the eSign Communication (the email and name as its sender and sender name too), shown on the timeline card and added to the notification email. The IP address is read from `CF-Connecting-IP`, `X-Real-IP` or `X-Forwarded-For`, then the connection.
- `download_signed_pdf` serves the latest signed PDF to a guest with the share key, and logs the download in the Access Log.

## Limitations

- **Not a digital signature.** The PDF is not signed with a certificate, and it carries no visual audit page. Its SHA-256 hash and the audit data are stored in Frappe, in the eSign Communication and the timeline, and in the notification email when one is sent.
- **A Send for eSign email to several recipients has no `email` parameter,** unless the web form requires a verified email. One link goes to everyone in **To**, so it names nobody, and the signer's email is only recorded when the form has an email field or the signer is logged in. A single recipient's link is bound to their address only when nobody else (CC, BCC, **Send me a copy**) gets the message. Turn on **Require Verified Email**, send to one recipient at a time, or use `get_esign_link` with `recipient_email` (for example in a Notification) to bind it.
- **A verified email proves the link, not the person.** "Email verified via recipient link" means the signer used the link that was emailed to that address and to nobody else, so they could read that mailbox, or were given the link by someone who could. The app does not check the name the signer types against anything: the name recorded is only what they typed, and without **Require Verified Email** the email is what they typed unless it matches the link's bound address. The share key in the link is still what limits who can open the document.
- **Bound links do not expire on their own.** The binding has no date of its own: a bound link stops working when the document's share key expires (Frappe's **Document Share Key Expiry**), or for every bound link of the site when its encryption key changes.
- **A form with no Signature field never shows as completed,** and a document whose signature fields are already filled opens as completed even if it was not signed through the app.
- **Only allow Signing on Mobile** goes by screen width, not by touch support: the form is hidden on large screens and shown on small ones.
- **Notifications** are sent only for an enabled Notification of the web form's DocType, with the **Custom** event and the **Email** channel. Others are skipped and an error is logged.
- **Old method paths.** Calls to the `esign.*` method paths of the app's earlier name still work through `override_whitelisted_methods`. They will be removed in a later release.

<!-- frappe-nix:begin support -->

## Support

- Bug reports and questions: [GitHub issues](https://github.com/Avunu/esign_webforms/issues)
- E-mail: <mail@avu.nu>

<!-- frappe-nix:end support -->

<!-- frappe-nix:begin development -->

## Development

```bash
nix develop        # or: direnv allow
prek install       # the git hooks CI runs
frappe-test        # the tests, the way CI runs them
```

The managed files, checks and release flow are described in the [app standards documentation](https://docs.avunu.net/frappe-nix/docs/app-standards/).

<!-- frappe-nix:end development -->

The build commands and the source layout are described in [docs/development.md](docs/development.md).

<!-- frappe-nix:begin license -->

## License

MIT, Copyright (c) 2025–present Avunu LLC → [license.txt](license.txt)

<!-- frappe-nix:end license -->
