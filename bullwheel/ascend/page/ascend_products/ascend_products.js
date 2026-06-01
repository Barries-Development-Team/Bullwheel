// Copyright (c) 2026 Barrie's Ski and Sports
// All Rights Reserved
// Unauthorized copying or distribution of this file is prohibited.

// Result Columns must exactly match the names of columns returned by the SQL Query, as defined in ascend_products.py
const RESULT_COLUMNS = ['Description', 'SKU', 'UPC', 'Brand', 'Price', 'Quantity', 'Location'];

frappe.pages['ascend-products'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Ascend Product Search',
		single_column: true
	});

	page.add_field({
		label: 'Server',
		fieldtype: 'Link',
		fieldname: 'server_name',
		options: 'SQL Server',
	});

	page.add_field({
		label: 'Search Field',
		fieldtype: 'Select',
		fieldname: 'search_field',
		options: [
			'Default (Description, SKU, UPC)',
			'Description',
			'Price',
			'Quantity',
			'UPC',
			'SKU',
			'Manufacturer Part Number',
			'Keyword',
			'Location',
			'Brand',
			'Color',
			'Size',
			'Style Name',
			'Style Number',
			'Gender',
			'Year',
			'Season',
		].join('\n'),
		default: 'Default (Description, SKU, UPC)',
	});

	let search_text_field = page.add_field({
		label: 'Search',
		fieldtype: 'Data',
		fieldname: 'search_text',
	});

	page.set_primary_action('Search', () => perform_search(page), 'search');

	$(page.main).append('<div class="product-results" style="padding: 1rem;"></div>');

	search_text_field.$input.on('keydown', function(event) {
		if (event.key === 'Enter') perform_search(page);
	});
};

function perform_search(page) {
	let server_name = page.fields_dict['server_name'].get_value();
	let search_text = page.fields_dict['search_text'].get_value();
	let search_field_label = page.fields_dict['search_field'].get_value();

	if (!server_name) {
		frappe.msgprint({ message: 'Please select a server.', title: 'Missing Field', indicator: 'orange' });
		return;
	}
	if (!search_text) {
		frappe.msgprint({ message: 'Please enter a search term.', title: 'Missing Field', indicator: 'orange' });
		return;
	}

	let search_field = search_field_label === 'Default (Description, SKU, UPC)'
		? 'default'
		: search_field_label;

	frappe.call({
		method: 'bullwheel.ascend.page.ascend_products.ascend_products.search_products',
		args: {
			server_name: server_name,
			search_text: search_text,
			search_field: search_field,
		},
		callback: function(response) {
			render_results(page, response.message || []);
		},
	});
}

function render_results(page, results) {
	let container = $(page.main).find('.product-results');

	if (!results.length) {
		container.html('<p class="text-muted">No products found.</p>');
		return;
	}

	let header_html = RESULT_COLUMNS.map(column => `<th>${column}</th>`).join('');

	let rows_html = results.map(row => {
		let cells = RESULT_COLUMNS.map(column => `<td>${row[column] ?? ''}</td>`).join('');
		return `<tr>${cells}</tr>`;
	}).join('');

	container.html(`
		<p class="text-muted">${results.length} result${results.length !== 1 ? 's' : ''} found</p>
		<table class="table table-bordered table-hover">
			<thead><tr>${header_html}</tr></thead>
			<tbody>${rows_html}</tbody>
		</table>
	`);
}