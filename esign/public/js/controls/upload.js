// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

import { toDom } from "hast-util-to-dom";

/**
 * @fileoverview Upload control for Frappe Framework
 * @description This module provides a file upload control with preview functionality.
 * Uses HAST for DOM structure creation.
 *
 * @requires hast-util-to-dom - For efficient DOM structure creation
 *
 * @author Avunu LLC
 */

export class ControlUpload extends frappe.ui.form.ControlData {
	make_input() {
		if (this.$input) return;

		// Define complete structure using hast (HTML Abstract Syntax Tree)
		// Structure: div.upload-wrapper > [button.btn-upload, input[type=file], div.upload-preview > img]
		const uploadStructure = {
			type: "element",
			tagName: "div",
			properties: { className: ["upload-wrapper"] },
			children: [
				{
					type: "element",
					tagName: "button",
					properties: {
						type: "button",
						className: ["btn", "btn-default", "btn-sm", "btn-upload"],
					},
					children: [{ type: "text", value: __("Upload") }],
				},
				{
					type: "element",
					tagName: "input",
					properties: {
						type: "file",
						className: ["hidden"],
						accept: this.df.options?.allowed_file_types?.join(",") || "image/*",
					},
					children: [],
				},
				{
					type: "element",
					tagName: "div",
					properties: { className: ["upload-preview"] },
					children: [
						{
							type: "element",
							tagName: "img",
							properties: { className: ["upload-preview-img"] },
							children: [],
						},
					],
				},
			],
		};

		// Convert hast to DOM
		const wrapper = toDom(uploadStructure);
		this.input_area.appendChild(wrapper);

		// Get references via property accessors
		// wrapper.children[0] = button.btn-upload
		// wrapper.children[1] = input[type=file]
		// wrapper.children[2] = div.upload-preview
		// wrapper.children[2].children[0] = img.upload-preview-img
		const button = wrapper.children[0];
		this.file_input = wrapper.children[1];
		this.preview_element = wrapper.children[2];
		this.preview_img = this.preview_element.children[0];

		// Bind event listeners
		this.file_input.addEventListener("change", (e) => {
			this.handle_file_selection(e);
		});

		button.addEventListener("click", (e) => {
			e.preventDefault();
			this.file_input.click();
		});

		// Set references for base class compatibility
		this.$input = $(button);
		this.input = button;
		this.has_input = true;
		this.set_input_attributes();
	}

	handle_file_selection(e) {
		const file = e.target.files[0];
		if (!file) return;

		// Convert to base64
		const reader = new FileReader();
		reader.addEventListener("load", (event) => {
			const dataurl = event.target.result;
			this.set_value(dataurl);
			this.value = dataurl;
			this.set_preview(dataurl);
		});
		reader.readAsDataURL(file);
	}

	set_preview(dataurl) {
		if (dataurl) {
			this.preview_img.src = dataurl;
			this.preview_element.classList.add("active");
			this.$input.textContent = __("Change");
		} else {
			this.preview_element.classList.remove("active");
			this.$input.textContent = __("Upload");
		}
	}

	set_input(value) {
		this.last_value = this.value;
		this.value = value;
		this.set_formatted_input(value);
		this.set_preview(value);
	}

	get_value() {
		return this.value || null;
	}
}
