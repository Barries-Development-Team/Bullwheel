# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Bulk Product Import: a one-vendor batch of New Products exported on an Ascend Vendor Products
import sheet.

Order Receipt exports the New Products on its own order. This batch covers New Products created
outside an order (from the New Product list) and lets staff export a vendor's whole backlog at
once. Ascend's importer does not read the vendor from the sheet — it is chosen in Ascend's import
dialog — so a batch holds one vendor's products. Generating the sheet marks them Exported."""

import frappe
from frappe.model.document import Document

from bullwheel.ascend.import_sheets import build_import_sheet, serve_file_download
from bullwheel.ascend.doctype.new_product.new_product import export_blocker, mark_exported, to_import_row


class BulkProductImport(Document):
	def validate(self):
		"""Every product in the batch must belong to the batch's vendor, and none may appear twice."""
		seen = set()
		for row in self.new_products:
			if row.new_product in seen:
				frappe.throw(f"New Product {row.new_product} is in this batch more than once.")
			seen.add(row.new_product)

			vendor = frappe.db.get_value("New Product", row.new_product, "vendor")
			if vendor != self.vendor:
				frappe.throw(
					f"New Product {row.new_product} belongs to {vendor}, not {self.vendor}. "
					f"One import sheet holds one vendor's products."
				)


@frappe.whitelist()
def get_pending_products(vendor: str) -> list[str]:
	"""Names of the vendor's Pending New Products, oldest first — the ones that are not on any
	import sheet yet."""
	return frappe.get_all(
		"New Product", filters={"vendor": vendor, "status": "Pending"}, order_by="creation asc", pluck="name"
	)


@frappe.whitelist()
def generate_import_sheet(name):
	"""Build an Ascend Vendor Products import sheet from the saved batch, mark its New Products
	Exported, and serve the sheet as a download. Refuses a batch holding anything that is not
	Pending or that Ascend cannot take yet (see new_product.export_blocker), so a sheet never
	re-exports a product or ships one that would create a duplicate."""
	document = frappe.get_doc("Bulk Product Import", name)
	document.check_permission("write")

	if not document.new_products:
		frappe.throw("Add New Products to the batch first (Get Pending Products).")

	problems = []
	for row in document.new_products:
		status = frappe.db.get_value("New Product", row.new_product, "status")
		if status != "Pending":
			problems.append(f"{row.new_product} is {status}, not Pending")
		elif reason := export_blocker(row.new_product):
			problems.append(f"{row.new_product}: {reason}")
	if problems:
		frappe.throw("This batch cannot be exported:<br>" + "<br>".join(problems))

	template_path = frappe.get_app_path(
		"bullwheel", "ascend", "import_templates", "ascend_template_vendor_products.xlsx"
	)
	sheet = build_import_sheet(
		template_path,
		[to_import_row(frappe.get_doc("New Product", row.new_product)) for row in document.new_products],
	)

	for row in document.new_products:
		mark_exported(row.new_product, export_batch=name)
	document.db_set("status", "Exported")
	frappe.db.commit()

	serve_file_download(
		f"{name} - {document.vendor} - Ascend Vendor Products.xlsx",
		sheet,
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	)
