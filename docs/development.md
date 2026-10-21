# Development

Requires Node 24+ and yarn. `nix develop` (or direnv) gives you both, plus the git hooks and a dev bench.

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

`prek install` sets up the git hooks; `prek run --all-files` runs every hook (ruff, oxfmt, oxlint, stylelint, the type checks and the frappe-nix checks) on the whole tree.

## Where things live

- `esign_webforms/esign/__init__.py`: `can_esign`, `send_esign_email` and the timeline hook.
- `esign_webforms/esign/custom/web_form.py`: the Web Form extension, the signing page's context, `accept`, `get_print_html`, `download_signed_pdf`, `get_esign_link` and the two background jobs that write the signed PDF and the audit record.
- `esign_webforms/esign/custom/email_template.py`: the Email Template extension.
- `esign_webforms/esign/custom/*.json`: the custom fields on Web Form and Email Template.
- `esign_webforms/config/__init__.py`: adds and removes the `eSign` Communication type on install, migrate and uninstall.
- `esign_webforms/templates/esign_webforms.html`: the signing page.
- `esign_webforms/public/js/esign_desk.ts`: the desk's Send for eSign button and dialog, and the timeline card's template.
- `esign_webforms/public/js/controls/`: the Signature control (draw, type, upload), and the upload and font-select controls it is built from.
- `esign_webforms/public/js/web/`: the signing page's script, which extends Frappe's web form to post to the app's `accept`.
- `esign_webforms/public/css/`: the control and signing-page styles, and the bundled signature fonts (`esign-fonts.entry.css`, built by Vite).
- `esign_webforms/demo.py`: the demo data for the screenshots.
- `marketplace/`: the marketplace listing and the screenshot spec.
