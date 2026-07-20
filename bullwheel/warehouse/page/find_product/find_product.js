frappe.pages['find-product'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Find Product',
		single_column: true
	});

	// Product search control
	var search_field = frappe.ui.form.make_control({
		parent: page.main,
		df: {
			fieldtype: 'Link',
			fieldname: 'product',
			label: 'Product',
			options: 'Ascend Product',
			placeholder: 'Search Ascend products...',
		},
		render_input: true,
	});
	search_field.refresh();

	// Results container
	var $results = $('<div class="find-product-results" style="margin-top: 20px;"></div>').appendTo(page.main);

	function run_search() {
		var product = search_field.get_value();
		$results.empty();

		if (!product) return;

		frappe.call({
			method: 'bullwheel.warehouse.stock_handler.get_locations_for_product',
			args: { product: product },
			callback: function(response) {
				var locations = response.message || [];

				if (!locations.length) {
					$results.append('<p class="text-muted">No warehouse locations found for this product.</p>');
					return;
				}

				var $table = $(`
					<table class="table table-bordered table-hover">
						<thead>
							<tr>
								<th>Warehouse Location</th>
								<th style="text-align: right;">Quantity</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
				`);

				locations.forEach(function(row) {
					var $row = $('<tr>')
						.append($('<td>').text(row.parent))
						.append($('<td style="text-align: right;">').text(row.quantity));
					$table.find('tbody').append($row);
				});

				$results.append($table);
			}
		});
	}

	page.set_primary_action('Find', run_search, 'search');

	// search_field.$input.on('change', run_search);
};