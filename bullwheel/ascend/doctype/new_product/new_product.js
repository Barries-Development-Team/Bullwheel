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

// Fields whose change should re-derive Swap Price and Online Price from the chosen Product
// Pricing Rule. `price` carries the MSRP the rule's percentages are applied to (its label is
// "MSRP"); `product_pricing_rule` selects which rule to apply. Note `price` also appears in
// DESCRIPTION_SOURCE_FIELDS, so both regenerators run when it changes — see add_field_handler.
const PRICING_SOURCE_FIELDS = ["price", "product_pricing_rule"];

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

// Re-derive Swap Price and Online Price from the selected Product Pricing Rule and the current
// MSRP (the `price` field). With no rule selected the fields are left alone — the rule's
// placeholder invites entering the prices manually — matching the server-side _compute_pricing.
function regenerate_pricing(frm) {
	if (!frm.doc.product_pricing_rule) {
		return;
	}

	frappe.call({
		method: "bullwheel.ascend.doctype.new_product.new_product.compute_swap_and_online_price",
		args: {
			msrp: frm.doc.price,
			product_pricing_rule_name: frm.doc.product_pricing_rule,
		},
		callback(response) {
			if (response.message) {
				frm.set_value("swap_price", response.message.swap_price);
				frm.set_value("online_price", response.message.online_price);
			}
		},
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

// Register a change handler for a field, composing with any already registered for it rather
// than overwriting — `price` drives both the Description and the pricing regenerators, so both
// must fire on its change.
function add_field_handler(fieldname, handler) {
	const existing = handlers[fieldname];
	handlers[fieldname] = existing
		? (frm) => {
			existing(frm);
			handler(frm);
		}
		: handler;
}

for (const fieldname of DESCRIPTION_SOURCE_FIELDS) {
	add_field_handler(fieldname, regenerate_description);
}

for (const fieldname of PRICING_SOURCE_FIELDS) {
	add_field_handler(fieldname, regenerate_pricing);
}

// bullwheel.forms.open_form_dialog (form_dialog.js) constructs a brand-new frappe.ui.form.Form
// on every open, unlike Frappe's own cached FormFactory — so ScriptManager.setup() re-evaluates
// this whole file each time, and a bare frappe.ui.form.on() call here would re-register every
// handler and accumulate duplicates in frappe.ui.form.handlers (which persists for the browser
// session across those re-evaluations). This guard registers once per session.
if (!frappe.ui.form.handlers["New Product"]?.before_save) {
	frappe.ui.form.on("New Product", handlers);
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