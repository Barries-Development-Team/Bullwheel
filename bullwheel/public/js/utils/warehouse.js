// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

frappe.provide('bullwheel.warehouse');

// Dialog UI for listing a product's locations
// product_sku  - Ascend SKU of the product (or the New Product's name when product_type is 'New Product').
// description  - Optional. Many circumstances where this function would be called already have the description, so it can be provided here to save a query.
// product_type - 'Ascend Product' (default) or 'New Product' for a product not imported into Ascend yet.
import { productLocationTable } from "./product_location_table";

bullwheel.warehouse.product_location_dialog = function({ product_sku, description = null, product_type = 'Ascend Product' } = {}) {

	// Look up the description only when the caller did not already supply one,
	// then open the dialog — nested so the "not found" message always has the
	// description available rather than racing an in-flight lookup.
	if (description === null) {
		const lookup = product_type === 'New Product'
			? frappe.db.get_value('New Product', product_sku, 'description').then((response) => response.message)
			: frappe.call({
				method: 'bullwheel.ascend.doctype.ascend_product.ascend_product.get_values',
				args: {
					name: product_sku,
					fields: JSON.stringify(["description"])
				}
			}).then((response) => response.message);

		lookup.then((record) => {
			// The product may not exist (mistyped, or removed); show locations by SKU alone then.
			description = (record && record.description) || product_sku;
			show_locations();
		});
	} else {
		show_locations();
	}

	function show_locations() {
		frappe.call({
			method: 'bullwheel.warehouse.stock_handler.get_product_locations',
			args: { product: product_sku, product_type: product_type },
			callback: function(response) {
				var locations = response.message || [];
				// Return if no locations were found
				if (!locations.length) {
					frappe.msgprint({
						title: __('Not Found'),
						indicator: 'red',
						message: __(`No warehouse location quantities were found for ${description} (${product_sku}).`)
					})
					return;
				}

				// Dialog Box with HTML field
				let dialog = new frappe.ui.Dialog({
					title: __('Product Locations'),
					primary_action_label: __('OK'),
					primary_action() {
						dialog.hide();
					}
				})

				dialog.$body.html(productLocationTable(locations));

				dialog.show();
			}
		})
	}
}

// Shared item check-in/check-out dialogs. Registered on the `bullwheel.warehouse`
// namespace rather than exported, because this bundle is loaded through
// `app_include_js` — DocType and Page scripts have no way to import from it.

// Product entry for a dialog whose caller does not already know the product: a single field taking
// any identifier (Store SKU, UPC, vendor part number, or New Product ID), resolved through
// bullwheel.ascend.resolve_scanned_product — Ascend Products first, New Products as the fallback,
// and a picker when several products match. The resolved product is shown under the field.
//
//   get_dialog - returns the dialog the field belongs to (it does not exist yet when the field
//                definition is built).
//   on_change  - optional callback invoked with the newly resolved product, or null.
//
// Returns { field, resolve }: `field` is the dialog field definition, and `resolve(callback)` passes
// the current entry's product ({doctype, name, description, upc}) or null to callback, reusing the
// last resolution while the entry is unchanged. Closing the picker without choosing calls nothing.
bullwheel.warehouse.product_lookup_field = function ({ get_dialog, on_change = () => {} } = {}) {
	const default_description = __('Scan or type a Store SKU, UPC, vendor part number, or New Product ID.');
	let resolved = { identifier: null, product: null };
	// The lookup in flight: its identifier and the callbacks waiting on it. A scanner's Enter, the
	// field's debounced change event, its blur, and the primary action can all ask for the same
	// identifier while the server (or the ambiguity picker) is still answering; they share this one
	// lookup instead of starting more, so a second picker can never open on top of the first.
	let pending = null;

	function show(identifier, product) {
		let description = default_description;
		if (product) {
			description = `<span style="color: #0ea5e9">${frappe.utils.escape_html(product.doctype)}: `
				+ `${frappe.utils.escape_html(product.description || product.name)} (${frappe.utils.escape_html(product.name)})</span>`;
		} else if (identifier) {
			description = `<span class="text-danger">${__('No Ascend Product or New Product matches {0}.', [frappe.utils.escape_html(identifier)])}</span>`;
		}
		// set_description rewrites only the help text. set_df_property would refresh the whole
		// control, which writes the control's stored value back into the input — and that value lags
		// a scanner's Enter by up to 500 ms (it is only synced on change), so the box would be blanked.
		get_dialog().fields_dict.product_identifier.set_description(description);
	}

	function settle(identifier, product, callbacks) {
		resolved = { identifier, product };
		show(identifier, product);
		on_change(product);
		callbacks.forEach((callback) => callback(product));
	}

	function resolve(callback) {
		const identifier = (get_dialog().get_value('product_identifier') || '').trim();
		if (identifier === resolved.identifier) {
			callback(resolved.product);
			return;
		}
		if (pending && pending.identifier === identifier) {
			pending.callbacks.push(callback);
			return;
		}
		if (!identifier) {
			pending = null;
			settle(identifier, null, [callback]);
			return;
		}

		const lookup = { identifier, callbacks: [callback] };
		pending = lookup;
		bullwheel.ascend.resolve_scanned_product(
			identifier,
			(product) => {
				if (pending !== lookup) return;  // The box was edited while this was in flight.
				pending = null;
				settle(identifier, product, lookup.callbacks);
			},
			// Picker closed without a choice, or the request failed: release the lookup so the next
			// attempt at this identifier starts fresh.
			() => { if (pending === lookup) pending = null; },
		);
	}

	return {
		field: {
			label: __('Product'),
			fieldname: 'product_identifier',
			fieldtype: 'Data',
			reqd: 1,
			description: default_description,
			onchange: () => resolve(() => {}),
		},
		resolve,
	};
};

// Resolve a scanner's trailing Enter in the product field right away rather than on blur. A
// found product keeps its text in the box and moves focus on to `next_fieldname`, so the next scan
// or entry lands in the right place; an unknown one keeps focus here with its text selected, so the
// next scan replaces it instead of being appended to it.
function resolve_product_on_enter(dialog, lookup, next_fieldname) {
	const product_input = dialog.fields_dict.product_identifier.$input;
	product_input.on('keydown', (event) => {
		if (event.key !== 'Enter') return;
		event.preventDefault();
		lookup.resolve((product) => {
			if (!product) {
				product_input.select();
				return;
			}
			// Deferred so the ambiguity picker's teardown cannot hand focus back to this box.
			if (next_fieldname) setTimeout(() => dialog.get_field(next_fieldname).set_focus(), 0);
		});
	});
}

// The Product Type + Product fields used when the caller pins a product (e.g. the Ascend Product
// or New Product form's own buttons). Both are fixed: the type is hidden and the product read-only,
// since the dialog is about the document it was opened from.
function pinned_product_fields(product, product_type) {
	return [
		{
			label: __('Product Type'),
			fieldname: 'product_type',
			fieldtype: 'Select',
			options: ['Ascend Product', 'New Product'],
			default: product_type,
			hidden: 1,
		},
		{
			label: __(product_type),
			fieldname: 'product',
			fieldtype: 'Dynamic Link',
			options: 'product_type',
			reqd: 1,
			default: product,
			read_only: 1,
		},
	];
}

// Pass the dialog's chosen product to callback as {doctype, name, label}: the resolved entry when the
// dialog uses product_lookup_field, otherwise the pinned Product Type + Product values.
function with_dialog_product(lookup, values, callback) {
	if (!lookup) {
		callback({ doctype: values.product_type, name: values.product, label: values.product });
		return;
	}
	lookup.resolve((product) => {
		if (!product) {
			frappe.show_alert({ message: __('Enter a product that exists in Ascend or as a New Product.'), indicator: 'orange' });
			return;
		}
		callback({ doctype: product.doctype, name: product.name, label: product.description || product.name });
	});
}

// Prompt for a product, a leaf Warehouse Location, and a quantity, then add that
// quantity to the location's on-hand inventory.
//
//   on_success - optional callback invoked with (product, location, quantity) once
//                the server confirms the check-in, so callers (e.g. a page refresh)
//                can react without polling.
//   product    - optional product name to pre-fill, for callers (e.g. the Ascend Product
//                form) that already know the product being checked in. Without it, the
//                dialog takes any identifier and searches Ascend Products, then New
//                Products (see product_lookup_field).
//   product_type - 'Ascend Product' (default), or 'New Product' for a product that is not
//                imported into Ascend yet. Only used with `product`.
bullwheel.warehouse.check_in_item = function ({ on_success, product, product_type = 'Ascend Product' } = {}) {
	let dialog;
	const lookup = product ? null : bullwheel.warehouse.product_lookup_field({ get_dialog: () => dialog });

	dialog = new frappe.ui.Dialog({
		title: __('Check In Item'),
		fields: [
			...(lookup ? [lookup.field] : pinned_product_fields(product, product_type)),
			{
				label: __('Warehouse Location'),
				fieldname: 'location',
				fieldtype: 'Link',
				options: 'Warehouse Location',
				reqd: 1,
				description: __('Only leaf locations can hold inventory.'),
				get_query: () => ({ filters: { is_group: 0 } }),
			},
			{
				label: __('Quantity'),
				fieldname: 'quantity',
				fieldtype: 'Int',
				reqd: 1,
				default: 1,
			},
		],
		primary_action_label: __('Check In'),
		primary_action(values) {
			if (cint(values.quantity) <= 0) {
				frappe.show_alert({ message: __('Quantity must be greater than zero.'), indicator: 'orange' });
				return;
			}

			with_dialog_product(lookup, values, (chosen) => {
				frappe.call({
					method: 'bullwheel.warehouse.stock_handler.check_in_item',
					args: {
						product: chosen.name,
						product_type: chosen.doctype,
						location: values.location,
						quantity: values.quantity,
					},
					callback() {
						dialog.hide();
						frappe.show_alert({
							message: __('Checked in {0} x {1} at {2}.', [values.quantity, chosen.label, values.location]),
							indicator: 'green',
						});
						on_success && on_success(chosen.name, values.location, cint(values.quantity));
					},
				});
			});
		},
	});

	if (lookup) resolve_product_on_enter(dialog, lookup, 'location');
	dialog.show();
};

// Prompt for a product and a quantity, list only the Warehouse Locations that
// currently have that product on hand, and remove that quantity from the chosen
// location's inventory.
//
//   on_success - optional callback invoked with (product, location, quantity) once
//                the server confirms the check-out.
//   product    - optional product name to pre-fill, for callers (e.g. the Ascend Product
//                form) that already know the product being checked out. Without it, the
//                dialog takes any identifier and searches Ascend Products, then New
//                Products (see product_lookup_field).
//   product_type - 'Ascend Product' (default), or 'New Product' for a product that is not
//                imported into Ascend yet. Only used with `product`.
bullwheel.warehouse.check_out_item = function ({ on_success, product, product_type = 'Ascend Product' } = {}) {
	let location_quantities = {};
	let dialog;
	const lookup = product ? null : bullwheel.warehouse.product_lookup_field({
		get_dialog: () => dialog,
		on_change: (resolved) => refresh_locations(resolved && resolved.doctype, resolved && resolved.name),
	});
	const refresh_pinned_locations = () => refresh_locations(dialog.get_value('product_type'), dialog.get_value('product'));

	dialog = new frappe.ui.Dialog({
		title: __('Check Out Item'),
		fields: [
			...(lookup ? [lookup.field] : pinned_product_fields(product, product_type)),
			{
				label: __('Warehouse Location'),
				fieldname: 'location',
				fieldtype: 'Select',
				reqd: 1,
				description: __('Select a product to see where it is on hand.'),
				onchange() {
					const on_hand = location_quantities[dialog.get_value('location')] || 0;
					dialog.set_value('on_hand', on_hand);
				},
			},
			{
				label: __('On Hand'),
				fieldname: 'on_hand',
				fieldtype: 'Int',
				read_only: 1,
				depends_on: 'eval:doc.location',
			},
			{
				label: __('Quantity'),
				fieldname: 'quantity',
				fieldtype: 'Int',
				reqd: 1,
				default: 1,
			},
		],
		primary_action_label: __('Check Out'),
		primary_action(values) {
			if (cint(values.quantity) <= 0) {
				frappe.show_alert({ message: __('Quantity must be greater than zero.'), indicator: 'orange' });
				return;
			}

			with_dialog_product(lookup, values, (chosen) => {
				const on_hand = location_quantities[values.location] || 0;
				if (cint(values.quantity) > on_hand) {
					frappe.show_alert({
						message: __('Only {0} of {1} on hand at {2}.', [on_hand, chosen.label, values.location]),
						indicator: 'orange',
					});
					return;
				}

				frappe.call({
					method: 'bullwheel.warehouse.stock_handler.check_out_item',
					args: {
						product: chosen.name,
						product_type: chosen.doctype,
						location: values.location,
						quantity: values.quantity,
					},
					callback() {
						dialog.hide();
						frappe.show_alert({
							message: __('Checked out {0} x {1} from {2}.', [values.quantity, chosen.label, values.location]),
							indicator: 'green',
						});
						on_success && on_success(chosen.name, values.location, cint(values.quantity));
					},
				});
			});
		},
	});

	// Re-populate the location Select each time the product changes, since only
	// locations with on-hand quantity of this product are valid check-out targets.
	function refresh_locations(selected_product_type, selected_product) {
		location_quantities = {};
		dialog.set_df_property('location', 'options', []);
		dialog.set_value('location', '');
		dialog.set_value('on_hand', 0);

		if (!selected_product) return;

		frappe.call({
			method: 'bullwheel.warehouse.stock_handler.get_product_locations',
			args: { product: selected_product, product_type: selected_product_type },
			callback(response) {
				const rows = response.message || [];
				if (!rows.length) {
					frappe.show_alert({
						message: __('No warehouse locations have {0} on hand.', [selected_product]),
						indicator: 'orange',
					});
					return;
				}

				rows.forEach((row) => { location_quantities[row.parent] = cint(row.quantity); });
				dialog.set_df_property('location', 'options', rows.map((row) => row.parent));
			},
		});
	}

	// Populate the location Select right away when a product default was supplied,
	// since the field's own onchange only fires on user interaction.
	if (product) refresh_pinned_locations();

	if (lookup) resolve_product_on_enter(dialog, lookup, 'location');
	dialog.show();
};
