// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

/**
 * @fileoverview The frappe control class the eSign controls extend, typed for them.
 *
 * frappe-types declares every `frappe.ui.form.Control*` class as the base `Control`. At
 * runtime `ControlData` extends `ControlInput` (frappe/public/js/frappe/form/controls/data.js),
 * and the eSign controls use its input area and two of its own methods, so this module
 * declares those members once and hands out the same class under that type.
 *
 * @author Avunu LLC
 */

import type { BaseControl, ControlInput, ControlOptions } from "frappe-types";

/**
 * A `ControlData` instance as the eSign controls use it. Its focus target (`$input`,
 * `input`) is whatever element the control renders (a button, a canvas, a hidden input),
 * which frappe only ever treats as an element.
 */
export interface ControlDataInstance extends Omit<ControlInput, "$input" | "input" | ControlMethod> {
	$input?: JQuery<HTMLElement>;
	input?: HTMLElement;
	// The methods the eSign controls override, kept as methods (Omit turns them into properties).
	make_input(): void;
	set_input(value: unknown): void;
	get_input_value(): unknown;
	get_value(): unknown;
	refresh(): void;
	refresh_input(): void;
	/** frappe/public/js/frappe/form/controls/data.js: copies `df` attributes onto `$input`. */
	set_input_attributes(): void;
	/** frappe/public/js/frappe/form/controls/data.js: renders a value into the input. */
	set_formatted_input(value: unknown): unknown;
}

type ControlMethod =
	| "make_input"
	| "set_input"
	| "get_input_value"
	| "get_value"
	| "refresh"
	| "refresh_input";

export interface ControlDataClass {
	new (opts: ControlOptions): ControlDataInstance;
	prototype: ControlDataInstance;
}

/** `frappe.ui.form.ControlData`, typed as the class it is at runtime. */
export const ControlData = frappe.ui.form.ControlData as ControlDataClass;

/** Every eSign control is a frappe control: the type `frappe.ui.form` registers it under. */
export type ControlClass = typeof BaseControl;
