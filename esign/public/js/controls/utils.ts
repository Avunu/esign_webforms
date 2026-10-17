// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * @fileoverview Shared utilities for eSign controls
 * @description Provides HAST-based utilities for DOM structure creation.
 *
 * @requires hast-util-to-dom - For efficient DOM structure creation
 *
 * @author Avunu LLC
 */

import type { Properties } from "hast";
import { toDom as hastToDom } from "hast-util-to-dom";

/**
 * Element callbacks: `constructor` is called with the created element, every other key is
 * assigned to the element as a property (`onclick`, `oninput`, …).
 */
export interface HastData {
	// Each handler takes its own event type, so the parameter is typed at the use site.
	[key: string]: ((arg: never) => unknown) | undefined;
}

/** A hast element with the two additions `toDom` understands: `ref` and `data`. */
export interface HastElement {
	type: "element";
	tagName: string;
	properties: Properties;
	children: HastChild[];
	/** `toDom` assigns the created element to `context[ref]`. */
	ref?: string;
	data?: HastData;
}

export interface HastText {
	type: "text";
	value: string;
}

export type HastChild = HastElement | HastText;

/**
 * Converts HAST to DOM with support for element refs and event bindings.
 *
 * Supports ref pattern:
 * - String ref (preferred): `ref: "myElement"` → assigns to `context.myElement`
 *
 * Supports constructor callback:
 * - Callback constructor: `data: { constructor: (el) => ... }` → calls function with element
 *
 * Event listeners are assigned via `data` property:
 * - `data: { onclick: (e) => ... }`
 *
 * @param hast - HAST structure
 * @param context - Object to assign string refs to (typically `this`)
 * @returns The root element
 */
export function toDom(hast: HastElement, context?: object): HTMLElement {
	const root = hastToDom(hast, {
		afterTransform(node, element) {
			if (node.type !== "element" || !(element instanceof Element)) {
				return;
			}
			const { ref, data } = node as Partial<HastElement>;
			// Handle string ref: assign element to context property
			if (ref && context) {
				Reflect.set(context, ref, element);
			}
			// Handle data properties (callback refs, events, etc.)
			for (const [key, value] of Object.entries(data ?? {})) {
				if (key === "constructor" && typeof value === "function") {
					(value as (el: Element) => void)(element); // Call ref callback with element
				} else {
					Reflect.set(element, key, value); // Assign event handlers
				}
			}
		},
	});
	if (!(root instanceof HTMLElement)) {
		throw new TypeError(`toDom: <${hast.tagName}> did not produce an HTML element`);
	}
	return root;
}

/** A custom icon size, as CSS lengths. */
export interface IconSize {
	width: string;
	height: string;
}

/**
 * Creates a HAST node for an SVG icon compatible with Frappe's icon system.
 * Supports both standard icons (icon-*) and Espresso icons (es-*).
 *
 * @param icon_name - The name of the icon (e.g., "edit", "add", "es-line-reload")
 * @param size - Size preset ("xs", "sm", "md", "lg") or custom dimensions
 * @param icon_class - Additional class for the <use> element
 * @param icon_style - Additional inline styles for the <svg> element
 * @param svg_class - Additional class for the <svg> element
 * @returns HAST element node representing the SVG icon
 *
 * @example
 * // Standard icon
 * createIconHast("edit", "md")
 *
 * @example
 * // Espresso icon
 * createIconHast("es-line-reload", "sm")
 *
 * @example
 * // Custom size
 * createIconHast("add", { width: "24px", height: "24px" })
 */
export function createIconHast(
	icon_name: string,
	size: string | IconSize = "sm",
	icon_class = "",
	icon_style = "",
	svg_class = "",
): HastElement {
	let size_class = "";
	const is_espresso = icon_name.startsWith("es-");

	const href = is_espresso ? `#${icon_name}` : `#icon-${icon_name}`;

	if (typeof size === "object") {
		icon_style += ` width: ${size.width}; height: ${size.height}`;
	} else {
		size_class = `icon-${size}`;
	}

	// Determine SVG class based on icon type
	let base_svg_class;
	if (is_espresso) {
		base_svg_class = icon_name.startsWith("es-solid") ? "es-icon es-solid" : "es-icon es-line";
	} else {
		base_svg_class = "icon";
	}

	const classes = [base_svg_class, svg_class, size_class].filter(Boolean);

	return {
		type: "element",
		tagName: "svg",
		properties: {
			className: classes,
			style: icon_style || undefined,
			ariaHidden: "true",
		},
		children: [
			{
				type: "element",
				tagName: "use",
				properties: {
					className: icon_class ? [icon_class] : undefined,
					href: href,
				},
				children: [],
			},
		],
	};
}
