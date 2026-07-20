frappe.pages['item-check-in-out'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Item Check-In/Out',
		single_column: true
	});

	page.set_primary_action('Check In', () => bullwheel.warehouse.check_in_item(), 'add');
	page.add_button('Check Out', () => bullwheel.warehouse.check_out_item(), { icon: 'remove' });
}