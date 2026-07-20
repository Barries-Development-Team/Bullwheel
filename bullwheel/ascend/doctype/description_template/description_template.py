# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class DescriptionTemplate(Document):
	def render(self, product):
		"""Render this template's stored Jinja template into a description string, injecting
		`product` (a New Product document, or an equivalent field dict for an in-progress form)
		as `doc` so the template can read its field values. Collapses the rendered output's
		whitespace onto a single line, since templates are usually written across multiple
		lines for readability."""
		rendered = frappe.render_template(self.template, {"doc": product})
		return " ".join(rendered.split())
