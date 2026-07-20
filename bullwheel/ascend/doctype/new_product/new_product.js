// Copyright (c) 2026, Barrie's Ski and Sports and contributors
// For license information, please see license.txt

// Fields whose change should re-render the Description from the chosen Description
// Template. Add a field here when a template starts (or stops) reading it — see
// documentation/DESCRIPTION_TEMPLATES.md for the full authoring guide.
const DESCRIPTION_SOURCE_FIELDS = [
	"vpn", "brand", "category", "style_name", "style_number", "manufacturers_part_number",
	"color", "size", "gender", "season", "year", "upc",
	"price", "estimated_cost",
	"case", "case_quantity", "case_upc", "case_msrp",
];

function regenerate_description(frm) {
	if (!frm.doc.description_template) {
		return;
	}

	frappe.call({
		method: "bullwheel.ascend.doctype.new_product.new_product.generate_description",
		args: {
			template_name: frm.doc.description_template,
			product: frm.doc,
		},
		callback(response) {
			if (response.message !== undefined) {
				frm.set_value("description", response.message);
			}
		},
	});
}

const handlers = {
	description_template(frm) {
		regenerate_description(frm);
	},
};

for (const fieldname of DESCRIPTION_SOURCE_FIELDS) {
	handlers[fieldname] = regenerate_description;
}

frappe.ui.form.on("New Product", handlers);
