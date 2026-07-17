# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class OrderReceiptItem(Document):
	# description and upc are snapshot fields, populated once when the item is added
	# (see populate_item_snapshot in order_receipt.py) rather than re-derived from Ascend
	# on every load — that per-row SQL Server lookup was the main receiving-job bottleneck.

	LABEL_RESOLUTION_FIELD = 'vpn'  # Dynamic Link via item_type; label prints resolve through it (see label_printing/resolution.py)
