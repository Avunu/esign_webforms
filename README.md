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

Full documentation: [docs.avunu.net/esign-webforms/docs/](https://docs.avunu.net/esign-webforms/docs/).

## Features

- **A signing page for any DocType.** Tick **Enable eSign** on a web form and its edit page shows the document in its print format beside the form, a consent checkbox and the submit button. See [docs/signing-form.md](docs/signing-form.md).
- **Send for eSign from the document.** A dialog emails the signing link with an eSign email template and records the message on the document. See [docs/send-for-esign.md](docs/send-for-esign.md).
- **Guest signing.** The link carries the document's share key, so the signer needs no account, until the key expires.
- **Draw, type or upload a signature.** The app replaces Frappe's Signature control, in the desk and on the signing page, with a drawing pad, a typed signature in one of four bundled script fonts, or an uploaded image. See [docs/signing.md](docs/signing.md).
- **Signed PDFs and an audit trail.** A background job attaches the signed PDF with its SHA-256 hash, and an eSign card in the timeline records the signer, their email, the consent they gave, their IP address and browser, and the time. See [docs/audit-trail.md](docs/audit-trail.md).
- **Recipient-bound links.** A link emailed to one recipient carries an HMAC binding of their address, so the audit trail records the email as verified. **Require Verified Email** signs only through such links. See [docs/verified-email.md](docs/verified-email.md).
- **Actions after signing.** Set a field, submit the document, and send a Notification with the signed PDF and the audit trail attached.
- **Signing on a phone.** **Only allow Signing on Mobile** shows a QR code instead of the form on large screens.
- **cloud_storage support.** With the cloud_storage app, the signed PDF is stored once and guests download it through a sharing link.

<!-- frappe-nix:begin compatibility -->

## Compatibility

| Frappe | Branch       |
| ------ | ------------ |
| v16    | `version-16` |

<!-- frappe-nix:end compatibility -->

<!-- frappe-nix:begin installation -->

## Installation

```bash
bench get-app https://github.com/Avunu/esign_webforms --branch version-16
bench --site <site> install-app esign_webforms
```

<!-- frappe-nix:end installation -->

Until the first release creates the `version-16` branch, install from `develop` instead: `bench get-app https://github.com/Avunu/esign_webforms --branch develop`.

## Configuration

1. **The DocType.** Give it a **Signature** field. To sign submitted documents, tick **Allow on Submit** on every field the web form changes.
2. **The web form.** Create a **Web Form** for the DocType, tick **Enable eSign**, add the Signature field and the signer's fields, and pick its **Print Format**. The **eSign Settings**, **Signer** and **Notification Settings** sections set what happens after signing, which fields name the signer, whether a verified email is required, the consent text and the notification.
3. **The email template.** Create an **Email Template** and tick **eSign Request**.
4. **Outgoing email and workers.** Send for eSign needs an outgoing **Email Account**, and the signed PDF is written by background jobs on the `short` queue.

Every setting is described in [docs/configuration.md](docs/configuration.md), and the steps in order in [docs/signing-form.md](docs/signing-form.md).

## How It Works

The app extends the **Web Form** and **Email Template** controllers through `extend_doctype_class` and adds their eSign fields as custom fields. A signing link is `/<web form route>/<document>/edit?key=<share key>`; the web form's `get_context` checks the key and renders the app's signing page, which loads the print preview into a shadow root. Signing posts to the app's own `accept`, which checks the key, the email binding and the consent, then saves the form's fields in one go. Background jobs render and attach the PDF, then write the eSign Communication that the timeline shows as a card and send the notification. See [docs/development/architecture.md](docs/development/architecture.md).

## Limitations

- **Not a digital signature.** The PDF is not signed with a certificate and carries no visual audit page; its hash and the audit data are stored in Frappe.
- **A verified email proves the link, not the person.** The name recorded is only what the signer typed.
- **A bound link must reach only its recipient,** and it expires only with the document's share key or the site's encryption key.
- **One link to several recipients names nobody,** unless the web form requires a verified email.

All limitations, and the messages the app shows with their fixes, are in [docs/troubleshooting.md](docs/troubleshooting.md).

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

The build commands, the tests and the source layout are described in [docs/development/README.md](docs/development/README.md).

<!-- frappe-nix:begin license -->

## License

MIT, Copyright (c) 2025–present Avunu LLC → [license.txt](license.txt)

<!-- frappe-nix:end license -->
