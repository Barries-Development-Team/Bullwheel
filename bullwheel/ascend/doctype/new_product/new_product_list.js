// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Route "+ Add New Product" through the full-form dialog instead of Quick Entry: Quick Entry
// has no script_manager, so the live description regeneration handlers in new_product.js
// cannot run there. The dialog hosts the real Form, where they work as on the full page.
frappe.listview_settings['New Product'] = {
	primary_action() {
		bullwheel.forms.open_form_dialog('New Product', {
			after_insert() {
				cur_list && cur_list.refresh();
			},
		});
	},
};
