# Copyright (c) 2026, Barrie's Ski and Sports and Contributors
# See license.txt

"""Unit tests for DescriptionTemplate.render — pure Jinja rendering, no DB dependency."""

import frappe
from frappe.tests import UnitTestCase


class UnitTestDescriptionTemplate(UnitTestCase):
	def test_render_substitutes_fields(self):
		template = frappe.get_doc({
			"doctype": "Description Template",
			"template_name": "Test Template",
			"template": "{{ doc.brand }} {{ doc.style_name }}",
		})
		product = frappe._dict({"brand": "Rossignol", "style_name": "Experience 88"})

		self.assertEqual(template.render(product), "Rossignol Experience 88")

	def test_render_collapses_whitespace_left_by_conditionals(self):
		template = frappe.get_doc({
			"doctype": "Description Template",
			"template_name": "Test Template",
			"template": "{{ doc.brand }}\n{% if doc.color %}{{ doc.color }}{% endif %}\n{{ doc.size }}",
		})
		product = frappe._dict({"brand": "Rossignol", "color": None, "size": "170cm"})

		self.assertEqual(template.render(product), "Rossignol 170cm")
