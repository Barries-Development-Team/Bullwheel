# Copyright (c) 2026, Barrie's Ski and Sports and Contributors
# See license.txt

# import frappe
from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestZebraPrinterLabel(IntegrationTestCase):
	"""
	Integration tests for ZebraPrinterLabel.
	Use this class for testing interactions between multiple components.
	"""

	pass


import frappe
from frappe.tests import UnitTestCase

from bullwheel.label_printing.doctype.zebra_printer_label.zebra_printer_label import missing_zpl_commands


class UnitTestRequiredZplCommands(UnitTestCase):

	def test_bundled_label_templates_are_complete(self):
		labels = frappe.get_file_json(frappe.get_app_path("bullwheel", "fixtures", "zebra_printer_label.json"))
		for label in labels:
			self.assertEqual(missing_zpl_commands(label["zpl"]), [], label["name"])

	def test_minimal_template_passes_with_any_spacing_in_the_quantity_tag(self):
		self.assertEqual(missing_zpl_commands("^XA^FDHi^FS^PQ{{quantity}}^XZ"), [])
		self.assertEqual(missing_zpl_commands("^XA\n^PQ{{ quantity }}\n^XZ"), [])

	def test_each_missing_command_is_reported(self):
		self.assertEqual(len(missing_zpl_commands("")), 3)
		self.assertEqual(len(missing_zpl_commands(None)), 3)
		missing = missing_zpl_commands("^XA^FDHi^FS^XZ")
		self.assertEqual(len(missing), 1)
		self.assertIn("^PQ", missing[0])

	def test_hardcoded_quantity_does_not_count(self):
		self.assertEqual(len(missing_zpl_commands("^XA^PQ1^XZ")), 1)

	def test_command_inside_a_jinja_comment_does_not_count(self):
		self.assertEqual(len(missing_zpl_commands("^XA {# ^PQ{{ quantity }} #} ^XZ")), 1)
