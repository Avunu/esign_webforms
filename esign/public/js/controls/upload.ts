// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * @fileoverview Upload control for Frappe Framework
 * @description This module provides a file upload control with preview functionality.
 * Uses HAST for DOM structure creation.
 *
 * @requires hast-util-to-dom - For efficient DOM structure creation
 *
 * @author Avunu LLC
 */

import { ControlData } from "./base";
import { toDom, type HastElement } from "./utils";

/** `df.options` of an Upload field, when it restricts the file types. */
interface UploadOptions {
	allowed_file_types?: string[];
}

export class ControlUpload extends ControlData {
	declare file_input: HTMLInputElement;
	declare preview_element: HTMLElement;
	declare preview_img: HTMLImageElement;

	override make_input(): void {
		if (this.$input) return;

		const options = this.df.options as UploadOptions | string | undefined;
		const allowed = typeof options === "object" ? options.allowed_file_types : undefined;

		// Define complete structure using hast (HTML Abstract Syntax Tree)
		// Structure: div.upload-wrapper > [button.btn-upload, input[type=file], div.upload-preview > img]
		const uploadStructure: HastElement = {
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
						accept: allowed?.length ? allowed : ["image/*"],
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

		// Get references by position:
		// [button.btn-upload, input[type=file], div.upload-preview > img.upload-preview-img]
		const [button, file_input, preview] = wrapper.children;
		const preview_img = preview?.children[0];
		if (
			!(button instanceof HTMLButtonElement) ||
			!(file_input instanceof HTMLInputElement) ||
			!(preview instanceof HTMLElement) ||
			!(preview_img instanceof HTMLImageElement)
		) {
			throw new TypeError("ControlUpload: unexpected markup");
		}
		this.file_input = file_input;
		this.preview_element = preview;
		this.preview_img = preview_img;

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

	handle_file_selection(e: Event): void {
		const file = (e.target as HTMLInputElement).files?.[0];
		if (!file) return;

		// Convert to base64
		const reader = new FileReader();
		reader.addEventListener("load", () => {
			const dataurl = reader.result as string;
			void this.set_value(dataurl);
			this.value = dataurl;
			this.set_preview(dataurl);
		});
		reader.readAsDataURL(file);
	}

	set_preview(dataurl: unknown): void {
		if (typeof dataurl === "string" && dataurl) {
			this.preview_img.src = dataurl;
			this.preview_element.classList.add("active");
			this.$input?.text(__("Change"));
		} else {
			this.preview_element.classList.remove("active");
			this.$input?.text(__("Upload"));
		}
	}

	override set_input(value: unknown): void {
		this.last_value = this.value;
		this.value = value;
		this.set_formatted_input(value);
		this.set_preview(value);
	}

	override get_value(): unknown {
		return this.value || null;
	}
}
