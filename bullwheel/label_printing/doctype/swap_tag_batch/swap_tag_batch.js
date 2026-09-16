// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Resolve a scanned identifier to an Ascend Product and add/increment its inventory row.
function handle_scan(frm, scanned_value) {
	frappe.call({
		method: 'bullwheel.ascend.doctype.ascend_product.ascend_product.get_values',
		args: {name: scanned_value, fields: ['name', 'description', 'upc']},
		callback(response) {
			const product = response.message;
			// get_values returns the product record (truthy object) when found,
			// or null when no product matches the scan.
			if (!product) {
				frappe.show_alert({
					message: `No product found for: ${frappe.utils.escape_html(scanned_value)}`,
					indicator: 'red'
				});
				return;
			}

			// The Link field stores the Ascend Product's name (the ID column),
			// not the scanned barcode.
			const store_upc = product.name;
			const existing_row = (frm.doc.swap_tag_items || []).find(
				row => row.product === store_upc
			);

			if (existing_row) {
				frappe.model.set_value(existing_row.doctype, existing_row.name, 'print_quantity', existing_row.print_quantity + 1);
			} else {
				frm.add_child('swap_tag_items', {
					// Preview values for description and upc will be replaced after save by virtual field implementation.
					print: 1,
                    product: store_upc,
					description: product.description,
					print_quantity: 1
				});
			}
			frm.refresh_field('swap_tag_items');
			frappe.show_alert({
				message: `Added: ${frappe.utils.escape_html(product.description || store_upc)}`,
				indicator: 'green'
			});
		}
	});
}

// Mount the scan box as a standalone control (no frm/doc) inside the scan_here HTML field, so
// typing/scanning never writes to frm.doc. Frappe re-renders the HTML field on every form
// refresh, so we re-mount the control here each time.
function setup_scan_box(frm) {
	const field = frm.get_field('scan_here');
	if (!field) return;

	field.$wrapper.empty();
	const control = frappe.ui.form.make_control({
		df: {
			fieldtype: 'Data',
			fieldname: 'scan_here',
			label: __('Add Item'),
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

// Map enabled rows in swap_tag_items to the items contract expected by
// bullwheel.printing.show_print_dialog — Ascend Product is a Native doctype for
// label resolution, so no Vendor Product hop is needed here.
function enabled_swap_tag_items(frm) {
	return (frm.doc.swap_tag_items || [])
		.filter((row) => row.print && row.product)
		.map((row) => ({
			doctype: 'Ascend Product',
			name: row.product,
			quantity: row.print_quantity,
			label: row.description || row.product,
		}));
}

// Enabled = checked to print and pointed at a product. Note that saving the form
// overwrites swap_price back to the live Product Price (SwapTagBatch.before_save),
// so an unsaved hand-edit is the only way a mismatch below can occur.
function build_enabled_rows(frm) {
	return (frm.doc.swap_tag_items || []).filter((row) => row.print && row.product);
}

// swap_price is a Data field (not Currency), so it must be normalized before
// comparing. A product with no Product Price on file at all is always a mismatch —
// there is nothing live for the label to render.
function find_swap_price_mismatches(enabled_rows, live_prices) {
	const TOLERANCE = 0.005;
	return enabled_rows
		.map((row) => {
			const live_price = live_prices[row.product];
			const row_price = flt(row.swap_price);
			const is_missing = live_price === null || live_price === undefined;
			const differs = is_missing || Math.abs(flt(live_price) - row_price) > TOLERANCE;
			return differs
				? {
						product: row.product,
						description: row.description || row.product,
						current_price: is_missing ? null : flt(live_price),
						new_price: row_price,
					}
				: null;
		})
		.filter(Boolean);
}

// One bulk Yes/No dialog covering every mismatched item. Resolves true ("keep as a
// permanent price change"), false ("use for this print only, revert afterward"), or
// null if the dialog was dismissed without a choice (treated as an abort).
function confirm_price_sync(mismatches) {
	return new Promise((resolve) => {
		const rows = mismatches.map((mismatch) => ({
			description: mismatch.description,
			current_price: mismatch.current_price === null ? __('(none on file)') : format_currency(mismatch.current_price),
			new_price: format_currency(mismatch.new_price),
		}));

		let confirmed = false;
		const dialog = new frappe.ui.Dialog({
			title: __('Swap Price Changed'),
			fields: [
				{
					fieldtype: 'HTML',
					fieldname: 'explanation',
					options: `<p>${__(
						'The following items have an edited swap price that does not match the live Product Price. The label always prints the live Product Price, so it will be updated to match before printing. Items with no existing price will keep the new price even if you choose one-time use.'
					)}</p>`,
				},
				{
					label: __('Items'),
					fieldname: 'mismatches',
					fieldtype: 'Table',
					cannot_add_rows: true,
					in_place_edit: false,
					data: rows,
					get_data: () => rows,
					fields: [
						{ label: __('Item'), fieldname: 'description', fieldtype: 'Data', in_list_view: 1, read_only: 1, columns: 5 },
						{ label: __('Current Product Price'), fieldname: 'current_price', fieldtype: 'Data', in_list_view: 1, read_only: 1, columns: 3 },
						{ label: __('New Price'), fieldname: 'new_price', fieldtype: 'Data', in_list_view: 1, read_only: 1, columns: 3 },
					],
				},
			],
			primary_action_label: __('Keep as Permanent Price Change'),
			primary_action: () => {
				confirmed = true;
				dialog.hide();
				resolve(true);
			},
			secondary_action_label: __('Use for This Print Only'),
			secondary_action: () => {
				confirmed = true;
				dialog.hide();
				resolve(false);
			},
			onhide: () => {
				if (!confirmed) resolve(null);
			},
		});
		dialog.show();
	});
}

async function handle_print_enabled_labels(frm) {
	const enabled_rows = build_enabled_rows(frm);
	if (!enabled_rows.length) {
		frappe.show_alert({ message: __('No items are marked to print.'), indicator: 'orange' });
		return;
	}

	const products = enabled_rows.map((row) => row.product);
	const live_prices = await frappe.call({
		method: 'bullwheel.ascend.doctype.product_price.product_price.get_swap_prices',
		args: { products },
	}).then((response) => response.message || {});

	const mismatches = find_swap_price_mismatches(enabled_rows, live_prices);

	let keep_price_changes = null;
	if (mismatches.length) {
		keep_price_changes = await confirm_price_sync(mismatches);
		if (keep_price_changes === null) {
			// Dialog dismissed without a choice: abort. Nothing has been written yet.
			return;
		}
	}

	// Precompute what to write/restore, but don't write anything yet — the print
	// dialog's own Print button (with its per-item quantity table) is the actual
	// confirmation step, so nothing touches Product Price until that fires.
	let new_prices = null;
	let original_prices_to_restore = null;
	if (mismatches.length) {
		new_prices = {};
		mismatches.forEach((mismatch) => {
			new_prices[mismatch.product] = mismatch.new_price;
		});

		if (!keep_price_changes) {
			original_prices_to_restore = {};
			mismatches.forEach((mismatch) => {
				if (mismatch.current_price !== null) {
					original_prices_to_restore[mismatch.product] = mismatch.current_price;
				}
			});
		}
	}

	bullwheel.printing.show_print_dialog({
		title: __('Print Enabled Labels'),
		items: enabled_swap_tag_items(frm),
		slot: 'swap_tag',
		on_submit: async (printer_name, printable_items) => {
			if (new_prices) {
				// Must complete before printing: print_labels reads Product Price live.
				await frappe.call({
					method: 'bullwheel.ascend.doctype.product_price.product_price.set_swap_prices',
					args: { prices: new_prices },
				});
			}

			bullwheel.printing
				.send_print_request({
					method: 'bullwheel.label_printing.print_labels',
					printer_name: printer_name,
					slot: 'swap_tag',
					doctype: 'Ascend Product',
					items: printable_items,
					label: __('Print Enabled Labels'),
				})
				.then(() => {
					// Only now, after the server has actually finished printing (and
					// therefore already read the live price), revert the temporary
					// change for anything the user chose "this print only" for.
					if (original_prices_to_restore && Object.keys(original_prices_to_restore).length) {
						frappe.call({
							method: 'bullwheel.ascend.doctype.product_price.product_price.set_swap_prices',
							args: { prices: original_prices_to_restore },
						});
					}
				});
		},
	});
}

frappe.ui.form.on('Swap Tag Batch', {
	refresh(frm) {
		frm.add_custom_button(__('Print Enabled Labels'), () => handle_print_enabled_labels(frm));

		setup_scan_box(frm);
	}
});
