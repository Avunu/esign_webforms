<!-- Copyright (c) 2026, Avunu LLC and contributors
For license information, please see license.txt-->

# Webform eSignatures

Collect Electronic Signatures on Frappe Documents via Web Forms.

## Features

### 🖊️ Electronic Signatures

- Capture legally-binding electronic signatures on any Frappe DocType
- Support for multiple signature fields per document
- Touch-optimized signature pad for mobile devices

### 🔗 Secure Document Sharing

- Share documents for signing via secure, expiring links
- Guest users can sign without logging in using document share keys
- Rate-limited endpoints to prevent abuse

### 📄 Signed PDF Generation

- Automatically generates and attaches signed PDFs to documents
- SHA-256 hash verification for document integrity
- Download signed documents directly from the signing page or document timeline

### 📋 Comprehensive Audit Trail

- Full audit trail recorded for each signature event
- Captures signer name, email, IP address, and user agent
- Records timestamp and which fields were signed
- Displays signature history in the document timeline

### ⚙️ Workflow Automation

- Optionally update a field value when document is signed (e.g., set status to "Signed")
- Optionally submit the document automatically after signing
- Background PDF generation for faster response times

### 📱 Mobile-First Design

- Responsive layout works on desktop and mobile
- Optional "Force Mobile" mode with QR code for touch screen signing
- Clean, distraction-free signing experience

## Usage

1. Create a Web Form for your DocType
2. Enable "eSign Enabled" in the Web Form settings
3. Add Signature field(s) to the Web Form
4. Optionally configure:
   - **Print Format** - The format used for the signed PDF
   - **Update Field / Value** - Automatically set a field when signed
   - **Submit on Response** - Submit the document after signing
   - **Force Mobile** - Require touch screen for signing
5. Generate a document share link and send to the signer

## Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app Avunu/esign_webforms
bench install-app esign_webforms
```

## Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/esign_webforms
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

## License

MIT
