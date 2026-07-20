// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Shared label-printing helpers. Registered on the `bullwheel.printing` namespace
// rather than exported, because this bundle is loaded through `app_include_js` —
// DocType scripts have no way to import from it.

frappe.provide('bullwheel.printing');

const DEFAULT_BUTTON_GROUP = 'Print Labels';
const DEFAULT_PRINT_METHOD = 'bullwheel.label_printing.print_labels';
// Bucket name for frappe.model.user_settings — not a real DocType, just a per-user
// settings namespace, keyed by print media type so one remembered printer can serve
// every slot that shares that media (see show_print_dialog).
const PRINTER_SETTINGS_DOCTYPE = 'Label Printer';

// ── Items contract ──────────────────────────────────────────────────────────────
//
// `items` may be given as any of:
//   • omitted                                  → the form's own document (form buttons only)
//   • 'DOCNAME'                                → one item
//   • ['DOCNAME-A', 'DOCNAME-B']               → many items
//   • [{doctype?, name, quantity?, label?}]    → full form
//   • a (possibly async) callback returning any of the above; receives `frm`
//
// Per item: `doctype` defaults to the top-level `doctype` argument (which defaults
// to the form's / list view's own doctype); `quantity` defaults to 1 and is editable
// in the print dialog; `label` is display-only dialog text (defaults to `name`) and
// is never sent to the server.
//
// Wire format sent to the server:
//   {printer_name, slot, doctype, items: [{doctype?, name, quantity}]}
//
// Items on a Resolved doctype (one whose controller declares LABEL_RESOLUTION_FIELD)
// are followed to their Native document server-side — callers pass whatever
// identifiers are already in scope, with no extra round trips.

function resolve_value(source, frm, fallback) {
	// A target may be given as a plain value or as a callback, and a callback may
	// return a promise. This lets a caller whose target is not known until click
	// time — a selected grid row, for example — defer resolution instead of
	// capturing a stale value at refresh. An omitted target falls back to the
	// form's own document.
	if (source === undefined) {
		return Promise.resolve(fallback);
	}

	return Promise.resolve(typeof source === 'function' ? source(frm) : source);
}

function normalize_items(items) {
	// Accept every shape the items contract allows and return a uniform
	// [{doctype?, name, quantity, label}] array, dropping empty entries.
	if (!items) {
		return [];
	}
	if (!Array.isArray(items)) {
		items = [items];
	}

	return items
		.map((item) => {
			if (typeof item === 'string') {
				item = { name: item };
			}
			return item && item.name
				? {
						doctype: item.doctype,
						name: item.name,
						quantity: cint(item.quantity) || 1,
						label: item.label || item.name,
					}
				: null;
		})
		.filter(Boolean);
}

async function show_print_dialog({ title, items, slot, on_submit }) {
	// Ask which configured Label Printer to send to and let the user set a
	// per-item quantity. Deleting a row or setting its quantity to 0 both mean
	// "skip this item".
	const rows = items.map((item, index) => ({
		idx: index + 1,
		item_label: item.label,
		quantity: item.quantity,
		// Hidden keys ride along untouched: the grid hands back these same row
		// objects, so the doctype/name survive the user's quantity edits.
		doctype: item.doctype,
		docname: item.name,
	}));

	// The printer picker is filtered to the label's recommended media (when set)
	// plus enabled printers only, and pre-filled with the last printer the user
	// printed with for that media type — remembered per user, per media type,
	// since one physical printer often serves several slots that share a media
	// type (e.g. Ascend Tag and Warehouse Location are both Direct Thermal).
	const [recommended_media, saved_printers] = await Promise.all([
		frappe.call({ method: 'bullwheel.label_printing.get_recommended_print_media', args: { slot } })
			.then((response) => response.message),
		frappe.model.user_settings.get(PRINTER_SETTINGS_DOCTYPE),
	]);

	let selected_printer_info = null;
	let default_printer;
	const last_printer = recommended_media && saved_printers[recommended_media];
	if (last_printer) {
		const printer_info = await frappe.db.get_value('Label Printer', last_printer, ['disabled', 'type'])
			.then((response) => response.message);
		if (printer_info && !printer_info.disabled && printer_info.type === recommended_media) {
			default_printer = last_printer;
			selected_printer_info = printer_info;
		}
	}

	const dialog = new frappe.ui.Dialog({
		title: __(title),
		fields: [
			{
				label: __('Printer'),
				fieldname: 'printer',
				fieldtype: 'Link',
				options: 'Label Printer',
				reqd: 1,
				default: default_printer,
				get_query: () => ({
					filters: {
						disabled: 0,
						...(recommended_media ? { type: recommended_media } : {}),
					},
				}),
				async onchange() {
					const printer_name = this.get_value();
					if (!printer_name) {
						selected_printer_info = null;
						return;
					}
					selected_printer_info = await frappe.db
						.get_value('Label Printer', printer_name, ['disabled', 'type'])
						.then((response) => response.message);

					if (selected_printer_info.disabled) {
						frappe.show_alert({
							message: __('{0} is disabled and cannot be used for printing.', [printer_name]),
							indicator: 'orange',
						});
					} else if (recommended_media && selected_printer_info.type !== recommended_media) {
						frappe.show_alert({
							message: __('{0} is a {1} printer, but this label recommends {2}.', [
								printer_name,
								selected_printer_info.type,
								recommended_media,
							]),
							indicator: 'orange',
						});
					}
				},
			},
			{
				label: __('Items'),
				fieldname: 'items',
				fieldtype: 'Table',
				cannot_add_rows: true,
				in_place_edit: true,
				data: rows,
				get_data: () => rows,
				fields: [
					{
						label: __('Item'),
						fieldname: 'item_label',
						fieldtype: 'Data',
						in_list_view: 1,
						read_only: 1,
						columns: 7,
					},
					{
						label: __('Quantity'),
						fieldname: 'quantity',
						fieldtype: 'Int',
						in_list_view: 1,
						columns: 2,
						default: 1,
					},
				],
			},
		],
		primary_action_label: __('Print'),
		primary_action(values) {
			const printable_items = (values.items || [])
				.filter((row) => cint(row.quantity) > 0)
				.map((row) => ({
					doctype: row.doctype,
					name: row.docname,
					quantity: cint(row.quantity),
				}));

			if (!printable_items.length) {
				frappe.show_alert({
					message: __('Every item was removed or set to quantity 0 — nothing to print.'),
					indicator: 'orange',
				});
				return;
			}

			dialog.hide();
			// Fire-and-forget: remembering the choice for next time shouldn't delay
			// sending the print job.
			if (selected_printer_info && selected_printer_info.type) {
				frappe.model.user_settings.save(
					PRINTER_SETTINGS_DOCTYPE,
					selected_printer_info.type,
					values.printer
				);
			}
			on_submit(values.printer, printable_items);
		},
	});

	dialog.show();
}

function send_print_request({ method, printer_name, slot, doctype, items, label }) {
	// One call carries everything: the server resolves each item to its Native
	// document, renders the slot's Zebra Printer Label per item, and transmits.
	frappe.show_alert({ message: __('Sending {0}...', [__(label)]), indicator: 'blue' });
	frappe.call({
		method: method,
		args: {
			printer_name: printer_name,
			slot: slot,
			doctype: doctype,
			items: items,
		},
		callback() {
			frappe.show_alert({ message: __('{0} sent', [__(label)]), indicator: 'green' });
		},
	});
}

// Add a form button that renders the label configured for `slot` against the target
// items and sends it to a Label Printer chosen at click time.
//
//   frm           - the form the button is added to (required)
//   label         - button text, also used as the dialog title (required)
//   slot          - Bullwheel Settings ▸ Printing ▸ Labels slot, e.g. 'swap_tag' (required)
//   doctype       - default doctype for items that carry none; a value, or a callback
//                   returning one (or a promise for one). Defaults to the form's own
//                   DocType.
//   items         - the items to print, in any shape the items contract above allows.
//                   Defaults to the form's own document.
//   group         - custom button group. Defaults to 'Print Labels'.
//   empty_message - shown when a callback resolves no items, e.g. nothing selected.
//   method        - whitelisted server action to call. Defaults to
//                   'bullwheel.label_printing.print_labels'.
//
// A callback that resolves nothing is a normal outcome, not an error: the user is told
// via `empty_message` and nothing is printed.
bullwheel.printing.add_print_button = function ({
	frm,
	label,
	slot,
	doctype,
	items,
	group = DEFAULT_BUTTON_GROUP,
	empty_message,
	method = DEFAULT_PRINT_METHOD,
}) {
	frm.add_custom_button(
		__(label),
		async () => {
			const [target_doctype, target_items] = await Promise.all([
				resolve_value(doctype, frm, frm.doc.doctype),
				resolve_value(items, frm, frm.doc.name),
			]);

			const normalized_items = normalize_items(target_items);
			if (!normalized_items.length) {
				frappe.show_alert({
					message: empty_message || __('Select a document to print before printing {0}.', [__(label)]),
					indicator: 'orange',
				});
				return;
			}

			show_print_dialog({
				title: label,
				items: normalized_items,
				slot: slot,
				on_submit: (printer_name, printable_items) => {
					send_print_request({
						method: method,
						printer_name: printer_name,
						slot: slot,
						doctype: target_doctype,
						items: printable_items,
						label: label,
					});
				},
			});
		},
		__(group)
	);
};

// Add a list-view bulk action that prints the label configured for `slot` for every
// checked row. Registered in the Actions menu, which Frappe only shows while rows are
// checked — call this from the list view's onload:
//
//   frappe.listview_settings['Ascend Product'] = {
//       onload(listview) {
//           bullwheel.printing.add_list_print_button({
//               listview, label: 'Print Ascend Tag', slot: 'ascend_tag',
//           });
//       },
//   };
//
//   listview      - the list view the action is added to (required)
//   label         - menu item text, also used as the dialog title (required)
//   slot          - Bullwheel Settings ▸ Printing ▸ Labels slot (required)
//   doctype       - default doctype for the checked items. Defaults to the list
//                   view's own DocType.
//   empty_message - shown when no rows are checked.
//   method        - whitelisted server action to call. Defaults to
//                   'bullwheel.label_printing.print_labels'.
bullwheel.printing.add_list_print_button = function ({
	listview,
	label,
	slot,
	doctype,
	empty_message,
	method = DEFAULT_PRINT_METHOD,
}) {
	listview.page.add_actions_menu_item(
		__(label),
		() => {
			const checked_names = listview.get_checked_items(true);
			const normalized_items = normalize_items(checked_names);
			if (!normalized_items.length) {
				frappe.show_alert({
					message: empty_message || __('Select at least one row to print {0}.', [__(label)]),
					indicator: 'orange',
				});
				return;
			}

			show_print_dialog({
				title: label,
				items: normalized_items,
				slot: slot,
				on_submit: (printer_name, printable_items) => {
					send_print_request({
						method: method,
						printer_name: printer_name,
						slot: slot,
						doctype: doctype || listview.doctype,
						items: printable_items,
						label: label,
					});
				},
			});
		},
		false
	);
};
