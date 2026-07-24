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
	"binding_brand_and_model"
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

// Confirms intentional creation before a brand-new product record is saved. Returning a
// Promise from before_save makes the save wait for the user's answer (see Frappe's
// validate_and_save, which awaits the before_save trigger before checking
// frappe.validated); setting frappe.validated = false on "No" stops the save the same way
// a failed validation would. Only guards creation — saving edits to an existing record
// does not re-prompt.
//
// The Save button is disabled here explicitly because frappe.ui.form.save() (save.js) only
// disables it once validate + before_save have already resolved — while this confirm dialog
// is up, the button underneath is still clickable. A second click during that gap (plus the
// before_insert round-trip to Ascend for VPN generation) starts a second, fully independent
// save before the first has assigned this document a real name, so the server processes both
// as separate inserts: two New Product records, each running its own after_insert, i.e. two
// Ascend Product records — and only one wins the race to claim a Vendor Product, since the
// second one's part-number match check runs after the first has already committed.
function confirm_new_product_save(frm) {
	if (!frm.is_new()) {
		return;
	}

	const primary_button = frm.page.btn_primary;
	primary_button.prop("disabled", true);

	return new Promise((resolve) => {
		frappe.confirm(
			__("Create this product record?"),
			() => resolve(),
			() => {
				frappe.validated = false;
				primary_button.prop("disabled", false);
				resolve();
			}
		);
	});
}

// Vendor is visible by default (set directly on the DocType), but Order Receipt's scan flow
// seeds it automatically — see open_new_product_form_dialog in order_receipt.js — so it hides
// the field for that flow specifically. Handled here in JS, keyed off the __created_via_order_receipt
// seed property, rather than the field's own hidden_depends_on: that property lives in the same
// DocType JSON the field's default visibility is edited through, so a doctype-editor save that
// doesn't include it would silently wipe it out again.
function toggle_vendor_visibility(frm) {
	frm.toggle_display("vendor", !frm.doc.__created_via_order_receipt);
}

// The Ski Details fields show (and Binding Brand and Model becomes required) via
// depends_on/mandatory_depends_on expressions on the DocType that read the configured prefix
// from frappe.boot.ski_category_prefix (see bullwheel_core/__init__.py). Those run on the full form and
// in the Quick Entry receiving modal alike, so no form-script visibility logic is needed here.
const handlers = {
	onload: toggle_vendor_visibility,
	description_template(frm) {
		regenerate_description(frm);
	},
	before_save: confirm_new_product_save,
};

for (const fieldname of DESCRIPTION_SOURCE_FIELDS) {
	handlers[fieldname] = regenerate_description;
}

// bullwheel.forms.open_form_dialog (form_dialog.js) constructs a brand-new frappe.ui.form.Form
// on every open, unlike Frappe's own cached FormFactory — so ScriptManager.setup() re-evaluates
// this whole file each time, and a bare frappe.ui.form.on() call here would re-register every
// handler and accumulate duplicates in frappe.ui.form.handlers (which persists for the browser
// session across those re-evaluations). This guard registers once per session.
if (!frappe.ui.form.handlers["New Product"]?.before_save) {
	frappe.ui.form.on("New Product", handlers);
}
