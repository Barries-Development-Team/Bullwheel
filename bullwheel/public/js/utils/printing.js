// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Shared label-printing helpers. Registered on the `bullwheel.printing` namespace
// rather than exported, because this bundle is loaded through `app_include_js` —
// DocType scripts have no way to import from it.

frappe.provide('bullwheel.printing');

const DEFAULT_BUTTON_GROUP = 'Print Labels';

function resolve_target(source, frm, fallback) {
	// A target may be given as a plain value or as a callback, and a callback may
	// return a promise. This lets a caller whose target is not known until click
	// time — a selected grid row, or a link chain that needs a server round trip —
	// defer resolution instead of capturing a stale value at refresh. An omitted
	// target falls back to the form's own document.
	if (source === undefined) {
		return Promise.resolve(fallback);
	}

	return Promise.resolve(typeof source === 'function' ? source(frm) : source);
}

// Add a button that renders the label configured for `slot` against a target document
// and sends it to a Label Printer chosen at click time.
//
//   frm           - the form the button is added to (required)
//   label         - button text, also used as the dialog title (required)
//   slot          - Bullwheel Settings ▸ Printing ▸ Labels slot, e.g. 'swap_tag' (required)
//   doctype       - target DocType; a value, or a callback returning one (or a promise
//                   for one). Defaults to the form's own DocType.
//   docname       - target document name; same forms as `doctype`. Defaults to the
//                   form's own name.
//   group         - custom button group. Defaults to 'Print Labels'.
//   empty_message - shown when a callback resolves no target, e.g. nothing selected.
//
// A callback that resolves nothing is a normal outcome, not an error: the user is told
// via `empty_message` and nothing is printed.
bullwheel.printing.add_print_button = function ({
	frm,
	label,
	slot,
	doctype,
	docname,
	group = DEFAULT_BUTTON_GROUP,
	empty_message,
}) {
	frm.add_custom_button(
		__(label),
		async () => {
			const [target_doctype, target_docname] = await Promise.all([
				resolve_target(doctype, frm, frm.doc.doctype),
				resolve_target(docname, frm, frm.doc.name),
			]);

			if (!target_doctype || !target_docname) {
				frappe.show_alert({
					message: empty_message || __('Select a document to print before printing {0}.', [__(label)]),
					indicator: 'orange',
				});
				return;
			}

			// Ask which configured Label Printer to send to, since there is no
			// default-printer concept yet. The tag layout itself lives in the
			// Zebra Printer Label record configured under Bullwheel Settings ▸
			// Printing ▸ Labels; the server renders it.
			frappe.prompt(
				[
					{
						label: __('Printer'),
						fieldname: 'printer',
						fieldtype: 'Link',
						options: 'Label Printer',
						reqd: 1,
					},
				],
				(values) => {
					frappe.show_alert({ message: __('Sending {0}...', [__(label)]), indicator: 'blue' });
					frappe.call({
						method: 'bullwheel.label_printing.print_label',
						args: {
							printer_name: values.printer,
							slot: slot,
							doctype: target_doctype,
							docname: target_docname,
						},
						callback() {
							frappe.show_alert({ message: __('{0} sent', [__(label)]), indicator: 'green' });
						},
					});
				},
				__(label),
				__('Print')
			);
		},
		__(group)
	);
};
