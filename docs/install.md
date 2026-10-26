---
title: Install and upgrade
description: Install eSign Web Forms on a Frappe v16 bench, see what the install adds to a site, and upgrade or remove the app.
nav_title: Install
order: 1
updated: 2026-10-26
---

eSign Web Forms installs like any Frappe app. It adds fields to two standard DocTypes and one option to Communication, and creates no DocTypes or records of its own.

## Before you start

- A bench with Frappe v16 and a System Manager login on the site.
- Node 24 or newer and yarn on the machine that builds the app. `bench build` runs the app's `yarn build`, which bundles the signature fonts.
- Background workers running on the bench (`bench start` in development, the `worker` processes in production). Without them nothing is signed: the PDF and the audit record are written by jobs on the `short` queue.
- Outgoing email set up on the site, if staff will send signing requests from the desk.

## Install

Run these from the bench directory. `<SITE_NAME>` is your site, for example `site1.example.com`.

```bash
bench get-app https://github.com/Avunu/esign_webforms --branch version-16
bench --site <SITE_NAME> install-app esign_webforms
```

The `version-16` branch is created by the first release. Until then, get the app from `develop`:

```bash
bench get-app https://github.com/Avunu/esign_webforms --branch develop
```

`bench get-app` builds the app's assets. If you pull new code by hand, run `bench build --app esign_webforms` afterwards.

## What installing sets up

| Change                        | Where                                         | Detail                                                                                                                                                                        |
| ----------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| eSign fields                  | Web Form                                      | **Enable eSign**, and the **eSign Settings**, **Signer** and **Notification Settings** sections. See [Configuration](configuration.md#web-form).                              |
| Print Format shown with eSign | Web Form                                      | A property setter makes **Print Format** show when **Enable eSign** or **Allow print** is ticked; Frappe shows it only with **Allow print**.                                  |
| **eSign Request**             | Email Template                                | A check box, and a **Message Template** section break below it.                                                                                                               |
| `eSign` Communication type    | Communication, **Communication Type** options | Added by `after_install`, and again by `after_migrate` if it is missing, through a property setter on the field's options. The audit records are Communications of this type. |
| Signature control             | Desk and signing page                         | The app's bundles replace Frappe's Signature control everywhere in the desk, and on eSign signing pages.                                                                      |

The fields and the property setter are customizations of the `eSign` module with `sync_on_migrate` set, so each `bench migrate` keeps them in step with the app. The app has no patches and no scheduled jobs.

## Upgrade

Update the app the way you update any Frappe app: `bench update`, or pull the new code in `apps/esign_webforms` and then run these from the bench directory.

```bash
bench build --app esign_webforms
bench --site <SITE_NAME> migrate
```

`bench migrate` re-syncs the custom fields and adds the `eSign` Communication type if it is missing. No release so far has shipped a patch that changes data.

> [!NOTE]
> The app was once called `esign`. Calls to the old method paths, such as `esign.esign.custom.web_form.accept`, still work through `override_whitelisted_methods` in `hooks.py`, for bookmarks, cached pages and webhooks. They will be removed in a later release.

## Uninstall

```bash
bench --site <SITE_NAME> uninstall-app esign_webforms
```

Frappe deletes the records that belong to the app's `eSign` module, which removes the custom fields on Web Form and Email Template and the Print Format property setter. The app's `after_uninstall` then removes `eSign` from the Communication Type options.

What stays behind:

- The signed PDFs, attached to the documents as private files, and their copies on the eSign Communications.
- The eSign Communications themselves. They stay on the documents, but without the app the timeline no longer shows them as eSign cards.
- The Document Share Keys that signing links created, until they expire.
- The web forms. Without the app, a web form that had **Enable eSign** is an ordinary web form again.
