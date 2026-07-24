frappe.listview_settings['Ascend Product'] = {
    onload: function(listview) {
        listview.page.add_menu_item(__('Find Products'), function() {
            let selected = listview.get_checked_items()
            if (!selected.length) {
                frappe.msgprint(__("Please select a product."));
                return;
            }
            if (selected.length > 1) {
                frappe.msgprint(__("Please select a single product. Multi-product support is current work-in-progress."));
                return;
            }
            bullwheel.warehouse.product_location_dialog({
				product_sku: selected[0].name,
				description: selected[0].description
			})
        })

    }
}
