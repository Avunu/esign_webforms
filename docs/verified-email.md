---
title: Verified email
description: How recipient-bound signing links work, what Require Verified Email changes, and what a verified email does and does not prove.
nav_title: Verified email
order: 7
updated: 2026-10-26
---

A signing link opens the document for whoever holds it. On its own it says nothing about who signed: the signer types their email, and the audit trail records what they typed. A recipient-bound link adds proof that the signer used the link emailed to one address, and the audit trail then records that address as verified.

## How a link is bound

A bound link carries two extra parameters: `email`, the recipient's address, and `email_sig`, a binding of that address to the document. The binding is an HMAC-SHA256 of the DocType, the document name and the address (trimmed and in lower case), keyed with a secret derived from the site's `encryption_key`. It cannot be moved to another document or another address, and it cannot be made without the site's key.

When the signing page or the signing endpoint gets a link with `email_sig`, it checks the binding in constant time. The share key is still checked first, and still decides whether the link opens the document at all and when it expires. The binding only vouches for the address.

A link is bound when:

- **Send for eSign** sends it to one address, with nobody in **CC**, **BCC** or **Send me a copy**.
- **Send for eSign** sends it for a web form with **Require Verified Email**: each recipient gets their own bound link.
- `get_esign_link` is called in Jinja or Python with a recipient email. See [Links in your own templates](send-for-esign.md#links-in-your-own-templates).

## What the signer sees

With a valid bound link, the form says "Signing as …, verified by your email link" and the email field is filled in with the address. On a web form without **Require Verified Email**, the signer can still change it; if they do, the audit trail records what they entered and notes "Link sent to …, verified via recipient link" with the bound address.

## Require Verified Email

Tick **Require Verified Email** in a web form's **Signer** section when every signing must come through a bound link. Then:

- The signing page refuses a link without a valid binding. A link with no binding shows **Signing Link Required**; one whose binding does not match shows **Invalid Signing Link**.
- Signing without a link is refused too: a signed-in owner opening the page, or a new document submitted through the web form.
- The email field (the **Signer Email Field**, or else a Data field whose options are `Email`) is filled from the link and read-only, and the server saves and records the bound address whatever the form submits.
- **Send for eSign** sends one email per address in **To**, each with its own link, and refuses **CC**, **BCC** and **Send me a copy**. The dialog's link preview says so, because the preview link is bound to nobody and would not open the form.

## What a verified email proves

"Email verified via recipient link" means the signer used the link that was emailed to that address and to nobody else, so they could read that mailbox, or were given the link by someone who could. It does not prove who the person is. The name recorded is only what the signer typed into the **Signer Name Field**, and the app does not check it against anything.

## Keep bound links private

- The app keeps the binding out of the Communication that **Send for eSign** records on the document and out of the link it shows the sender.
- A link that `get_esign_link` binds in Jinja is wherever the template puts it. A Notification's email is recorded as a Communication on the document, and a print format can be printed by anyone who can read the document, so a bound link in either is readable by everyone with access to the document.
- Bound links have no expiry of their own. A bound link stops working when the document's share key expires, or, for every bound link of the site at once, when the site's `encryption_key` changes.
