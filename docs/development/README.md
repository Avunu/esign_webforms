---
title: Develop eSign Web Forms
description: Set up the dev shell, build the bundles and fonts, run the tests and checks, and see what CI and the release flow do.
nav_title: Development
order: 9
updated: 2026-10-26
---

This page is for people changing the app. [How it works](architecture.md) explains the design behind the code. The managed files, checks and release flow shared by every Avunu app are described in the [app standards documentation](https://docs.avunu.net/frappe-nix/docs/app-standards/); this page covers what is specific to this repository.

## Set up

The repository is a frappe-nix app. Its dev shell gives you Node 24, yarn, the Python tools, the git hooks and a dev bench in `.frappe-nix/bench` with the app installed:

```bash
nix develop --no-pure-eval
```

`direnv allow` does the same each time you enter the folder. Outside Nix you need a bench with Frappe v16, Node 24 or newer and yarn, with the app in the bench's `apps/` folder.

## Commands

| Command                            | What it does                                                                                                                  |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `yarn build`                       | Builds the signature fonts with Vite, then registers them in the bench's `sites/assets/assets.json` (skipped outside a bench) |
| `bench build --app esign_webforms` | Builds the desk, control and web bundles with Frappe's esbuild, then runs `yarn build`                                        |
| `yarn typecheck`                   | Type-checks the TypeScript                                                                                                    |
| `yarn lint` / `yarn format`        | Runs oxlint and oxfmt                                                                                                         |
| `yarn lint:css`                    | Runs stylelint on the stylesheets                                                                                             |
| `yarn check`                       | All of the above checks, as the git hooks run them                                                                            |
| `frappe-test --reuse-site`         | Runs the Python tests on the dev site, with coverage                                                                          |
| `frappe-shots`                     | Rebuilds the demo site (`esign_webforms/demo.py`) and retakes the screenshots in `docs/screenshots/`                          |

`prek install` sets up the git hooks; `prek run --all-files` runs every hook (ruff, oxfmt, oxlint, stylelint, the type checks and the frappe-nix checks) on the whole tree. `nix run --no-pure-eval .#frappe-init -- --check` reports whether the managed files are in step with the standards profile.

## Where things live

```text
esign_webforms/
  hooks.py                         bundles, controller extensions, timeline hook, Jinja method, old method paths
  config/__init__.py               adds and removes the eSign Communication type on install, migrate and uninstall
  esign/__init__.py                can_esign, send_esign_email and the timeline hook
  esign/custom/web_form.py         the Web Form extension, the signing page's context, accept, get_print_html,
                                   download_signed_pdf, get_esign_link and the two background jobs
  esign/custom/email_template.py   the Email Template extension
  esign/custom/*.json              the custom fields on Web Form and Email Template
  templates/esign_webforms.html    the signing page
  public/js/esign_desk.ts          the Send for eSign button and dialog, and the timeline card's template
  public/js/web_form.js            the Web Form form script (doctype_js)
  public/js/controls/              the Signature control (draw, type, upload) and the upload and font-select controls
  public/js/web/                   the signing page's script, which extends Frappe's web form to post to accept
  public/css/                      the control and signing-page styles, and the signature fonts (built by Vite)
  demo.py                          the demo data for the screenshots
  tests/                           the Python tests
marketplace/                       the marketplace listing and the screenshot spec
vite.config.mjs                    the font bundle
scripts/vite-register.mjs          registers the Vite bundle in sites/assets/assets.json (managed by frappe-nix)
```

## How the build fits together

- **esbuild bundles.** `bench build` compiles every `*.bundle.*` file under `esign_webforms/public/`: `esign_webforms.desk.bundle.js`, `esign_webforms.control.bundle.js` and `esign_webforms.control.bundle.css`, which `hooks.py` loads on every desk page, and `esign_webforms.web.bundle.js` and `esign_webforms.web.bundle.scss`, which the signing page loads with the control styles. The entries are `.js` files that import the TypeScript modules, because only a `.js` entry gets the same key in `assets.json` from `bench build` and `bench build --using-cached`.
- **Fonts.** `vite.config.mjs` builds `public/css/esign-fonts.entry.css`, which imports the four `@fontsource` fonts, into `public/dist/css/esign-fonts.bundle.<HASH>.css` and its font files. `scripts/vite-register.mjs` then registers it in `assets.json` as `esign-fonts.bundle.css`, the name `hooks.py` and the signing page use.
- **Types.** The TypeScript is checked against [frappe-types](https://github.com/Avunu/frappe-types). What the app adds to Frappe's namespaces is declared in `types/esign_webforms.augment.d.ts`, and `types/doctypes.d.ts` holds the generated DocType types.

## Tests

The Python tests are Frappe `IntegrationTestCase`s in `esign_webforms/tests/`. `utils.py` creates a test DocType, `eSign Test Agreement`, and the helpers the tests share.

| File               | Covers                                                                                                                                                                                                                  |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_web_form.py` | The Web Form extension and its validation, share-key access, the signing page, `get_esign_link`, the preview, the signed PDF download, `accept`, the background jobs, email bindings, verified signing and signer names |
| `test_esign.py`    | The hooks, `can_esign`, `send_esign_email` and its link binding rules, the timeline card, the Email Template extension and the install hooks                                                                            |
| `test_demo.py`     | The demo data `frappe-demo` and `frappe-shots` use                                                                                                                                                                      |

Frappe only runs tests on a site that allows them. Use a development or test site, never production:

```bash
bench --site <TEST_SITE> set-config allow_tests true
bench --site <TEST_SITE> run-tests --app esign_webforms
```

In the dev shell, `frappe-test --reuse-site` runs the same tests with coverage of the app alone (the floor is `fail_under` in `pyproject.toml`). There are no JavaScript unit tests; `yarn typecheck`, `yarn lint` and `yarn format:check` are the front-end gates.

## Continuous integration and releases

These workflows are managed by frappe-nix (`frappe-init --sync` writes them) and call its shared workflows:

- `ci.yml` runs on every pull request, every push to `develop` and once a day. Its checks are `ci / lint` (the pre-commit hooks, run with prek), `ci / typecheck`, `ci / test` (the Python tests with coverage) and `ci / marketplace` (the checks of `marketplace/listing.toml`).
- `pr-policy.yml` adds `ci / pr-policy`, which checks a pull request's base, title and commits: conventional commits against `develop`.
- `release.yml` runs release-please on `develop`. Merging its release pull request tags the version, writes `CHANGELOG.md`, and moves the `version-16` branch, which `bench get-app` installs from.
- `nightly.yml` runs the integration suites each night and is never a required check. `deps.yml` relocks and syncs after a dependency bump.

`docs.yml` is this repository's own: it checks the documentation on every pull request that touches `docs/`.

## Working on these docs

The documentation is Markdown in `docs/`. It is published with the other Avunu projects at [docs.avunu.net/esign-webforms/docs/](https://docs.avunu.net/esign-webforms/docs/) by [Avunu/site-docs](https://github.com/Avunu/site-docs), which picks up the latest release of this repository. Write the files so that they read well on GitHub too: front matter, GitHub alerts and relative links. The screenshots in `docs/screenshots/` are generated by `frappe-shots`; do not edit them by hand.

To check a change as the pull request check does, clone Avunu/site-docs beside this repository and, from its folder (Node 22.19 or newer), run:

```bash
npm ci --ignore-scripts && npm run build
node build/cli.js check --only esign-webforms --source esign-webforms=../esign_webforms
```
