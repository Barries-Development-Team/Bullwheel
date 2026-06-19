frappe.pages['find-product'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Find Product',
		single_column: true
	});
}