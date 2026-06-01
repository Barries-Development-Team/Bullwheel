// Copyright (c) 2026 Barrie's Ski and Sports
// All Rights Reserved
// Unauthorized copying or distribution of this file is prohibited.

frappe.provide("barries");

frappe.pages["product-search"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Product Search"),
		single_column: true,
	});

	wrapper.product_search = new barries.ProductSearch(page);
};

barries.ProductSearch = class ProductSearch {
	constructor(page) {
		this.page = page;
		this.servers = [];
		this.build_layout();
		this.bind_events();
		this.load_config();
	}

	build_layout() {
		// A small style block keyed to this page so the result list reads as a
		// clean, native-looking list without fighting Frappe's desk styling.
		this.page.main.append(`
			<style>
				.product-search-controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-end; margin-bottom: 12px; }
				.product-search-controls .control-block { display: flex; flex-direction: column; gap: 4px; }
				.product-search-controls .control-label { font-size: var(--text-sm); color: var(--text-muted); }
				.product-search-controls .term-block { flex: 1 1 260px; }
				.product-search-status { color: var(--text-muted); font-size: var(--text-sm); margin-bottom: 8px; min-height: 20px; }
				.product-search-results { border-top: 1px solid var(--border-color); }
				.product-item { padding: 12px 4px; border-bottom: 1px solid var(--border-color); }
				.product-item-title { font-weight: 600; }
				.product-item-meta { color: var(--text-muted); font-size: var(--text-sm); margin-top: 2px; }
				.product-item-meta .sep { margin: 0 6px; opacity: 0.5; }
			</style>
		`);

		this.$body = $(`
			<div class="product-search">
				<div class="product-search-controls">
					<div class="control-block term-block">
						<span class="control-label">${__("Search term")}</span>
						<input type="text" class="form-control search-term"
							placeholder="${__("Description, SKU, UPC…")}">
					</div>
					<div class="control-block field-block">
						<span class="control-label">${__("Search field")}</span>
						<select class="form-control search-field"></select>
					</div>
					<div class="control-block server-block" style="display:none;">
						<span class="control-label">${__("SQL Server")}</span>
						<select class="form-control search-server"></select>
					</div>
					<div class="control-block">
						<button class="btn btn-primary btn-sm search-button">
							${__("Search")}
						</button>
					</div>
				</div>
				<div class="product-search-status"></div>
				<div class="product-search-results"></div>
			</div>
		`).appendTo(this.page.main);

		this.$term = this.$body.find(".search-term");
		this.$field = this.$body.find(".search-field");
		this.$serverBlock = this.$body.find(".server-block");
		this.$server = this.$body.find(".search-server");
		this.$button = this.$body.find(".search-button");
		this.$status = this.$body.find(".product-search-status");
		this.$results = this.$body.find(".product-search-results");
	}

	bind_events() {
		this.$button.on("click", () => this.search());
		this.$term.on("keydown", (event) => {
			if (event.key === "Enter") {
				this.search();
			}
		});
	}

	load_config() {
		frappe
			.xcall("barries.barries.api.inventory.get_search_config")
			.then((config) => this.apply_config(config))
			.catch(() => this.set_status(__("Could not load search configuration.")));
	}

	apply_config(config) {
		const fields = (config && config.fields) || [];
		this.$field.empty();
		fields.forEach((field) => {
			this.$field.append(
				$("<option>").val(field.value).text(field.label)
			);
		});

		this.servers = (config && config.servers) || [];
		if (this.servers.length > 1) {
			this.$server.empty();
			this.servers.forEach((name) => {
				this.$server.append($("<option>").val(name).text(name));
			});
			this.$serverBlock.show();
		} else {
			this.$serverBlock.hide();
		}

		if (this.servers.length === 0) {
			this.$button.prop("disabled", true);
			this.set_status(
				__("No SQL Server connection is configured. Create a SQL Server record first.")
			);
		} else {
			this.$term.focus();
		}
	}

	search() {
		const term = (this.$term.val() || "").trim();
		if (!term) {
			this.$term.focus();
			return;
		}

		const field = this.$field.val();
		const server_name = this.servers.length > 1 ? this.$server.val() : null;

		this.set_status(__("Searching…"));
		this.$results.empty();
		this.$button.prop("disabled", true);

		frappe
			.xcall("barries.barries.api.inventory.search_products", {
				search_term: term,
				field: field,
				server_name: server_name,
			})
			.then((rows) => this.render_results(rows || [], term))
			.catch(() => this.set_status(__("Search failed.")))
			.finally(() => this.$button.prop("disabled", false));
	}

	render_results(rows, term) {
		this.$results.empty();

		if (!rows.length) {
			this.set_status(__('No products found for "{0}".', [term]));
			return;
		}

		this.set_status(__("{0} result(s) for \"{1}\".", [rows.length, term]));

		rows.forEach((row) => {
			this.$results.append(this.render_item(row));
		});
	}

	render_item(row) {
		const meta = [];
		this.add_meta(meta, __("Price"), this.format_price(row.price));
		this.add_meta(meta, __("Qty"), row.quantity);
		this.add_meta(meta, __("SKU"), row.sku);
		this.add_meta(meta, __("UPC"), row.upc);
		this.add_meta(meta, __("Brand"), row.brand);
		this.add_meta(meta, __("Location"), row.location);
		this.add_meta(meta, __("Size"), row.size);
		this.add_meta(meta, __("Color"), row.color);

		const $item = $('<div class="product-item">');
		$item.append(
			$('<div class="product-item-title">').text(
				row.description || __("(no description)")
			)
		);
		if (meta.length) {
			const $meta = $('<div class="product-item-meta">');
			meta.forEach((part, index) => {
				if (index > 0) {
					$meta.append($('<span class="sep">').text("·"));
				}
				$meta.append(document.createTextNode(part));
			});
			$item.append($meta);
		}
		return $item;
	}

	add_meta(list, label, value) {
		if (value === null || value === undefined || value === "") {
			return;
		}
		list.push(`${label}: ${value}`);
	}

	format_price(value) {
		if (value === null || value === undefined || value === "") {
			return value;
		}
		const numeric = Number(value);
		if (Number.isNaN(numeric)) {
			return value;
		}
		return format_currency(numeric);
	}

	set_status(message) {
		this.$status.text(message);
	}
};
