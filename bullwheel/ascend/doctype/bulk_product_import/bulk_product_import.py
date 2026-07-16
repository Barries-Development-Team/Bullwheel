# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import frappe
from frappe.model.document import Document

from bullwheel.ascend.import_sheets import generate_import_sheet as write_import_sheet
from bullwheel.ascend.doctype.new_product.new_product import to_import_row


class BulkProductImport(Document):
	pass


@frappe.whitelist()
def generate_import_sheet(name):
	"""Build an Ascend Vendor Products import sheet from the saved child table rows and serve it as a download."""
	document = frappe.get_doc("Bulk Product Import", name)

	template_path = frappe.get_app_path(
		"bullwheel", "ascend", "import_templates", "ascend_template_vendor_products.xlsx"
	)

	rows = [to_import_row(product) for product in document.table_frll]
	write_import_sheet(template_path, rows, f"{name} - Ascend Vendor Product Import.xlsx")