# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import json

import frappe

from bullwheel.bullwheel_core import get_label
from bullwheel.bullwheel_core.exceptions import	PrintLabelNotConfigured

from bullwheel.label_printing.ZebraPrinter import ZebraPrinter
from bullwheel.label_printing.exceptions import *

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


# Multi-Label Print
@frappe.whitelist()
def print_labels(printer_name: str, slot: str, doctype: str, items):
	"""Render the Zebra Printer Label configured for the given Bullwheel Settings slot
	against the source document, then send it to the printer. This is the label-driven
	counterpart of print_zpl, which sends caller-supplied raw ZPL."""

	if isinstance(items, str):
		items = frappe.parse_json(items)
	
	printer_document = frappe.get_doc("Label Printer", printer_name)
	if printer_document.disabled:
		frappe.throw(f"Label Printer '{printer_name}' is disabled and cannot be used for printing.")

	try:
		label = get_label(slot)
	except PrintLabelNotConfigured:
		frappe.throw(f"No label is configured for '{slot}' in Bullwheel Settings ▸ Printing ▸ Labels.")
		
	zpl = ''
	for item in items:
		docname = item.get('name')
		quantity = item.get('quantity')

		source_document = frappe.get_doc(doctype, docname)
		zpl += label.render(source_document, printer_document, quantity)

	try:
		with ZebraPrinter(printer_document) as printer:
			printer.send(zpl)
	except PrinterConnectionError:
		return {"status": "connection error", "printer": printer_name}
	except Exception as error:
		raise error
		
	return {"status": "success", "printer": printer_name}