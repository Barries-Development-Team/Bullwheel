// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Per-table config for the Add/Edit/Remove buttons on Order Receipt child tables. Each
// entry drives a DocType-defined dialog plus a queued, serialized update of that table.
const TABLE_CONFIGS = {
	order_items: {
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
	new_products: {
		table: 'new_products',
		child_doctype: 'New Product',
		noun: 'New Product'
	}
};

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
				mandatory_depends_on: df.mandatory_depends_on,
				description: df.description
			};
			if (config.customize_field) config.customize_field(frm, field);
			return field;
		});
}

// Open the Add/Edit dialog for a child table.
//   row       - for edit: prefills the fields and targets the queued update by its name.
//   prefill   - {fieldname: value} to seed an add dialog (used by the scan flow).
//   on_submit - custom submit handler(values); defaults to a queued add/edit of this table.
function open_dialog(frm, config, {job, row = null, prefill = null, on_submit = null}) {
	frappe.model.with_doctype(config.child_doctype, () => {
		const dialog = new frappe.ui.Dialog({
			title: job === 'add' ? __('Add {0}', [config.noun]) : __('Edit {0}', [config.noun]),
			fields: dialog_fields(frm, config),
			primary_action_label: job === 'add' ? __('Add') : __('Save'),
			primary_action: (values) => {
				// get_values() returns null when a required field is missing; it has
				// already flagged the field, so just stay open for the user to fix it.
				if (!values) return;
				if (on_submit) {
					on_submit(values);
				} else {
					queue_update(frm, config, job, values, row ? row.name : null);
				}
				dialog.hide();
			}
		});

		const seed = row
			? Object.fromEntries(editable_fieldnames(config.child_doctype).map((field) => [field, row[field]]))
			: (prefill || {});
		Object.keys(seed).forEach((field) => {
			if (seed[field] != null) dialog.set_value(field, seed[field]);
		});

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
function show_table_buttons(frm, config) {
	make_grid_selectable_only(frm, config);

	frm.add_custom_button(__(`Add ${config.noun}`), () => open_dialog(frm, config, {job: 'add'}));
	frm.add_custom_button(__(`Edit ${config.noun}`), () => {
		const rows = frm.fields_dict[config.table].grid.get_selected_children();
		if (rows.length !== 1) {
			frappe.msgprint(__('Select exactly one {0} to edit.', [config.noun.toLowerCase()]));
			return;
		}
		open_dialog(frm, config, {job: 'edit', row: rows[0]});
	});
	frm.add_custom_button(__(`Remove ${config.noun}`), () => {
		const rows = frm.fields_dict[config.table].grid.get_selected_children();
		if (!rows.length) {
			frappe.msgprint(__('Select at least one {0} to remove.', [config.noun.toLowerCase()]));
			return;
		}
		frappe.confirm(__('Remove {0} selected {1}(s)?', [rows.length, config.noun.toLowerCase()]), () => {
			rows.forEach((row) => queue_update(frm, config, 'remove', {}, row.name));
		});
	});
}

function hide_table_buttons(frm, config) {
	frm.remove_custom_button(__(`Add ${config.noun}`));
	frm.remove_custom_button(__(`Edit ${config.noun}`));
	frm.remove_custom_button(__(`Remove ${config.noun}`));
}

function update_table_buttons(frm) {
	if (frm.get_active_tab().id === "order-receipt-new_products_tab") {
		show_table_buttons(frm, TABLE_CONFIGS.new_products);
		hide_table_buttons(frm, TABLE_CONFIGS.order_items);
	} else {
		show_table_buttons(frm, TABLE_CONFIGS.order_items);
		hide_table_buttons(frm, TABLE_CONFIGS.new_products);
	}
}


// ── Scan flow ──────────────────────────────────────────────────────────────────
// All scan mutations route through the serialized queue (like the buttons), so the
// grids stay read-only and concurrent scans from multiple users can't lose updates.

// Add or increment an order item. The server-side upsert (match on item_type + vpn)
// keeps rapid/concurrent scans correct regardless of the form's on-screen state.
// description/upc come from scan_item so the server snapshots them without a re-query.
function queue_add_or_increment_item(frm, item_type, vpn, cost, description, upc) {
	frappe.call('bullwheel.ascend.doctype.order_receipt.order_receipt.queue_add_or_increment_item', {
		docname: frm.doc.name,
		item_type: item_type,
		vpn: vpn,
		cost: cost,
		description: description,
		upc: upc
	}).then(() => frappe.show_alert({
		message: __('Added: {0}', [frappe.utils.escape_html(vpn)]),
		indicator: 'green'
	}));
}

// Stage a New Product (+ a linked order item) via the queue.
function queue_stage_new_product(frm, values) {
	const clean = {};
	editable_fieldnames('New Product').forEach((field) => (clean[field] = values[field]));

	frappe.call('bullwheel.ascend.doctype.order_receipt.order_receipt.queue_stage_new_product', {
		docname: frm.doc.name,
		values: JSON.stringify(clean)
	}).then(() => frappe.show_alert({message: __('New product staged'), indicator: 'orange'}));
}

// Prompt-on-scan: open the New Product dialog prefilled from the scan so the user can
// complete the required fields, then stage the product and link an order item.
function open_new_product_from_scan(frm, prefill) {
	const config = TABLE_CONFIGS.find((c) => c.table === 'new_products');
	open_dialog(frm, config, {
		job: 'add',
		prefill: prefill,
		on_submit: (values) => queue_stage_new_product(frm, values)
	});
}

// Dispatch a scanned identifier: resolve it via scan_item, then route the result through the
// serialized queue (add/increment an order item, or prompt for a new product).
function handle_scan(frm, scanned_value) {
	frappe.call('bullwheel.ascend.doctype.order_receipt.order_receipt.scan_item', {
		id: scanned_value,
		vendor: frm.doc.vendor,
		docname: frm.doc.name
	}).then((response) => {
		const [status, record] = response.message || [];

		if (status === 'new product found') {
			// Already staged as a New Product on this order — add/increment the
			// order item that references it (record.name is the New Product row).
			queue_add_or_increment_item(frm, 'New Product', record.name, record.cost, record.description, record.upc);
		} else if (status === 'vpn found') {
			// record.vpn is the Vendor Product's docname, e.g. "12345 (Specialized)".
			queue_add_or_increment_item(frm, 'Vendor Product', record.vpn, record.cost, record.description, record.upc);
		} else if (status === 'product found') {
			// Ascend has this product, but this vendor has no Vendor Product on file yet —
			// collect the New Product details, then stage it + link an order item.
			open_new_product_from_scan(frm, {
				upc: record.upc,
				description: record.description,
				cost: record.cost
			});
		} else {
			// No record of this item anywhere — confirm before creating one from scratch.
			frappe.confirm(
				`No product found for "${frappe.utils.escape_html(scanned_value)}". Create a new product record?`,
				() => open_new_product_from_scan(frm, {upc: scanned_value})
			);
		}
	});
}

// Mount the scan box as a standalone control (no frm/doc) inside the scan_item HTML field, so
// typing/scanning never writes to frm.doc and never marks the form dirty — a dirty form would
// suppress the realtime auto-refresh. Frappe re-renders the HTML field on every form refresh,
// so we re-mount the control here each time.
function setup_scan_box(frm) {
	const field = frm.get_field('scan_item');
	if (!field) return;

	field.$wrapper.empty();
	const control = frappe.ui.form.make_control({
		df: {
			fieldtype: 'Data',
			fieldname: 'scan_item',
			label: __('Scan Item'),
			options: 'Barcode',
			placeholder: __('Scan here')
		},
		parent: field.$wrapper,
		render_input: true
	});
	control.refresh();

	// Read/clear the raw input directly; the value stays out of frm.doc entirely.
	control.$input.on('keydown', (event) => {
		if (event.key !== 'Enter') return;
		event.preventDefault();

		const scanned_value = (control.$input.val() || '').trim();
		if (!scanned_value) return;

		control.$input.val('');
		handle_scan(frm, scanned_value);
	});
}

frappe.ui.form.on("Order Receipt", {
 	refresh(frm) {
		if (!frm.is_new()) {
			// Regenerates the buttons so that the receiving actions are always before the table actions.
			frm.clear_custom_buttons(); 
			frm.add_custom_button(__('Export Received Batch'), () => {
				frappe.confirm(`This task should only be performed by a member of the Receiving Team.<br>
								All unreceived items will be marked as received. Do you wish to continue?<br>
								For more information, select "Import Instructions".`,
					() => { // Yes
						const url = '/api/method/bullwheel.ascend.doctype.order_receipt.order_receipt.export_received_batch'
							+ '?docname=' + encodeURIComponent(frm.doc.name);
						window.open(url);
					}, () => { // No
						return
				})
        	},__("Receiving"));

			frm.add_custom_button(__('Import Instructions'), () => {
				frappe.msgprint({
					title: __('Ascend Order Import Instructions'),
					indicator: 'green',
					message: __(`Note: This task should be performed by a member of the Receiving Team.
								<div style='margin-top: 20px;'></div>
								After exporting the received batch, a single .zip file will be downloaded to your computer containing two spreadsheets; a "PO" and a "Products" sheet. Extract both spreadsheets from the .zip before continuing. The "PO" sheet contains VPN, Cost, and Quantity data for the Order, while the "Product" sheet contains the new Vendor Product data. <b>The Vendor Product data must be imported before the Order is created!</b>
								<div style='margin-top: 20px;'></div>
								<b>Vendor Product Import Steps</b><br>
								1. While on the Ascend Desktop, select File > Import > Vendor Products...<br>
								2. In the File Explorer, navigate to and select the extracted spreadsheet with the "Products" prefix.<br>
								3. Select the vendor associated with the order.<br>
								4. Check the (Select All) box, and hit OK.
								<div style='margin-top: 20px;'></div>
								<b>Order Import Steps</b><br>
								1. Open Orders from either the Ascend Desktop or the Database Explorer.<br>
								2. Add a new order.<br>
								3. Select the vendor associated with the order.<br>
								4. In the PO Number field, enter the vendor name, PO number, and the batch number. (e.g. Jackson Base Camp June 2026 Demo Batch 1)<br>
								5. Select File > Import from Excel...<br>
								6. In the File Explorer, navigate to and select the extracted spreadsheet with the "PO" prefix.<br>
								7. Check the (Select All) box, and hit OK.<br>
								8. Select Check > All.<br>
								9. Save the order and, if provided, enter the invoice number when prompted.
						`)
				});
			},__("Receiving"));

			update_table_buttons(frm);
			setup_scan_box(frm);
			
			// Hides tag element in the sidebar
			$('.form-tags').hide();
			$('.tags-label').hide();
    	}
	},
	// Reveal only the button group for the table on the newly-active tab.
	on_tab_change(frm) {
		if (!frm.is_new()) {
			update_table_buttons(frm);
		}
	},
});