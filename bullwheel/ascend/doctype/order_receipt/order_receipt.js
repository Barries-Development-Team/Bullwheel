// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Per-table config for the Add/Edit/Remove buttons on Order Receipt child tables. Each
// entry drives a DocType-defined dialog plus a queued, serialized update of that table.
const TABLE_CONFIGS = {
	order_items: {
		table: 'order_items',
		child_doctype: 'Order Receipt Item',
		noun: 'Order Item',
		// Scope the vpn Link to this receipt's vendor. Vendor Product records carry a
		// `vendor` link (Vendor.Name) and are named "<part number> (<vendor>)".
		customize_field: (frm, field, job) => {
			if (field.fieldname === 'vpn') {
				field.get_query = () => ({filters: {vendor: frm.doc.vendor}});
				if (job === 'edit') field.read_only = 1;
			}
			if (field.fieldname === 'received' && job === 'add') {
				field.hidden = 1;
			}
		}
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
function dialog_fields(frm, config, job) {
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
			if (config.customize_field) config.customize_field(frm, field, job);
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
			fields: dialog_fields(frm, config, job),
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

	if (frm.fields_dict.order_status.value == "Received") { return }
	
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

// ── Label printing ─────────────────────────────────────────────────────────────

// Map the selected order-item rows to print items. Each row's `vpn` (a Vendor Product
// docname) is already in scope, so the client passes it straight through and the server
// resolves the rest (Vendor Product → product → Ascend Product) — no per-row round trips.
function selected_order_items(frm) {
	return frm.fields_dict.order_items.grid
		.get_selected_children()
		.filter((row) => row.vpn)
		.map((row) => ({
			doctype: 'Vendor Product',
			name: row.vpn,
			quantity: 1,
			label: row.description || row.vpn,
		}));
}

function add_product_print_buttons(frm) {
	const tags = [
		{ label: 'Print Swap Tag', slot: 'swap_tag' },
		{ label: 'Print Ascend Tag', slot: 'ascend_tag' },
		{ label: 'Print Online Tag', slot: 'online_tag' },
	];

	tags.forEach(({ label, slot }) => {
		bullwheel.printing.add_print_button({
			frm: frm,
			label: label,
			slot: slot,
			items: selected_order_items,
			empty_message: __('Select one or more order items to print tags for.'),
		});
	});
}

// ── Scan flow ──────────────────────────────────────────────────────────────────
// All scan mutations route through the serialized queue (like the buttons), so the
// grids stay read-only and concurrent scans from multiple users can't lose updates.

// Add or increment an order item. The server-side upsert (match on vpn) keeps
// rapid/concurrent scans correct regardless of the form's on-screen state. description/upc
// come from the caller (scan_item, or a just-created Vendor Product/New Product) so the
// server snapshots them without a re-query.
function queue_add_or_increment_item(frm, vpn, cost, description, upc) {
	frappe.call('bullwheel.ascend.doctype.order_receipt.order_receipt.queue_add_or_increment_item', {
		docname: frm.doc.name,
		vpn: vpn,
		cost: cost,
		description: description,
		upc: upc
	}).then(() => frappe.show_alert({
		message: __('Added: {0}', [frappe.utils.escape_html(vpn)]),
		indicator: 'green'
	}));
}

// 'product found': Ascend already has this product, but the receipt's vendor has no Vendor
// Product on file for it yet. A minimal dialog collects just the part number (VPN) and cost
// needed to create that Vendor Product; the server inserts it into Ascend and, on success,
// adds/increments the matching order item. Runs synchronously (not via the queue) so an
// Ascend insert failure is reported back into this dialog instead of failing silently in a
// background job.
async function open_vendor_link_dialog(frm, record) {

	const generated_vpn_response = await frappe.call('bullwheel.ascend.doctype.vendor_product.vendor_product.generate_vpn', {
		vendor_id: frm.doc.cached_vendor_id,
		vpn_prefix: frm.doc.vpn_prefix,
		brand: record.brand,
		model: record.style_name,
		size: record.size,
		color: record.color
	});
	const generated_vpn = generated_vpn_response.message;

	const dialog = new frappe.ui.Dialog({
		title: __('Link Vendor Product'),
		fields: [
			{fieldname: 'description', label: __('Description'), fieldtype: 'Data', read_only: 1, default: record.description},
			{fieldname: 'part_number', label: __('Part Number (VPN)'), fieldtype: 'Data', reqd: 1, default: generated_vpn },
			{fieldname: 'cost', label: __('Cost'), fieldtype: 'Currency', reqd: 1}
		],
		primary_action_label: __('Link & Add'),
		primary_action: (values) => {
			frappe.call('bullwheel.ascend.doctype.order_receipt.order_receipt.link_vendor_product', {
				docname: frm.doc.name,
				product_id: record.product_id,
				part_number: values.part_number,
				cost: values.cost,
				description: record.description,
				upc: record.upc
			}).then((response) => {
				dialog.hide();
				frappe.show_alert({
					message: __('Added: {0}', [frappe.utils.escape_html(response.message)]),
					indicator: 'green'
				});
			});
			// Left open on failure: frappe.call already surfaced the server error.
		}
	});
	dialog.show();
}

// 'not found': nothing in Ascend matches the scanned identifier. Opens the full New Product
// form inside a modal (bullwheel.forms.open_form_dialog) rather than Quick Entry — the real
// Form runs the doctype's client scripts, so live description regeneration works during
// receiving, and the after-insert callback fires on save no matter how the user saves (the
// old Quick Entry path lost the callback if the user clicked "Edit Full Form"). The scanned
// value, this receipt's vendor, and this receipt's vpn_prefix are seeded onto the document
// before the modal opens (vpn_prefix is a hidden field, never rendered) — New Product's own
// insert hooks (see new_product.py) generate the Vendor Part Number, create the Ascend
// Product, and, since vendor is set, the linked Vendor Product. Vendor is visible by default
// on New Product, but this flow sets it automatically from the receipt, so
// __created_via_order_receipt (a client-only property, never persisted — see new_product.json's
// vendor field) hides it specifically for this flow rather than for manual vendor entry.
function open_new_product_form_dialog(frm, scanned_value) {
	frappe.model.with_doctype('New Product', () => {
		const seed_document = frappe.model.get_new_doc('New Product');
		seed_document.upc = scanned_value;
		seed_document.vendor = frm.doc.vendor;
		seed_document.vpn_prefix = frm.doc.vpn_prefix;
		seed_document.__created_via_order_receipt = 1;

		bullwheel.forms.open_form_dialog('New Product', {
			seed_document: seed_document,
			after_insert(new_product) {
				queue_add_or_increment_item(
					frm,
					`${new_product.vpn} (${frm.doc.vendor})`, // matches VendorProduct.NAME_EXPRESSION
					new_product.estimated_cost,
					new_product.description,
					new_product.upc
				);
			},
		});
	});
}

// Dispatch a scanned identifier: resolve it via scan_item, then route the result through the
// serialized queue (add/increment an order item), the vendor-link dialog, or the New Product
// form dialog.
function handle_scan(frm, scanned_value) {
	frappe.call('bullwheel.ascend.doctype.order_receipt.order_receipt.scan_item', {
		id: scanned_value,
		vendor: frm.doc.vendor,
		cached_vendor_id: frm.doc.cached_vendor_id,
		docname: frm.doc.name
	}).then((response) => {
		const [status, record] = response.message || [];

		if (status === 'vpn found') {
			// record.vpn is the Vendor Product's docname, e.g. "12345 (Specialized)".
			queue_add_or_increment_item(frm, record.vpn, record.cost, record.description, record.upc);
		} else if (status === 'product found') {
			// Ascend has this product, but this vendor has no Vendor Product on file yet.
			open_vendor_link_dialog(frm, record);
		} else {
			// No record of this item anywhere — confirm before creating one from scratch.
			frappe.confirm(
				`No product found for "${frappe.utils.escape_html(scanned_value)}". Create a new product record?`,
				() => open_new_product_form_dialog(frm, scanned_value)
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

// On a new receipt's first save, prompt for the vpn_prefix acronym (used later when
// generating VPNs for products on this order) instead of silently defaulting it. Suggests
// an acronym derived from the selected vendor's name but lets the user override it. Returns
// a Promise so before_save's caller (frappe.run_serially) awaits the dialog before the
// mandatory-field check and the actual save proceed.
function prompt_vpn_prefix(frm) {
	return new Promise((resolve, reject) => {
		let confirmed = false;

		const dialog = new frappe.ui.Dialog({
			title: __('Confirm VPN Prefix'),
			fields: [
				{
					fieldname: 'vpn_prefix',
					label: __('VPN Prefix'),
					description: 'This value will be prepended to new vendor part numbers.',
					fieldtype: 'Data',
					reqd: 1,
					default: bullwheel.ascend.generate_vendor_acronym(frm.doc.vendor)
				}
			],
			primary_action_label: __('Confirm'),
			primary_action: (values) => {
				// Ensure prefix is not empty.
				const vpn_prefix = (values.vpn_prefix || '').trim();
				if (!vpn_prefix) {
					dialog.set_df_property('vpn_prefix', 'description', __('VPN Prefix cannot be empty.'));
					return;
				}

				confirmed = true;
				frm.set_value('vpn_prefix', vpn_prefix);
				dialog.hide();
				resolve();
			},
			// Closed (Escape / backdrop) without confirming: block the save rather than
			// silently proceeding with no prefix.
			onhide: () => {
				if (!confirmed) {
					frappe.validated = false;
					reject();
				}
			}
		});

		dialog.show();
	});
}

frappe.ui.form.on("Order Receipt", {
	before_save(frm) {
		// Vendor is itself a required field: if it's missing, let the normal mandatory-field
		// check (which runs right after before_save) report that instead of prompting here.
		if (frm.is_new() && frm.doc.vendor) return prompt_vpn_prefix(frm);
	},
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
								After exporting the received batch, a single "PO" spreadsheet will be downloaded to your computer, containing VPN, Cost, and Quantity data for the Order. New and vendor-linked products are created directly in Ascend during receiving, so there is no separate Vendor Products sheet to import.
								<div style='margin-top: 20px;'></div>
								<b>Order Import Steps</b><br>
								1. Open Orders from either the Ascend Desktop or the Database Explorer.<br>
								2. Add a new order.<br>
								3. Select the vendor associated with the order.<br>
								4. In the PO Number field, enter the vendor name, PO number, and the batch number. (e.g. Jackson Base Camp June 2026 Demo Batch 1)<br>
								5. Select File > Import from Excel...<br>
								6. In the File Explorer, navigate to and select the downloaded "PO" spreadsheet.<br>
								7. Check the (Select All) box, and hit OK.<br>
								8. Select Check > All.<br>
								9. Save the order and, if provided, enter the invoice number when prompted.
						`)
				});
			},__("Receiving"));

			frm.add_custom_button(__('Open Product'), () => {
				const rows = frm.fields_dict.order_items.grid.get_selected_children();
				if (rows.length !== 1) {
					frappe.msgprint(__('Select exactly one item to open.'));
					return;
				}

				vpn = rows[0].vpn
				frappe.show_alert('Loading Product...', 5)
				frappe.db.get_value('Vendor Product', vpn, 'product').then(response => {
					window.open(`/desk/ascend-product/${response.message.product}`,'_blank');
 				})	
			})

			add_product_print_buttons(frm);
			show_table_buttons(frm, TABLE_CONFIGS.order_items);
			setup_scan_box(frm);

			// Hides tag element in the sidebar
			$('.form-tags').hide();
			$('.tags-label').hide();
    	}
	},
});
