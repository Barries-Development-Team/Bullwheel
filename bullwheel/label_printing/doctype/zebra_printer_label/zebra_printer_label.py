# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ZebraPrinterLabel(Document):
	def render(self, doc, printer, quantity: int = 1):
		"""Render this label's stored ZPL template into final ZPL, injecting the source
		document, the target printer (for dpi), and this label as Jinja context so the
		template can size and lay out the label from real values."""

		return frappe.render_template(self.zpl, {"doc": doc, "printer": printer, "label": self, "quantity": quantity})
