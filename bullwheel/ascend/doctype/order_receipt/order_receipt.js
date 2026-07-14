// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Per-table config for the Add/Edit/Remove buttons on Order Receipt child tables. Each
// entry drives a DocType-defined dialog plus a queued, serialized update of that table.
const TABLE_CONFIGS = [
	{
		table: 'order_items',
		child_doctype: 'Order Receipt Item',
		noun: 'Order Item',
		// Scope the vpn Dynamic Link to this receipt's vendor. Vendor Product records carry
		// a `vendor` link (Vendor.Name) and are named "<vpn> (<vendor>)"; New Product rows
		// have no vendor, so no filter is applied for that item type.
		customize_field: (frm, field) => {
			if (field.fieldname === 'vpn') {
				field.get_query = () => {
					const item_type = cur_dialog && cur_dialog.get_value('item_type');
					if (item_type === 'Vendor Product' && frm.doc.vendor) {
						return {filters: {vendor: frm.doc.vendor}};
					}
					return {};
				};
			}
		}
	},
	{
		table: 'new_products',
		child_doctype: 'New Product',
		noun: 'New Product'
	}
];

// A child field is editable through the dialog/queue when it is writable, non-virtual, and
// value-bearing. Mirrors writable_fieldnames() in order_receipt.py.
function is_editable_field(df) {
	return !df.read_only && !df.is_virtual && !frappe.model.no_value_type.includes(df.fieldtype);
}

// Fieldnames of a child DocType that the dialog edits and the queue writes.
function editable_fieldnames(child_doctype) {
	return frappe.get_meta(child_doctype).fields.filter(is_editable_field).map((df) => df.fieldname);
}

// Route one add/edit/remove for a child table through the serialized job. The job's
// doc.save() publishes doc_update, which auto-refreshes this (non-dirty) form — so there
// is no manual reload here.
function queue_update(frm, config, job, doc, row_name = null) {
	const values = {};
	editable_fieldnames(config.child_doctype).forEach((field) => (values[field] = doc[field]));

	frappe.call('bullwheel.ascend.doctype.order_receipt.order_receipt.queue_update_table', {
		docname: frm.doc.name,
		table: config.table,
		job: job,
		values: JSON.stringify(values),
		row_name: row_name
	}).then(() => frappe.show_alert({message: __('Queued'), indicator: 'blue'}));
}

// Build the Add/Edit dialog field list from the child DocType so the form stays driven by
// the DocType definition rather than a hardcoded list. Per-table customize_field hooks can
// adjust individual fields (e.g. the vpn vendor filter for order items).
function dialog_fields(frm, config) {
	return frappe.get_meta(config.child_doctype).fields
		.filter(is_editable_field)
		.map((df) => {
			const field = {
				fieldname: df.fieldname,
				label: df.label,
				fieldtype: df.fieldtype,
				options: df.options,
				reqd: df.reqd,
				default: df.default,
				depends_on: df.depends_on,
				mandatory_depends_on: df.mandatory_depends_on
			};
			if (config.customize_field) config.customize_field(frm, field);
			return field;
		});
}

// Open the Add/Edit dialog for a child table. For edit, `row` prefills the fields and its
// name targets the queued update.
function open_dialog(frm, config, job, row = null) {
	frappe.model.with_doctype(config.child_doctype, () => {
		const dialog = new frappe.ui.Dialog({
			title: job === 'add' ? __('Add {0}', [config.noun]) : __('Edit {0}', [config.noun]),
			fields: dialog_fields(frm, config),
			primary_action_label: job === 'add' ? __('Add') : __('Save'),
			primary_action: (values) => {
				// get_values() returns null when a required field is missing; it has
				// already flagged the field, so just stay open for the user to fix it.
				if (!values) return;
				queue_update(frm, config, job, values, row ? row.name : null);
				dialog.hide();
			}
		});

		if (row) {
			editable_fieldnames(config.child_doctype).forEach((field) => {
				if (row[field] != null) dialog.set_value(field, row[field]);
			});
		}

		dialog.show();
	});
}

// A child grid is selectable (for Edit/Remove) but not directly editable: every mutation
// must go through the queue so concurrent edits stay serialized.
function make_grid_selectable_only(frm, config) {
	const grid = frm.fields_dict[config.table].grid;
	grid.cannot_add_rows = true;
	// Set the flags on the field df too: the "Add row" and "Duplicate rows" selection
	// actions gate on df.cannot_add_rows (grid.js refresh_duplicate_rows_button ignores
	// the grid-instance flag), and "Delete" gates on df.cannot_delete_rows.
	grid.df.cannot_add_rows = true;
	grid.df.cannot_delete_rows = true;
	editable_fieldnames(config.child_doctype).forEach((field) => grid.toggle_enable(field, false));
	grid.refresh();
}

// Wire the Add/Edit/Remove buttons and grid locking for one child table. Buttons are
// grouped into a "<noun>" dropdown (frm.add_custom_button's 3rd arg) so each table gets
// one toolbar entry instead of three flat buttons.
function setup_table_buttons(frm, config) {
	make_grid_selectable_only(frm, config);

	const group = config.noun;

	frm.add_custom_button(__('Add'), () => open_dialog(frm, config, 'add'), group);
	frm.add_custom_button(__('Edit'), () => {
		const rows = frm.fields_dict[config.table].grid.get_selected_children();
		if (rows.length !== 1) {
			frappe.msgprint(__('Select exactly one {0} to edit.', [config.noun.toLowerCase()]));
			return;
		}
		open_dialog(frm, config, 'edit', rows[0]);
	}, group);
	frm.add_custom_button(__('Remove'), () => {
		const rows = frm.fields_dict[config.table].grid.get_selected_children();
		if (!rows.length) {
			frappe.msgprint(__('Select at least one {0} to remove.', [config.noun.toLowerCase()]));
			return;
		}
		frappe.confirm(__('Remove {0} selected {1}(s)?', [rows.length, config.noun.toLowerCase()]), () => {
			rows.forEach((row) => queue_update(frm, config, 'remove', {}, row.name));
		});
	}, group);
}

frappe.ui.form.on("Order Receipt", {
 	refresh(frm) {

		if (!frm.is_new()) {
			TABLE_CONFIGS.forEach((config) => setup_table_buttons(frm, config));
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
