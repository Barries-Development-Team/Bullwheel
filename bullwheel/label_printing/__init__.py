# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import json

import frappe

from bullwheel.bullwheel_core import get_label
from bullwheel.bullwheel_core.exceptions import	PrintLabelNotConfigured

from bullwheel.label_printing.ZebraPrinter import ZebraPrinter
from bullwheel.label_printing.exceptions import *
from bullwheel.label_printing.resolution import resolve_print_items

def describe_status_problems(status: dict) -> list:
	"""Translate the ~HS status flags into human-readable problem descriptions,
	returning an empty list when the printer reports no known problems."""
	problems = []
	if status.get("paper_out"):
		problems.append("out of paper/media")
	if status.get("head_open"):
		problems.append("printhead is open")
	if status.get("paused"):
		problems.append("paused")
	return problems


@frappe.whitelist()
def test_connection(**kwargs):
	"""Verify that a configured Label Printer is reachable and report its host
	status, surfacing the outcome to the user via a colored message box."""
	document = json.loads(kwargs.get('doc'))
	printer_document = frappe.get_doc("Label Printer", document.get('name'))
	result = ZebraPrinter(printer_document).test_connection()

	if isinstance(result, PrinterException):
		frappe.msgprint(
			msg=f"Could not reach the printer. Please check the IP address, port, and that the printer is powered on and connected to the network. The error is as follows:\n{result}",
			title="Connection Test Failed",
			indicator="red",
		)
		return

	problems = describe_status_problems(result)
	if problems:
		frappe.msgprint(
			msg="The printer is reachable but reports: " + ", ".join(problems) + ".",
			title="Printer Not Ready",
			indicator="orange",
		)
	else:
		frappe.msgprint(
			msg="Connection test succeeded! The printer is reachable and ready.",
			title="Success",
			indicator="green",
		)


@frappe.whitelist()
def get_recommended_print_media(slot: str):
	"""Return the Recommended Print Media configured on the Zebra Printer Label for
	`slot`, or None when the label has none set or the slot itself has no label
	configured yet. Lets the print dialog filter the printer picker to physically
	compatible hardware without requiring the calling user to have read access to
	Bullwheel Settings or Zebra Printer Label."""
	try:
		label = get_label(slot)
	except PrintLabelNotConfigured:
		return None
	return label.recommended_print_media or None


# Multi-Label Print
@frappe.whitelist()
def print_labels(printer_name: str, slot: str, items, doctype: str = None):
	"""Resolve each requested item to a natively printable document, render the Zebra
	Printer Label configured for the given Bullwheel Settings slot once per item with
	its own quantity, and send the concatenated ZPL to the printer in one transmission.

	`items` is a list (or JSON string) of {doctype?, name, quantity?} dicts; `doctype`
	is the default for items that do not carry their own. Items on a Resolved doctype
	are followed to their Native document server-side (see label_printing/resolution.py),
	so callers pass whatever identifiers they have in scope. If any item cannot be
	resolved, nothing prints."""

	if isinstance(items, str):
		items = frappe.parse_json(items)
	if not items:
		frappe.throw("No items were provided to print.")

	printer_document = frappe.get_doc("Label Printer", printer_name)
	if printer_document.disabled:
		frappe.throw(f"Label Printer '{printer_name}' is disabled and cannot be used for printing.")

	try:
		label = get_label(slot)
	except PrintLabelNotConfigured:
		frappe.throw(f"No label is configured for '{slot}' in Bullwheel Settings ▸ Printing ▸ Labels.")

	target_doctypes = [row.target_doctype for row in (label.get("target_doctypes") or [])]
	resolved_items, failure_messages = resolve_print_items(
		items, default_doctype=doctype, target_doctypes=target_doctypes
	)

	if failure_messages:
		frappe.throw(
			"Nothing was printed. The following items cannot be printed:<br>"
			+ "<br>".join(failure_messages),
			title="Cannot Print Labels",
		)
	if not resolved_items:
		frappe.throw("No items to print.")

	# Duplicate selections (e.g. two order items resolving to the same product) render
	# from one fetched document instead of hitting SQL Server once per row.
	document_cache = {}
	zpl = ''
	for native_doctype, native_name, quantity in resolved_items:
		cache_key = (native_doctype, native_name)
		if cache_key not in document_cache:
			try:
				document_cache[cache_key] = frappe.get_doc(native_doctype, native_name)
			except frappe.DoesNotExistError:
				frappe.throw(f"Nothing was printed. {native_doctype} '{native_name}' was not found.")
		zpl += label.render(document_cache[cache_key], printer_document, quantity)

	try:
		with ZebraPrinter(printer_document) as printer:
			printer.send(zpl)
	except PrinterConnectionError:
		return {"status": "connection error", "printer": printer_name}
	except Exception as error:
		raise error

	return {"status": "success", "printer": printer_name}