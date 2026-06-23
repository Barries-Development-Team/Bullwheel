# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
import json
from frappe.model.document import Document


class BulkProductImport(Document):
	pass

@frappe.whitelist()
def generate_import_sheet(**kwargs):
	document = json.loads(kwargs.get('doc'))
	server_document = frappe.get_doc("Bulk Product Import", document.get('name'))
	return