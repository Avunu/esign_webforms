// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { toDom } from "./utils";

/**
 * @fileoverview FontSelect control for Frappe Framework
 * @description A custom select control that renders font options in their actual font.
 * Uses HAST for DOM creation, Popover API for dropdown, and CSS Anchor Positioning.
 * Checks local font availability using the Local Font Access API when available.
 *
 * @requires hast-util-to-dom - For efficient DOM structure creation
 *
 * @author Avunu LLC
 */

/**
 * Generates a unique anchor name for CSS anchor positioning
 * @returns {string} Unique anchor name
 */
let anchorCounter = 0;
function generateAnchorName() {
	return `--font-select-anchor-${++anchorCounter}`;
}

/**
 * Checks which fonts from a list are available locally using the Local Font Access API.
 * Falls back to returning all fonts if the API is unavailable or permission is denied.
 *
 * @param {Array<{value: string, label: string, fontFamily: string, variants?: string[]}>} fonts
 *   Array of font options. Each option can include:
 *   - value: The value to use when selected
 *   - label: Display label for the option
 *   - fontFamily: CSS font-family value
 *   - variants: Optional array of font family name variants to check for availability
 * @returns {Promise<Array<{value: string, label: string, fontFamily: string}>>}
 *   Filtered array of available fonts
 *
 * @example
 * const fonts = [
 *   {
 *     value: "brush-script",
 *     label: "Brush Script",
 *     fontFamily: '"Brush Script MT", cursive',
 *     variants: ["Brush Script MT", "Brush Script Std", "BrushScriptMT"]
 *   }
 * ];
 * const available = await filterAvailableFonts(fonts);
 */
export async function filterAvailableFonts(fonts) {
	if (!fonts || fonts.length === 0) {
		return [];
	}

	// If Local Font Access API is not available, return all fonts
	if (!("queryLocalFonts" in window)) {
		return fonts.map(({ value, label, fontFamily }) => ({
			value,
			label,
			fontFamily,
		}));
	}

	try {
		const localFonts = await window.queryLocalFonts();
		const localFontNames = new Set(localFonts.map((f) => f.family.toLowerCase()));

		const available = [];
		for (const font of fonts) {
			// Use variants if provided, otherwise use the label as the variant
			const variants = font.variants || [font.label];
			const isAvailable = variants.some((variant) => localFontNames.has(variant.toLowerCase()));
			if (isAvailable) {
				available.push({
					value: font.value,
					label: font.label,
					fontFamily: font.fontFamily,
				});
			}
		}

		// If no fonts are available locally, fall back to all fonts
		// (they may still render via web fonts or fallbacks)
		return available.length > 0
			? available
			: fonts.map(({ value, label, fontFamily }) => ({
					value,
					label,
					fontFamily,
				}));
	} catch {
		// Permission denied or other error - return all fonts
		return fonts.map(({ value, label, fontFamily }) => ({
			value,
			label,
			fontFamily,
		}));
	}
}

export class ControlFontSelect extends frappe.ui.form.ControlData {
	/**
	 * Initializes the control. Called by Frappe's control lifecycle.
	 * Triggers async font availability check.
	 */
	make_input() {
		if (this.has_input) return;

		// Mark as having input to prevent re-entry
		this.has_input = true;
		this._options = [];
		this._available_options = [];
		this._is_hidden = false;

		// Parse options and check availability asynchronously
		this._init_promise = this._init_async();
	}

	/**
	 * Async initialization - parses options, checks font availability, builds UI
	 * @private
	 */
	async _init_async() {
		// Parse options from df.options
		this._options = this.parse_options();

		// Filter to only available fonts
		this._available_options = await filterAvailableFonts(this._options);

		// If 0 or 1 font available, hide the control (no meaningful choice)
		if (this._available_options.length <= 1) {
			this._is_hidden = true;
			this._hide_control();

			// If exactly one font, set it as the value
			if (this._available_options.length === 1) {
				this.value = this._available_options[0].value;
			}
			return;
		}

		// Build the UI
		this._build_ui();

		// Set initial value
		const defaultValue = this.df.default || (this._available_options[0] && this._available_options[0].value);
		if (defaultValue) {
			this.set_input(defaultValue);
		}
	}

	/**
	 * Hides the control when there's no meaningful choice
	 * @private
	 */
	_hide_control() {
		// Hide the entire field wrapper if possible
		if (this.$wrapper) {
			this.$wrapper.hide();
		} else if (this.wrapper) {
			this.wrapper.style.display = "none";
		}
	}

	/**
	 * Shows the control
	 * @private
	 */
	_show_control() {
		if (this.$wrapper) {
			this.$wrapper.show();
		} else if (this.wrapper) {
			this.wrapper.style.display = "";
		}
	}

	/**
	 * Builds the font select UI
	 * @private
	 */
	_build_ui() {
		this._anchor_name = generateAnchorName();

		// Generate unique IDs for popover association
		const popoverId = `font-select-popover-${anchorCounter}`;

		// Build options list for HAST
		const optionItems = this._available_options.map((opt, index) => ({
			type: "element",
			tagName: "button",
			properties: {
				type: "button",
				className: ["font-select-option"],
				dataValue: opt.value,
				dataIndex: index,
				dataFontFamily: opt.fontFamily,
			},
			children: [{ type: "text", value: opt.label }],
		}));

		// Define complete structure using HAST
		const wrapperStructure = {
			type: "element",
			tagName: "div",
			properties: {
				className: ["font-select-wrapper"],
				style: `anchor-name: ${this._anchor_name};`,
			},
			children: [
				{
					type: "element",
					tagName: "button",
					properties: {
						type: "button",
						className: ["font-select-trigger", "btn", "btn-default", "btn-sm"],
						popoverTarget: popoverId,
						popoverTargetAction: "toggle",
					},
					children: [
						{
							type: "element",
							tagName: "span",
							properties: { className: ["font-select-value"] },
							children: [{ type: "text", value: "" }],
						},
						{
							type: "element",
							tagName: "span",
							properties: { className: ["font-select-arrow"] },
							children: [{ type: "text", value: "▾" }],
						},
					],
				},
				{
					type: "element",
					tagName: "div",
					properties: {
						id: popoverId,
						popover: "auto",
						className: ["font-select-popover"],
						style: `position-anchor: ${this._anchor_name};`,
					},
					children: [
						{
							type: "element",
							tagName: "div",
							properties: { className: ["font-select-options"] },
							children: optionItems,
						},
					],
				},
			],
		};

		// Convert HAST to DOM
		this.font_select_wrapper = toDom(wrapperStructure);
		this.input_area.appendChild(this.font_select_wrapper);

		// Get references
		this.trigger_button = this.font_select_wrapper.children[0];
		this.value_display = this.trigger_button.children[0];
		this.popover_element = this.font_select_wrapper.children[1];
		this.options_container = this.popover_element.children[0];

		// Apply font-family styles to option buttons
		const optionButtons = this.options_container.children;
		for (let i = 0; i < optionButtons.length; i++) {
			const btn = optionButtons[i];
			btn.style.fontFamily = btn.dataset.fontFamily;
		}

		// Bind click handlers for options
		this.options_container.addEventListener("click", (e) => {
			const optionButton = e.target.closest(".font-select-option");
			if (optionButton) {
				const value = optionButton.dataset.value;
				this.set_input(value);
				this.popover_element.hidePopover();
				if (this.df.onchange) {
					this.df.onchange();
				}
			}
		});

		// Create hidden input for form compatibility
		this.hidden_input = document.createElement("input");
		this.hidden_input.type = "hidden";
		this.hidden_input.name = this.df.fieldname;
		this.font_select_wrapper.appendChild(this.hidden_input);

		// Set references for base class compatibility
		this.$input = $(this.trigger_button);
		this.input = this.hidden_input;
	}

	/**
	 * Parses options from df.options
	 * Supports:
	 * - Array of strings: ["Font A", "Font B"]
	 * - Array of objects: [{ value: "font-a", label: "Font A", fontFamily: "...", variants: [...] }]
	 * - Newline-separated string: "Font A\nFont B"
	 * @returns {Array<{value: string, label: string, fontFamily: string, variants?: string[]}>}
	 */
	parse_options() {
		let options = this.df.options || [];

		if (typeof options === "string") {
			options = options.split("\n").filter((o) => o.trim());
		}

		return options.map((opt) => {
			if (typeof opt === "string") {
				return {
					value: opt,
					label: opt,
					fontFamily: opt,
				};
			}
			return {
				value: opt.value || opt.label,
				label: opt.label || opt.value,
				fontFamily: opt.fontFamily || opt.value,
				variants: opt.variants,
			};
		});
	}

	/**
	 * Gets option by value from available options
	 * @param {string} value
	 * @returns {Object|undefined}
	 */
	get_option(value) {
		return this._available_options.find((opt) => opt.value === value);
	}

	/**
	 * Gets all available options
	 * @returns {Array<{value: string, label: string, fontFamily: string}>}
	 */
	get_options() {
		return this._available_options;
	}

	/**
	 * Returns whether the control is hidden due to insufficient options
	 * @returns {boolean}
	 */
	is_hidden() {
		return this._is_hidden;
	}

	/**
	 * Waits for async initialization to complete
	 * @returns {Promise<void>}
	 */
	async ready() {
		if (this._init_promise) {
			await this._init_promise;
		}
	}

	set_input(value) {
		this.last_value = this.value;
		this.value = value;

		const option = this.get_option(value);
		if (option && this.value_display) {
			this.value_display.textContent = option.label;
			this.value_display.style.fontFamily = option.fontFamily;
		}

		if (this.hidden_input) {
			this.hidden_input.value = value || "";
		}

		// Update selected state in options
		if (this.options_container) {
			const optionButtons = this.options_container.children;
			for (let i = 0; i < optionButtons.length; i++) {
				const btn = optionButtons[i];
				if (btn.dataset.value === value) {
					btn.classList.add("selected");
				} else {
					btn.classList.remove("selected");
				}
			}
		}
	}

	get_input_value() {
		return this.value;
	}

	get_value() {
		return this.value || this.get_model_value();
	}

	set_formatted_input(value) {
		this.set_input(value);
	}

	/**
	 * Refreshes options if they have changed
	 */
	async refresh() {
		super.refresh();

		// Wait for initial async setup
		await this.ready();

		// Check if options changed
		const newOptions = this.parse_options();
		const newOptionsJson = JSON.stringify(newOptions);
		if (this._last_options_json !== newOptionsJson) {
			this._last_options_json = newOptionsJson;
			this._options = newOptions;

			// Re-filter for availability
			this._available_options = await filterAvailableFonts(this._options);

			// Update visibility based on available options
			if (this._available_options.length <= 1) {
				this._is_hidden = true;
				this._hide_control();
				if (this._available_options.length === 1) {
					this.value = this._available_options[0].value;
				}
			} else {
				this._is_hidden = false;
				this._show_control();
				this.rebuild_options();
			}
		}
	}

	/**
	 * Rebuilds the options list
	 */
	rebuild_options() {
		if (!this.options_container) return;

		// Clear existing options
		while (this.options_container.firstChild) {
			this.options_container.removeChild(this.options_container.firstChild);
		}

		// Build new options
		this._available_options.forEach((opt, index) => {
			const optionStructure = {
				type: "element",
				tagName: "button",
				properties: {
					type: "button",
					className: ["font-select-option"],
					dataValue: opt.value,
					dataIndex: index,
				},
				children: [{ type: "text", value: opt.label }],
			};
			const optionEl = toDom(optionStructure);
			optionEl.style.fontFamily = opt.fontFamily;
			if (opt.value === this.value) {
				optionEl.classList.add("selected");
			}
			this.options_container.appendChild(optionEl);
		});
	}
}

// Register control globally for Frappe
frappe.ui.form.ControlFontSelect = ControlFontSelect;
