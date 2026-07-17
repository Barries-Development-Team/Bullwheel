# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Server-side resolution of print items to natively printable documents.

A "Native" doctype is one a Zebra Printer Label template renders directly
(e.g. Ascend Product, Warehouse Location). A "Resolved" doctype carries a Link
or Dynamic Link field that eventually reaches a Native doctype. A Resolved
doctype's controller class declares which field to follow:

	class VendorProduct(AbstractVirtualDocType):
		LABEL_RESOLUTION_FIELD = 'product'   # Link -> Ascend Product

	class OrderReceiptItem(Document):
		LABEL_RESOLUTION_FIELD = 'vpn'       # Dynamic Link via item_type

Native doctypes declare nothing. The resolver hops these fields until it
reaches a doctype with no declaration — or one the label explicitly targets —
so the client never needs a round trip to translate a selection into
printable documents.
"""

import frappe
from frappe.model.base_document import get_controller
from frappe.utils import cint

from bullwheel.label_printing.exceptions import LabelResolutionError

# The class attribute a Resolved doctype's controller declares to name the Link or
# Dynamic Link field the server follows toward a Native doctype.
LABEL_RESOLUTION_ATTRIBUTE = "LABEL_RESOLUTION_FIELD"

# Hop ceiling: real chains are one or two hops, so anything this deep is a
# misconfiguration rather than a legitimate resolution path.
MAXIMUM_RESOLUTION_DEPTH = 10


def get_label_resolution_field(doctype: str) -> str | None:
	"""Return the doctype's declared label-resolution fieldname, or None when the
	doctype is Native (its controller declares no LABEL_RESOLUTION_FIELD)."""
	return getattr(get_controller(doctype), LABEL_RESOLUTION_ATTRIBUTE, None)


def fetch_document_values(doctype: str, name: str, fieldnames: list) -> dict | None:
	"""Fetch the requested fields of one document by name, returning None when the
	document does not exist. Virtual doctypes resolve through their controller
	thanks to the virtual_link_title patch on Database.get_value."""
	return frappe.db.get_value(doctype, name, fieldnames, as_dict=True)


def resolve_to_native(doctype: str, name: str, target_doctypes: list | None = None) -> tuple[str, str]:
	"""Follow the LABEL_RESOLUTION_FIELD chain from (doctype, name), hopping Link and
	Dynamic Link fields until a Native doctype — or one of the label's declared
	target doctypes — is reached, and return that (doctype, name) pair. Raises
	LabelResolutionError when a hop is broken or the chain never terminates."""
	visited = set()

	while True:
		# A doctype the label explicitly targets is printable as-is, even if it
		# declares a resolution field of its own.
		if target_doctypes and doctype in target_doctypes:
			return doctype, name

		resolution_fieldname = get_label_resolution_field(doctype)
		if resolution_fieldname is None:
			return doctype, name

		if (doctype, name) in visited or len(visited) >= MAXIMUM_RESOLUTION_DEPTH:
			raise LabelResolutionError(
				f"Label resolution starting from {doctype} '{name}' exceeded "
				f"{MAXIMUM_RESOLUTION_DEPTH} hops or looped back on itself."
			)
		visited.add((doctype, name))

		resolution_field = frappe.get_meta(doctype).get_field(resolution_fieldname)
		if resolution_field is None:
			raise LabelResolutionError(
				f"{doctype} declares {LABEL_RESOLUTION_ATTRIBUTE} = '{resolution_fieldname}', "
				f"but no such field exists on the doctype."
			)

		if resolution_field.fieldtype == "Link":
			values = fetch_document_values(doctype, name, [resolution_fieldname])
			if values is None:
				raise LabelResolutionError(f"{doctype} '{name}' was not found.")
			next_doctype = resolution_field.options
			next_name = values.get(resolution_fieldname)

		elif resolution_field.fieldtype == "Dynamic Link":
			options_fieldname = resolution_field.options
			values = fetch_document_values(doctype, name, [resolution_fieldname, options_fieldname])
			if values is None:
				raise LabelResolutionError(f"{doctype} '{name}' was not found.")
			next_doctype = values.get(options_fieldname)
			next_name = values.get(resolution_fieldname)

		else:
			raise LabelResolutionError(
				f"{doctype}.{resolution_fieldname} is a {resolution_field.fieldtype} field; "
				f"{LABEL_RESOLUTION_ATTRIBUTE} must name a Link or Dynamic Link field."
			)

		if not next_doctype or not next_name:
			raise LabelResolutionError(
				f"{doctype} '{name}' has no value in its '{resolution_field.label or resolution_fieldname}' "
				f"field, so it cannot be resolved to a printable document."
			)

		doctype, name = next_doctype, next_name


def resolve_print_items(items: list, default_doctype: str | None = None, target_doctypes: list | None = None) -> tuple[list, list]:
	"""Resolve every requested item to a native (doctype, name, quantity) triple,
	returning (resolved_items, failure_messages). Items with quantity below 1 are
	skipped as a deliberate "don't print this one". Callers must refuse to print
	when any failure message is returned, so a bad selection never produces a
	partial print run."""
	resolved_items = []
	failure_messages = []

	for item in items:
		item_doctype = item.get("doctype") or default_doctype
		item_name = item.get("name")
		# An absent quantity means "one copy"; an explicit 0 means "skip this item",
		# so the two cases must not share a falsy-coalescing default.
		quantity = 1 if item.get("quantity") is None else cint(item.get("quantity"))

		if quantity < 1:
			continue
		if not item_doctype or not item_name:
			failure_messages.append(f"An item is missing its doctype or name: {item!r}.")
			continue

		try:
			native_doctype, native_name = resolve_to_native(item_doctype, item_name, target_doctypes)
		except LabelResolutionError as error:
			failure_messages.append(str(error))
			continue

		if target_doctypes and native_doctype not in target_doctypes:
			failure_messages.append(
				f"{item_doctype} '{item_name}' resolves to a {native_doctype}, but this "
				f"label prints {', '.join(target_doctypes)} documents."
			)
			continue

		resolved_items.append((native_doctype, native_name, quantity))

	return resolved_items, failure_messages
