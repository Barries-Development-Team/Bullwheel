// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Fields of Order Receipt Item that we round-trip through the edit dialog and the
// queued update job. Must mirror EDITABLE_ITEM_FIELDS in order_receipt.py.
const ITEM_FIELDS = ['item_type', 'vpn', 'quantity', 'cost', 'received', 'comments'];

// Route one add/edit/remove for the order_items table through the serialized job.
// The job's doc.save() publishes doc_update, which auto-refreshes this (non-dirty)
// form — so there is no manual reload here.
function queue_item_update(frm, job, doc, row_name = null) {
	const values = {};
	ITEM_FIELDS.forEach((field) => (values[field] = doc[field]));

	frappe.call('bullwheel.ascend.doctype.order_receipt.order_receipt.queue_update_table', {
		docname: frm.doc.name,
		table: 'order_items',
		job: job,
		values: JSON.stringify(values),
		row_name: row_name
	}).then(() => frappe.show_alert({message: __('Queued'), indicator: 'blue'}));
}

// Build the Add/Edit dialog field list from the Order Receipt Item DocType so the form
// stays driven by the DocType definition rather than a hardcoded list. Uses the same
// visibility rule as Quick Entry: show fields that are reqd or allow_in_quick_entry, and
// skip read-only, virtual, and layout fields (so description/upc are excluded).
function item_dialog_fields(frm) {
	const layout_types = ['Section Break', 'Column Break', 'Tab Break', 'HTML'];
	return frappe.get_meta('Order Receipt Item').fields
		.filter((df) =>
			(df.reqd || df.allow_in_quick_entry) &&
			!df.read_only && !df.is_virtual &&
			!layout_types.includes(df.fieldtype)
		)
		.map((df) => {
			const field = {
				fieldname: df.fieldname,
				label: df.label,
				fieldtype: df.fieldtype,
				options: df.options,
				reqd: df.reqd,
				default: df.default
			};
			if (df.fieldname === 'vpn') {
				// Scope Vendor Product suggestions to this receipt's vendor. Vendor Product
				// records carry a `vendor` link (Vendor.Name), and their name is formatted
				// "<vpn> (<vendor>)". New Product rows have no vendor, so no filter applies
				// for that item type.
				field.get_query = () => {
					const item_type = cur_dialog && cur_dialog.get_value('item_type');
					if (item_type === 'Vendor Product' && frm.doc.vendor) {
						return {filters: {vendor: frm.doc.vendor}};
					}
					return {};
				};
			}
			return field;
		});
}

// Open the Add/Edit item dialog. For edit, `row` prefills the fields and its name targets
// the queued update. The vpn Dynamic Link resolves its target DocType from the in-dialog
// item_type (Frappe's dialog handling reads sibling values via cur_dialog).
function open_item_dialog(frm, job, row = null) {
	frappe.model.with_doctype('Order Receipt Item', () => {
		const dialog = new frappe.ui.Dialog({
			title: job === 'add' ? __('Add Item') : __('Edit Item'),
			fields: item_dialog_fields(frm),
			primary_action_label: job === 'add' ? __('Add') : __('Save'),
			primary_action: (values) => {
				// get_values() returns null when a required field is missing; it has
				// already flagged the field, so just stay open for the user to fix it.
				if (!values) return;
				queue_item_update(frm, job, values, row ? row.name : null);
				dialog.hide();
			}
		});

		if (row) {
			// item_type is set before vpn (ITEM_FIELDS order) so the Dynamic Link
			// target is known when its value is applied.
			ITEM_FIELDS.forEach((field) => {
				if (row[field] != null) dialog.set_value(field, row[field]);
			});
		}

		dialog.show();
	});
}

// The order_items grid is selectable (for Edit/Remove) but not directly editable:
// every mutation must go through the queue so concurrent edits stay serialized.
function make_grid_selectable_only(frm) {
	const grid = frm.fields_dict.order_items.grid;
	grid.cannot_add_rows = true;
	// Set the flags on the field df too: the "Add row" and "Duplicate rows" selection
	// actions gate on df.cannot_add_rows (grid.js refresh_duplicate_rows_button ignores
	// the grid-instance flag), and "Delete" gates on df.cannot_delete_rows.
	grid.df.cannot_add_rows = true;
	grid.df.cannot_delete_rows = true;
	ITEM_FIELDS.forEach((field) => grid.toggle_enable(field, false));
	grid.refresh();
}

frappe.ui.form.on("Order Receipt", {
 	refresh(frm) {

		if (!frm.is_new()) {
			make_grid_selectable_only(frm);

			frm.add_custom_button("Add Item", () => open_item_dialog(frm, 'add'));
			frm.add_custom_button("Edit Item", () => {
				const rows = frm.fields_dict.order_items.grid.get_selected_children();
				if (rows.length !== 1) {
					frappe.msgprint(__('Select exactly one item to edit.'));
					return;
				}
				open_item_dialog(frm, 'edit', rows[0]);
			});
			frm.add_custom_button("Remove Item", () => {
				const rows = frm.fields_dict.order_items.grid.get_selected_children();
				if (!rows.length) {
					frappe.msgprint(__('Select at least one item to remove.'));
					return;
				}

				frappe.confirm(__('Remove {0} selected item(s)?', [rows.length]), () => {
					rows.forEach((row) => queue_item_update(frm, 'remove', {}, row.name));
				});
			});
		}


        $(frm.wrapper)
			.off('keydown.scan')
			.on('keydown.scan', '[data-fieldname="add_item"] input', function (event) {
				if (event.key !== 'Enter') return;
				event.preventDefault();

				// Read straight from the input element. A Frappe Data field only
				// syncs into frm.doc on its change event (blur/debounce), which has
				// not fired yet when Enter is pressed mid-typing — so frm.doc.add_item
				// would be stale and the scan would appear to be missed.
				const input = event.target;
				const scanned_value = (input.value || '').trim();
				if (!scanned_value) return;

				// Clear the input immediately so the user can scan the next item
				// without waiting on the server round-trip, and keep the model in sync.
				$(input).val('');
				frm.doc.add_item = '';

				frappe.call('bullwheel.ascend.doctype.order_receipt.order_receipt.scan_item', {
					id: scanned_value,
					vendor: frm.doc.vendor
				}).then((response) => {
					const [status, record] = response.message || [];

					if (status === 'vpn found') {
						// record.vpn is the Vendor Product's docname, e.g. "12345 (Specialized)".
						const existing_row = (frm.doc.order_items || []).find(
							row => row.item_type === 'Vendor Product' && row.vpn === record.vpn
						);

						if (existing_row) {
							frappe.model.set_value(existing_row.doctype, existing_row.name, 'quantity', existing_row.quantity + 1);
						} else {
							frm.add_child('order_items', {
								item_type: 'Vendor Product',
								vpn: record.vpn,
								description: record.description,
								upc: record.upc,
								quantity: 1,
								cost: record.cost
							});
						}
						frm.refresh_field('order_items');
						frappe.show_alert({
							message: `Added: ${frappe.utils.escape_html(record.vpn)}`,
							indicator: 'green'
						});
					} else if (status === 'product found') {
						// Ascend has this product, but this vendor has no Vendor Product
						// on file for it yet — stage a New Product entry to record the
						// new vendor association.
						stage_new_product(frm, {
							upc: record.upc,
							description: record.description,
							comments: 'Existing product receiving a new vendor product association.'
						});
					} else {
						// No record of this item anywhere — confirm before creating one from scratch.
						frappe.confirm(
							`No product found for "${frappe.utils.escape_html(scanned_value)}". Create a new product record?`,
							() => stage_new_product(frm, {
								upc: scanned_value,
								description: null,
								comments: 'New product — no existing record found.'
							})
						);
					}
				});
			});
 	},
});

function stage_new_product(frm, {upc, description, comments}) {
	// Every "New Product" entry needs a placeholder VPN since it has no
	// Vendor Product on file yet; the real one is filled in during review.
	const new_product_row = frm.add_child('new_products', {
		vpn: frappe.utils.get_random(10),
		upc: upc,
		description: description
	});
	frm.refresh_field('new_products');

	// Link the order item back to the New Product row we just staged.
	frm.add_child('order_items', {
		item_type: 'New Product',
		vpn: new_product_row.name,
		quantity: 1,
		comments: comments
	});
	frm.refresh_field('order_items');

	frappe.show_alert({
		message: `New product staged for: ${frappe.utils.escape_html(upc)}`,
		indicator: 'orange'
	});
}
