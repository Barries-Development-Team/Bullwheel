// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Route "+ Add New Product" through the full-form dialog instead of Quick Entry: Quick Entry
// has no script_manager, so the live description regeneration handlers in new_product.js
// cannot run there. The dialog hosts the real Form, where they work as on the full page.
const IMPORT_OVERDUE_DAYS = 3;

frappe.listview_settings['New Product'] = {
	onload(listview) {
		// Looks for Vendor Products Ascend now holds for Exported/Pending New Products and matches
		// them. Also runs on a schedule; this is for "I just imported it".
		listview.page.add_inner_button(__('Check Ascend'), () => {
			frappe.call({
				method: 'bullwheel.ascend.new_product_reconciliation.check_ascend',
				freeze: true,
				freeze_message: __('Checking Ascend...'),
				callback: () => listview.refresh(),
			});
		});
	},
	add_fields: ['status', 'exported_on'],
	// Status colors: Pending (waiting to be exported) orange, Exported (waiting for Ascend) blue,
	// Imported green, Import Failed red, Cancelled gray. An export that Ascend has not picked up
	// within IMPORT_OVERDUE_DAYS shows red, since the import sheet is probably still unimported.
	get_indicator(doc) {
		if (doc.status === 'Exported' && doc.exported_on
			&& frappe.datetime.get_day_diff(frappe.datetime.now_datetime(), doc.exported_on) >= IMPORT_OVERDUE_DAYS) {
			return [__('Import Overdue'), 'red', 'status,=,Exported'];
		}
		const colors = {
			'Pending': 'orange', 'Exported': 'blue', 'Imported': 'green',
			'Import Failed': 'red', 'Cancelled': 'gray',
		};
		return [__(doc.status), colors[doc.status] || 'gray', 'status,=,' + doc.status];
	},
	primary_action() {
		bullwheel.forms.open_form_dialog('New Product', {
			after_insert() {
				cur_list && cur_list.refresh();
			},
		});
	},
};
