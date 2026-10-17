// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import SignaturePad from "signature_pad";
import { createIconHast, toDom } from "./utils";

/**
 * @fileoverview Signature control for Frappe Framework
 * @description A modern, self-contained signature control using HAST for DOM creation,
 * Popover API for dialogs, and CSS Anchor Positioning. Supports draw, type, and upload
 * signature methods.
 *
 * Minimal dependency on Frappe - only extends the base control class pattern.
 *
 * Uses custom `toDom()` wrapper with string refs for element binding:
 * - String ref: `ref: "myElement"` → assigns to `this.myElement`
 * - Callback ref: `data: { constructor: (el) => this.arr.push(el) }` → for dynamic refs
 * - Events: `data: { onclick: () => ... }` → assigned directly to element
 *
 * Fonts are bundled via @fontsource and imported in the controls index.js entry point.
 *
 * @requires signature_pad - For canvas-based signature drawing
 * @requires hast-util-to-dom - For efficient DOM structure creation
 *
 * @author Avunu LLC
 */

/**
 * Bundled signature fonts from @fontsource - always available
 * @type {Array<{value: string, label: string, fontFamily: string}>}
 */
const SIGNATURE_FONTS = [
	{
		value: "Pacifico",
		label: "Pacifico",
		fontFamily: "Pacifico, cursive",
	},
	{
		value: "Dancing Script",
		label: "Dancing Script",
		fontFamily: '"Dancing Script", cursive',
	},
	{
		value: "Great Vibes",
		label: "Great Vibes",
		fontFamily: '"Great Vibes", cursive',
	},
	{
		value: "Caveat",
		label: "Caveat",
		fontFamily: "Caveat, cursive",
	},
];

/**
 * Unique ID counter for popover associations
 */
let signatureCounter = 0;

/**
 * @class ControlSignature
 * @extends frappe.ui.form.ControlData
 * @description A signature field control with draw, type, and upload modes.
 * Uses modern web APIs (Popover, CSS Anchor Positioning) and HAST for DOM.
 */
export class ControlSignature extends frappe.ui.form.ControlData {
	/**
	 * Gets the term to use for "signature" from df.options.
	 * Defaults to "Signature" if not specified.
	 * @returns {string}
	 */
	get_signature_term() {
		return this.df.options?.trim() || "Signature";
	}

	make_input() {
		if (this.has_input) return;

		this._id = ++signatureCounter;
		this._current_mode = "draw";
		this._font_options = [];
		this._selected_font = null;

		// Build the display area and popover dialog
		this.build_display_area();
		this.build_dialog_popover();

		// Set references for base class compatibility
		this.$input = $(this.display_canvas);
		this.input = this.display_canvas;
		this.has_input = true;
	}

	/**
	 * Builds the signature display area with canvas and overlay
	 */
	build_display_area() {
		const term = this.get_signature_term().toLowerCase();
		const addText = __("Add your {0}", [term]);
		const replaceText = __("Replace {0}", [term]);
		const addIcon = createIconHast("es-line-add", "md");
		const replaceIcon = createIconHast("es-line-edit", "md");

		const displayStructure = {
			type: "element",
			tagName: "div",
			properties: { className: ["signature-display"] },
			ref: "display_wrapper",
			data: {
				onclick: () => {
					if (this.get_status() === "Write") {
						this.show_dialog();
					}
				},
			},
			children: [
				{
					type: "element",
					tagName: "canvas",
					properties: {
						width: 750,
						height: 292,
						className: ["signature-display-canvas"],
					},
					ref: "display_canvas",
					children: [],
				},
				{
					type: "element",
					tagName: "div",
					properties: { className: ["signature-overlay"] },
					ref: "display_overlay",
					children: [
						{
							type: "element",
							tagName: "div",
							properties: {
								className: ["signature-overlay-content", "add-signature"],
							},
							children: [
								{
									...addIcon,
								},
								{
									type: "element",
									tagName: "div",
									properties: {
										className: ["signature-overlay-text"],
									},
									children: [{ type: "text", value: addText }],
								},
							],
						},
						{
							type: "element",
							tagName: "div",
							properties: {
								className: ["signature-overlay-content", "replace-signature"],
							},
							children: [
								{
									...replaceIcon,
								},
								{
									type: "element",
									tagName: "div",
									properties: {
										className: ["signature-overlay-text"],
									},
									children: [{ type: "text", value: replaceText }],
								},
							],
						},
					],
				},
			],
		};

		const wrapper = toDom(displayStructure, this);
		this.input_area.appendChild(wrapper);
	}

	/**
	 * Builds the signature dialog as a popover element
	 */
	build_dialog_popover() {
		const term = this.get_signature_term();
		const termLower = term.toLowerCase();
		const popoverId = `signature-dialog-${this._id}`;
		const fontOptionsId = `signature-font-options-${this._id}`;

		// Collect mode buttons and sections for array references
		this.mode_buttons = [];
		this.mode_sections = [];

		const dialogStructure = {
			type: "element",
			tagName: "div",
			properties: {
				id: popoverId,
				popover: "manual",
				className: ["signature-dialog"],
			},
			ref: "dialog",
			data: {
				onclick: (e) => {
					// Close on backdrop click
					if (e.target === this.dialog) {
						this.hide_dialog();
					}
				},
				onkeydown: (e) => {
					if (e.key === "Escape") {
						this.hide_dialog();
					}
				},
			},
			children: [
				// Header
				{
					type: "element",
					tagName: "div",
					properties: { className: ["signature-dialog-header"] },
					children: [
						{
							type: "element",
							tagName: "h3",
							properties: {},
							children: [
								{
									type: "text",
									value: __("Add your {0}", [termLower]),
								},
							],
						},
						{
							type: "element",
							tagName: "button",
							properties: {
								type: "button",
								className: ["signature-dialog-close"],
								ariaLabel: __("Close"),
							},
							data: { onclick: () => this.hide_dialog() },
							children: [{ type: "text", value: "×" }],
						},
					],
				},
				// Body
				{
					type: "element",
					tagName: "div",
					properties: { className: ["signature-dialog-body"] },
					children: [
						// Mode buttons
						{
							type: "element",
							tagName: "div",
							properties: {
								className: ["signature-mode-buttons"],
							},
							children: [
								{
									type: "element",
									tagName: "button",
									properties: {
										type: "button",
										className: ["signature-mode-btn", "active"],
										dataMode: "draw",
									},
									data: {
										constructor: (el) => this.mode_buttons.push(el),
										onclick: () => this.select_mode("draw"),
									},
									children: [{ type: "text", value: __("Draw") }],
								},
								{
									type: "element",
									tagName: "button",
									properties: {
										type: "button",
										className: ["signature-mode-btn"],
										dataMode: "type",
									},
									data: {
										constructor: (el) => this.mode_buttons.push(el),
										onclick: () => this.select_mode("type"),
									},
									children: [{ type: "text", value: __("Type") }],
								},
								{
									type: "element",
									tagName: "button",
									properties: {
										type: "button",
										className: ["signature-mode-btn"],
										dataMode: "upload",
									},
									data: {
										constructor: (el) => this.mode_buttons.push(el),
										onclick: () => this.select_mode("upload"),
									},
									children: [{ type: "text", value: __("Upload") }],
								},
							],
						},
						// Mode sections container
						{
							type: "element",
							tagName: "div",
							properties: {
								className: ["signature-mode-sections"],
							},
							children: [
								// Draw section
								{
									type: "element",
									tagName: "div",
									properties: {
										className: ["signature-section", "signature-draw-section", "active"],
										dataSection: "draw",
									},
									data: {
										constructor: (el) => this.mode_sections.push(el),
									},
									children: [
										{
											type: "element",
											tagName: "div",
											properties: {
												className: ["signature-canvas-wrapper"],
											},
											children: [
												{
													type: "element",
													tagName: "canvas",
													properties: {
														className: ["signature-pad-canvas"],
													},
													ref: "pad_canvas",
													children: [],
												},
												{
													type: "element",
													tagName: "div",
													properties: {
														className: ["signature-line"],
													},
													children: [],
												},
											],
										},
										{
											type: "element",
											tagName: "div",
											properties: {
												className: ["signature-btn-row"],
											},
											children: [
												{
													type: "element",
													tagName: "a",
													properties: {
														href: "#",
														type: "button",
														className: ["signature-reset", "btn", "icon-btn"],
													},
													data: {
														onclick: () => {
															if (this.signature_pad) {
																this.signature_pad.clear();
															}
														},
													},
													children: [createIconHast("es-line-reload", "sm")],
												},
											],
										},
									],
								},
								// Type section
								{
									type: "element",
									tagName: "div",
									properties: {
										className: ["signature-section", "signature-type-section"],
										dataSection: "type",
									},
									data: {
										constructor: (el) => this.mode_sections.push(el),
									},
									children: [
										{
											type: "element",
											tagName: "div",
											properties: {
												className: ["signature-type-inputs"],
											},
											children: [
												{
													type: "element",
													tagName: "input",
													properties: {
														type: "text",
														className: ["signature-typed-input"],
														placeholder: __("Type your {0}", [termLower]),
													},
													ref: "typed_input",
													data: {
														oninput: () => this.update_typed_preview(),
													},
													children: [],
												},
												// Font selector
												{
													type: "element",
													tagName: "div",
													properties: {
														className: ["signature-font-select"],
													},
													children: [
														{
															type: "element",
															tagName: "button",
															properties: {
																type: "button",
																className: ["signature-font-trigger"],
																popoverTarget: fontOptionsId,
																popoverTargetAction: "toggle",
															},
															children: [
																{
																	type: "element",
																	tagName: "span",
																	properties: {
																		className: ["signature-font-value"],
																	},
																	ref: "font_value_display",
																	children: [
																		{
																			type: "text",
																			value: "",
																		},
																	],
																},
																{
																	type: "element",
																	tagName: "span",
																	properties: {
																		className: ["signature-font-arrow"],
																	},
																	children: [
																		{
																			type: "text",
																			value: "▾",
																		},
																	],
																},
															],
														},
														{
															type: "element",
															tagName: "div",
															properties: {
																id: fontOptionsId,
																popover: "auto",
																className: ["signature-font-popover"],
															},
															ref: "font_popover",
															children: [],
														},
													],
												},
											],
										},
										// Typed preview
										{
											type: "element",
											tagName: "div",
											properties: {
												className: ["signature-typed-preview"],
											},
											children: [
												{
													type: "element",
													tagName: "div",
													properties: {
														className: ["signature-typed-text"],
													},
													ref: "typed_preview_text",
													children: [],
												},
												{
													type: "element",
													tagName: "div",
													properties: {
														className: ["signature-line"],
													},
													children: [],
												},
											],
										},
									],
								},
								// Upload section
								{
									type: "element",
									tagName: "div",
									properties: {
										className: ["signature-section", "signature-upload-section"],
										dataSection: "upload",
									},
									data: {
										constructor: (el) => this.mode_sections.push(el),
									},
									children: [
										{
											type: "element",
											tagName: "div",
											properties: {
												className: ["signature-upload-area"],
											},
											ref: "upload_area",
											data: {
												onclick: (e) => {
													if (e.target !== this.file_input) {
														this.file_input.click();
													}
												},
												ondragover: (e) => {
													e.preventDefault();
													this.upload_area.classList.add("drag-over");
												},
												ondragleave: () => {
													this.upload_area.classList.remove("drag-over");
												},
												ondrop: (e) => {
													e.preventDefault();
													this.upload_area.classList.remove("drag-over");
													const file = e.dataTransfer.files[0];
													if (file && file.type.startsWith("image/")) {
														this.process_uploaded_file(file);
													}
												},
											},
											children: [
												{
													type: "element",
													tagName: "input",
													properties: {
														type: "file",
														accept: "image/*",
														className: ["signature-file-input"],
													},
													ref: "file_input",
													data: {
														onchange: (e) => this.handle_file_select(e),
													},
													children: [],
												},
												{
													type: "element",
													tagName: "div",
													properties: {
														className: ["signature-upload-prompt"],
													},
													ref: "upload_prompt",
													children: [
														createIconHast("upload", "lg"),
														{
															type: "element",
															tagName: "div",
															properties: {},
															children: [
																{
																	type: "text",
																	value: __("Click or drag to upload"),
																},
															],
														},
													],
												},
												{
													type: "element",
													tagName: "div",
													properties: {
														className: ["signature-upload-preview"],
													},
													ref: "upload_preview",
													children: [
														{
															type: "element",
															tagName: "img",
															properties: {
																className: ["signature-upload-img"],
															},
															ref: "upload_img",
															children: [],
														},
													],
												},
											],
										},
									],
								},
							],
						},
					],
				},
				// Footer
				{
					type: "element",
					tagName: "div",
					properties: { className: ["signature-dialog-footer"] },
					children: [
						{
							type: "element",
							tagName: "button",
							properties: {
								type: "button",
								className: ["btn", "btn-md", "signature-btn", "signature-btn-secondary"],
							},
							data: { onclick: () => this.hide_dialog() },
							children: [{ type: "text", value: __("Cancel") }],
						},
						{
							type: "element",
							tagName: "button",
							properties: {
								type: "button",
								className: ["btn", "btn-md", "signature-btn", "signature-btn-primary"],
							},
							data: { onclick: () => this.handle_insert() },
							children: [
								{
									type: "text",
									value: __("Insert {0}", [term]),
								},
							],
						},
					],
				},
			],
		};

		toDom(dialogStructure, this);
		document.body.appendChild(this.dialog);
	}

	/**
	 * Shows the signature dialog
	 */
	show_dialog() {
		// Initialize font options if not already done (bundled fonts are always available)
		if (this._font_options.length === 0) {
			this._font_options = SIGNATURE_FONTS;
			this.build_font_options();
			if (this._font_options.length > 0) {
				this.select_font(this._font_options[0].value);
			}
		}

		// Reset state
		this._upload_data = null;
		this.upload_preview.classList.remove("active");
		this.upload_prompt.classList.remove("hidden");
		this.typed_input.value = "";
		this.update_typed_preview();

		// Show dialog
		this.dialog.showPopover();

		// Initialize signature pad after dialog is visible
		requestAnimationFrame(() => {
			this.init_signature_pad();
		});
	}

	/**
	 * Hides the signature dialog
	 */
	hide_dialog() {
		this.dialog.hidePopover();
	}

	/**
	 * Selects a signature mode (draw, type, upload)
	 * @param {string} mode - The mode to select
	 */
	select_mode(mode) {
		this._current_mode = mode;

		// Update button states
		this.mode_buttons.forEach((btn) => {
			btn.classList.toggle("active", btn.dataset.mode === mode);
		});

		// Update section visibility
		this.mode_sections.forEach((section) => {
			section.classList.toggle("active", section.dataset.section === mode);
		});

		// Initialize signature pad when switching to draw mode
		if (mode === "draw") {
			requestAnimationFrame(() => this.init_signature_pad());
		}
	}

	/**
	 * Initializes the signature pad on the draw canvas
	 */
	init_signature_pad() {
		if (!this.pad_canvas) return;

		// Resize canvas to match CSS size
		this.resize_pad_canvas();

		if (!this.signature_pad) {
			this.signature_pad = new SignaturePad(this.pad_canvas, {
				backgroundColor: "transparent",
				// black ink — baked into the saved signature PNG, which is composited
				// onto the (white) signed document; must NOT follow the desk theme.
				penColor: "black",
			});
		}
	}

	/**
	 * Resizes the pad canvas to match CSS dimensions and device pixel ratio
	 */
	resize_pad_canvas() {
		const ratio = Math.max(window.devicePixelRatio || 1, 1);
		const rect = this.pad_canvas.getBoundingClientRect();

		if (rect.width === 0 || rect.height === 0) return;

		if (this.pad_canvas.width !== rect.width * ratio || this.pad_canvas.height !== rect.height * ratio) {
			this.pad_canvas.width = rect.width * ratio;
			this.pad_canvas.height = rect.height * ratio;
			this.pad_canvas.getContext("2d").scale(ratio, ratio);

			if (this.signature_pad) {
				this.signature_pad.clear();
			}
		}
	}

	/**
	 * Builds font option buttons in the font popover
	 */
	build_font_options() {
		// Track font option buttons for select state updates
		this._font_option_buttons = [];

		const optionsStructure = {
			type: "element",
			tagName: "div",
			properties: { className: ["signature-font-options"] },
			children: this._font_options.map((opt) => ({
				type: "element",
				tagName: "button",
				properties: {
					type: "button",
					className: ["signature-font-option"],
					dataValue: opt.value,
				},
				data: {
					constructor: (el) => {
						this._font_option_buttons.push(el);
						el.style.fontFamily = opt.fontFamily;
					},
					onclick: () => {
						this.select_font(opt.value);
						this.font_popover.hidePopover();
					},
				},
				children: [{ type: "text", value: opt.label }],
			})),
		};

		const optionsEl = toDom(optionsStructure);
		this.font_popover.appendChild(optionsEl);
	}

	/**
	 * Selects a font for typed signatures
	 * @param {string} value - The font value to select
	 */
	select_font(value) {
		this._selected_font = value;
		const option = this._font_options.find((o) => o.value === value);

		if (option) {
			this.font_value_display.textContent = option.label;
			this.font_value_display.style.fontFamily = option.fontFamily;
		}

		// Update selected state in options using stored refs
		if (this._font_option_buttons) {
			this._font_option_buttons.forEach((btn) => {
				btn.classList.toggle("selected", btn.dataset.value === value);
			});
		}

		this.update_typed_preview();
	}

	/**
	 * Updates the typed signature preview
	 */
	update_typed_preview() {
		const text = this.typed_input.value || "";
		const option = this._font_options.find((o) => o.value === this._selected_font);
		const fontFamily = option?.fontFamily || SIGNATURE_FONTS[0].fontFamily;

		this.typed_preview_text.textContent = text;
		this.typed_preview_text.style.fontFamily = fontFamily;
	}

	/**
	 * Handles file selection from input
	 * @param {Event} e - The change event
	 */
	handle_file_select(e) {
		const file = e.target.files[0];
		if (file) {
			this.process_uploaded_file(file);
		}
	}

	/**
	 * Processes an uploaded file and shows preview
	 * @param {File} file - The uploaded file
	 */
	process_uploaded_file(file) {
		const reader = new FileReader();
		reader.addEventListener("load", (e) => {
			this._upload_data = e.target.result;
			this.upload_img.src = this._upload_data;
			this.upload_preview.classList.add("active");
			this.upload_prompt.classList.add("hidden");
		});
		reader.readAsDataURL(file);
	}

	/**
	 * Handles the insert button click
	 */
	handle_insert() {
		const term = this.get_signature_term().toLowerCase();

		if (this._current_mode === "draw") {
			if (!this.signature_pad || this.signature_pad.isEmpty()) {
				frappe.toast({
					message: __("Please draw a {0} first", [term]),
					indicator: "orange",
				});
				return;
			}
			const data = this.pad_canvas.toDataURL("image/png");
			this.set_signature_value(data);
		} else if (this._current_mode === "type") {
			const text = this.typed_input.value.trim();
			if (!text) {
				frappe.toast({
					message: __("Please enter {0} text", [term]),
					indicator: "orange",
				});
				return;
			}
			const data = this.convert_typed_to_base64(text);
			this.set_signature_value(data);
		} else if (this._current_mode === "upload") {
			if (!this._upload_data) {
				frappe.toast({
					message: __("Please upload a {0} image", [term]),
					indicator: "orange",
				});
				return;
			}
			this.normalize_upload_to_canvas(this._upload_data).then((data) => {
				this.set_signature_value(data);
			});
			return; // Don't hide yet, wait for promise
		}

		this.hide_dialog();
	}

	/**
	 * Converts typed text to base64 PNG
	 * @param {string} text - The text to convert
	 * @returns {string} Base64 data URL
	 */
	convert_typed_to_base64(text) {
		const option = this._font_options.find((o) => o.value === this._selected_font);
		const fontFamily = option?.fontFamily || SIGNATURE_FONTS[0].fontFamily;

		const canvas = document.createElement("canvas");
		canvas.width = 750;
		canvas.height = 292;
		const ctx = canvas.getContext("2d");

		ctx.fillStyle = "transparent";
		ctx.fillRect(0, 0, canvas.width, canvas.height);

		// black ink — baked into the saved signature PNG (see init_signature_pad);
		// must NOT follow the desk theme or it would be invisible on the document.
		ctx.fillStyle = "#000000";
		ctx.textAlign = "center";
		ctx.textBaseline = "alphabetic";

		// Draw text at 75% from top (on the signature line)
		const signatureLineY = canvas.height * 0.75;

		// Start with a large font size and scale down if text is too wide
		let fontSize = 120;

		ctx.font = `italic ${fontSize}px ${fontFamily}`;
		let textWidth = ctx.measureText(text).width;

		// Scale down font if text is too wide
		while (textWidth > canvas.width && fontSize > 20) {
			fontSize -= 2;
			ctx.font = `italic ${fontSize}px ${fontFamily}`;
			textWidth = ctx.measureText(text).width;
		}

		ctx.fillText(text, canvas.width / 2, signatureLineY);

		return canvas.toDataURL("image/png");
	}

	/**
	 * Normalizes an uploaded image to a consistent canvas size
	 * @param {string} dataUrl - The uploaded image data URL
	 * @returns {Promise<string>} Normalized base64 data URL
	 */
	normalize_upload_to_canvas(dataUrl) {
		return new Promise((resolve, reject) => {
			const canvas = document.createElement("canvas");
			canvas.width = 750;
			canvas.height = 292;
			const ctx = canvas.getContext("2d");

			ctx.fillStyle = "transparent";
			ctx.fillRect(0, 0, canvas.width, canvas.height);

			const img = new Image();
			img.addEventListener("load", () => {
				const padding = 20;
				const maxWidth = canvas.width - padding * 2;
				const maxHeight = canvas.height - padding * 2;

				let width = img.width;
				let height = img.height;
				const aspectRatio = width / height;

				if (width > maxWidth) {
					width = maxWidth;
					height = width / aspectRatio;
				}
				if (height > maxHeight) {
					height = maxHeight;
					width = height * aspectRatio;
				}

				const x = (canvas.width - width) / 2;
				const y = (canvas.height - height) / 2;

				ctx.drawImage(img, x, y, width, height);
				resolve(canvas.toDataURL("image/png"));
			});
			img.addEventListener("error", reject);
			img.src = dataUrl;
		});
	}

	/**
	 * Sets the signature value and updates the display
	 * @param {string} data - Base64 signature data
	 */
	set_signature_value(data) {
		this.value = data;
		this.set_value(data);
		this.render_display();
		this.hide_dialog();

		frappe.toast({
			message: __("{0} added successfully", [this.get_signature_term()]),
			indicator: "green",
		});
	}

	/**
	 * Resolves a CSS custom property to a fully-computed color string.
	 * Canvas 2D can't parse `var(--x)`, so we read the resolved color off a
	 * hidden probe element — reading `color` guarantees a concrete rgb() value.
	 */
	resolve_css_color(var_name, fallback = "#d1d8dd") {
		const probe = document.createElement("span");
		probe.style.color = `var(${var_name}, ${fallback})`;
		probe.style.display = "none";
		document.body.appendChild(probe);
		const color = getComputedStyle(probe).color;
		probe.remove();
		return color || fallback;
	}

	/**
	 * Re-renders the empty-state placeholder when the desk theme changes so its
	 * border tracks the active theme. Set up once per control instance.
	 */
	setup_theme_observer() {
		if (this._theme_observer) return;
		this._theme_observer = new MutationObserver(() => {
			if (!this.get_value()) this.render_display();
		});
		this._theme_observer.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ["data-theme"],
		});
	}

	/**
	 * Renders the signature on the display canvas
	 */
	render_display() {
		if (!this.display_canvas) return;
		this.setup_theme_observer();

		const ctx = this.display_canvas.getContext("2d");
		ctx.clearRect(0, 0, this.display_canvas.width, this.display_canvas.height);

		const value = this.get_value();
		if (value) {
			const img = new Image();
			img.addEventListener("load", () => {
				ctx.drawImage(img, 0, 0, this.display_canvas.width, this.display_canvas.height);
			});
			img.src = value;
			this.display_wrapper.classList.add("has-signature");
		} else {
			this.render_empty_display();
			this.display_wrapper.classList.remove("has-signature");
		}
	}

	/**
	 * Renders the empty state on the display canvas
	 */
	render_empty_display() {
		const ctx = this.display_canvas.getContext("2d");
		ctx.clearRect(0, 0, this.display_canvas.width, this.display_canvas.height);

		ctx.setLineDash([5, 5]);
		// Canvas can't parse var(); resolve the themed border color from the DOM.
		ctx.strokeStyle = this.resolve_css_color("--border-color");
		ctx.lineWidth = 2;
		ctx.strokeRect(10, 10, this.display_canvas.width - 20, this.display_canvas.height - 20);
		ctx.setLineDash([]);
	}

	// ─────────────────────────────────────────────────────────────────
	// Base class interface methods
	// ─────────────────────────────────────────────────────────────────

	set_input(value) {
		this.value = value;
		this.render_display();
	}

	get_input_value() {
		return this.value;
	}

	get_value() {
		const value = this.value || this.get_model_value();
		// Ignore placeholder image
		if (value === "/assets/frappe/images/signature-placeholder.png") {
			return "";
		}
		return value;
	}

	set_formatted_input(value) {
		this.set_input(value);
	}

	refresh_input() {
		// Call base class to handle label, description, mandatory styling, etc.
		super.refresh_input();

		// Now safe to render our custom display
		this.render_display();

		// Update read-only state
		if (this.display_wrapper) {
			if (this.get_status() !== "Write") {
				this.display_wrapper.classList.add("readonly");
			} else {
				this.display_wrapper.classList.remove("readonly");
			}
		}
	}
}
