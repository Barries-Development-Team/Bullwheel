# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for print_labels and render_label_zpl.

All tests are pure unit tests with no database dependency: the printer fetch, label
lookup, item resolution, document fetch, and ZebraPrinter transport are each patched
at their seam in bullwheel.label_printing (the same approach test_resolution.py takes).
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from bullwheel.label_printing import print_labels, render_label_zpl
from bullwheel.label_printing.exceptions import PrinterConnectionError

MODULE = "bullwheel.label_printing"


# ─── Test Fixtures ────────────────────────────────────────────────────────────


def make_printer(connection_method="Network", disabled=0, media_type="Direct Thermal", dpi=203):
	"""Build a Label Printer stand-in with the fields print_labels reads."""
	printer = MagicMock()
	printer.connection_method = connection_method
	printer.disabled = disabled
	printer.type = media_type
	printer.dpi = dpi
	return printer


def make_label():
	"""Build a Zebra Printer Label stand-in whose render tags each document and quantity."""
	label = MagicMock()
	label.get.return_value = []
	label.render.side_effect = lambda document, printer, quantity: f"^XA{document.name}x{quantity}^XZ"
	return label


def make_document(name):
	"""Build a fetched native document stand-in carrying only a name."""
	document = MagicMock()
	document.name = name
	return document


@contextmanager
def patched_printing(printer, label, resolved_items, failure_messages=None):
	"""Patch every external seam print_labels touches, yielding the ZebraPrinter class
	mock and the frappe.get_doc mock so tests can assert on transport and fetches."""

	def get_doc(doctype, name):
		"""Return the printer for Label Printer lookups and a named stand-in otherwise."""
		if doctype == "Label Printer":
			return printer
		return make_document(name)

	with (
		patch(f"{MODULE}.frappe.get_doc", side_effect=get_doc) as get_doc_mock,
		patch(f"{MODULE}.get_label", return_value=label),
		patch(f"{MODULE}.resolve_print_items", return_value=(resolved_items, failure_messages or [])),
		patch(f"{MODULE}.ZebraPrinter") as zebra_printer_class,
	):
		yield zebra_printer_class, get_doc_mock


ITEMS = [{"name": "PRODUCT-A", "quantity": 2}]
RESOLVED = [("Ascend Product", "PRODUCT-A", 2)]


# ─── render_label_zpl ─────────────────────────────────────────────────────────


class TestRenderLabelZpl(UnitTestCase):
	def test_concatenates_one_render_per_item(self):
		"""Each resolved item renders once with its own quantity, in order."""
		resolved_items = [("Ascend Product", "PRODUCT-A", 2), ("Ascend Product", "PRODUCT-B", 1)]
		with patched_printing(make_printer(), make_label(), resolved_items):
			zpl = render_label_zpl(make_printer(), "ascend_tag", ITEMS, "Ascend Product")
		self.assertEqual(zpl, "^XAPRODUCT-Ax2^XZ^XAPRODUCT-Bx1^XZ")

	def test_duplicate_items_fetch_the_document_once(self):
		"""Two items resolving to the same document share one fetch."""
		resolved_items = [("Ascend Product", "PRODUCT-A", 1), ("Ascend Product", "PRODUCT-A", 3)]
		with patched_printing(make_printer(), make_label(), resolved_items) as (_, get_doc_mock):
			zpl = render_label_zpl(make_printer(), "ascend_tag", ITEMS, "Ascend Product")
		self.assertEqual(get_doc_mock.call_count, 1)
		self.assertEqual(zpl, "^XAPRODUCT-Ax1^XZ^XAPRODUCT-Ax3^XZ")

	def test_resolution_failure_renders_nothing(self):
		"""Any unresolvable item throws before anything is rendered."""
		label = make_label()
		with patched_printing(make_printer(), label, [], failure_messages=["PRODUCT-X: not found"]):
			with self.assertRaises(frappe.ValidationError):
				render_label_zpl(make_printer(), "ascend_tag", ITEMS, "Ascend Product")
		label.render.assert_not_called()


# ─── print_labels ─────────────────────────────────────────────────────────────


class TestPrintLabels(UnitTestCase):
	def test_browser_printer_returns_zpl_and_printer_details(self):
		"""A Browser printer gets the rendered ZPL plus its media type and dpi back."""
		printer = make_printer(connection_method="Browser", media_type="Thermal Transfer", dpi=300)
		with patched_printing(printer, make_label(), RESOLVED):
			result = print_labels("Front Desk", "swap_tag", ITEMS, "Ascend Product")
		self.assertEqual(
			result,
			{
				"status": "browser",
				"printer": "Front Desk",
				"media_type": "Thermal Transfer",
				"dpi": 300,
				"zpl": "^XAPRODUCT-Ax2^XZ",
			},
		)

	def test_browser_printer_never_opens_a_socket(self):
		"""The server never constructs a ZebraPrinter for a Browser printer."""
		with patched_printing(make_printer(connection_method="Browser"), make_label(), RESOLVED) as (
			zebra_printer_class,
			_,
		):
			print_labels("Front Desk", "ascend_tag", ITEMS, "Ascend Product")
		zebra_printer_class.assert_not_called()

	def test_network_printer_sends_over_socket(self):
		"""A Network printer is sent the rendered ZPL and returns success without the ZPL."""
		with patched_printing(make_printer(), make_label(), RESOLVED) as (zebra_printer_class, _):
			result = print_labels("Warehouse", "ascend_tag", ITEMS, "Ascend Product")
		printer_instance = zebra_printer_class.return_value.__enter__.return_value
		printer_instance.send.assert_called_once_with("^XAPRODUCT-Ax2^XZ")
		self.assertEqual(result, {"status": "success", "printer": "Warehouse"})

	def test_network_connection_error_is_reported(self):
		"""An unreachable Network printer returns the connection error status."""
		with patched_printing(make_printer(), make_label(), RESOLVED) as (zebra_printer_class, _):
			zebra_printer_class.return_value.__enter__.side_effect = PrinterConnectionError("refused")
			result = print_labels("Warehouse", "ascend_tag", ITEMS, "Ascend Product")
		self.assertEqual(result, {"status": "connection error", "printer": "Warehouse"})

	def test_disabled_printer_is_rejected(self):
		"""A disabled printer throws before any rendering."""
		label = make_label()
		with patched_printing(make_printer(connection_method="Browser", disabled=1), label, RESOLVED):
			with self.assertRaises(frappe.ValidationError):
				print_labels("Front Desk", "ascend_tag", ITEMS, "Ascend Product")
		label.render.assert_not_called()
