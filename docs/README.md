# eSign Web Forms

Electronic signatures on Frappe documents through web forms, with signed PDFs

This app turns a Frappe web form into a signing page. You send the signer a link from the document, they read it in its print format and sign it on their phone or computer without logging in, and the signed PDF comes back to the document with an audit trail of who signed and when. It works with any DocType that has a Signature field.

## What you get

- A signing page for any DocType: tick **Enable eSign** on a web form, and its edit page shows the document beside the form.
- A **Send for eSign** button on the document, with a dialog that sends the link using an eSign email template.
- A signature dialog with three ways to sign: draw, type in one of four script fonts, or upload an image.
- A signed PDF in the web form's print format, attached to the document with its SHA-256 hash.
- An audit trail in the document timeline: the signer's name and email, IP address and browser, the time, the fields signed, the consent they gave and the PDF hash. Guest signers are named by what they type into the form's signer name and email fields.
- Recipient-bound links: a link emailed to one recipient carries a signed binding of their address, so the audit trail records the email as verified via the recipient link. **Require Verified Email** signs only through such links and locks the email field to the bound address. The binding stays in the email to the recipient: the Communication on the document and the link the sender gets back leave it out.
- A required "I agree to sign this document electronically" consent checkbox, with text you can change per web form.
- Optional actions after signing: set a field, submit the document, and send a notification with the signed PDF attached.

## Setting it up

1. Give the DocType a **Signature** field.
2. Create a **Web Form** for it, tick **Enable eSign**, and add the Signature field and anything else the signer fills in, such as their name and email. In the **Signer** section, pick those fields as the **Signer Name Field** and **Signer Email Field** so the audit trail names the signer. Tick **Require Verified Email** to sign only through links emailed to each signer, and set **Consent Text** to replace the default consent.
3. Create an **Email Template** with **eSign Request** ticked.
4. Open a document and click **Send for eSign**.

The [README](https://github.com/Avunu/esign_webforms#readme) describes every setting, how the signing works and its limitations.

## Installation

```bash
bench get-app https://github.com/Avunu/esign_webforms --branch develop
bench --site <site> install-app esign_webforms
```

The signed PDFs and the timeline entries are written by background jobs, so the bench's workers must be running.

## Development

The build commands and the source layout are described in [Development](development.md).

## License

[MIT](https://github.com/Avunu/esign_webforms/blob/develop/license.txt), Copyright (c) 2025–present Avunu LLC.
