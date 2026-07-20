// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Shared item check-in/check-out dialogs. Registered on the `bullwheel.warehouse`
// namespace rather than exported, because this bundle is loaded through
// `app_include_js` — DocType and Page scripts have no way to import from it.

frappe.provide('bullwheel.warehouse');

// Prompt for a product, a leaf Warehouse Location, and a quantity, then add that
// quantity to the location's on-hand inventory.
//
//   on_success - optional callback invoked with (product, location, quantity) once
//                the server confirms the check-in, so callers (e.g. a page refresh)
//                can react without polling.
bullwheel.warehouse.check_in_item = function ({ on_success } = {}) {
	const dialog = new frappe.ui.Dialog({
		title: __('Check In Item'),
		fields: [
			{
				label: __('Product'),
				fieldname: 'product',
				fieldtype: 'Link',
				options: 'Ascend Product',
				reqd: 1,
			},
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

			frappe.call({
				method: 'bullwheel.warehouse.stock_handler.check_in_item',
				args: {
					product: values.product,
					location: values.location,
					quantity: values.quantity,
				},
				callback() {
					dialog.hide();
					frappe.show_alert({
						message: __('Checked in {0} x {1} at {2}.', [values.quantity, values.product, values.location]),
						indicator: 'green',
					});
					on_success && on_success(values.product, values.location, cint(values.quantity));
				},
			});
		},
	});

	dialog.show();
};

// Prompt for a product and a quantity, list only the Warehouse Locations that
// currently have that product on hand, and remove that quantity from the chosen
// location's inventory.
//
//   on_success - optional callback invoked with (product, location, quantity) once
//                the server confirms the check-out.
bullwheel.warehouse.check_out_item = function ({ on_success } = {}) {
	let location_quantities = {};

	const dialog = new frappe.ui.Dialog({
		title: __('Check Out Item'),
		fields: [
			{
				label: __('Product'),
				fieldname: 'product',
				fieldtype: 'Link',
				options: 'Ascend Product',
				reqd: 1,
				onchange: refresh_locations,
			},
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
			const on_hand = location_quantities[values.location] || 0;
			if (cint(values.quantity) <= 0) {
				frappe.show_alert({ message: __('Quantity must be greater than zero.'), indicator: 'orange' });
				return;
			}
			if (cint(values.quantity) > on_hand) {
				frappe.show_alert({
					message: __('Only {0} of {1} on hand at {2}.', [on_hand, values.product, values.location]),
					indicator: 'orange',
				});
				return;
			}

			frappe.call({
				method: 'bullwheel.warehouse.stock_handler.check_out_item',
				args: {
					product: values.product,
					location: values.location,
					quantity: values.quantity,
				},
				callback() {
					dialog.hide();
					frappe.show_alert({
						message: __('Checked out {0} x {1} from {2}.', [values.quantity, values.product, values.location]),
						indicator: 'green',
					});
					on_success && on_success(values.product, values.location, cint(values.quantity));
				},
			});
		},
	});

	// Re-populate the location Select each time the product changes, since only
	// locations with on-hand quantity of this product are valid check-out targets.
	function refresh_locations() {
		const product = dialog.get_value('product');
		location_quantities = {};
		dialog.set_df_property('location', 'options', []);
		dialog.set_value('location', '');
		dialog.set_value('on_hand', 0);

		if (!product) return;

		frappe.call({
			method: 'bullwheel.warehouse.stock_handler.get_locations_for_product',
			args: { product: product },
			callback(response) {
				const rows = response.message || [];
				if (!rows.length) {
					frappe.show_alert({
						message: __('No warehouse locations have {0} on hand.', [product]),
						indicator: 'orange',
					});
					return;
				}

				rows.forEach((row) => { location_quantities[row.parent] = cint(row.quantity); });
				dialog.set_df_property('location', 'options', rows.map((row) => row.parent));
			},
		});
	}

	dialog.show();
};
