# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Make Frappe's "Show Title in Link Fields" feature work for virtual DocTypes.

Frappe resolves a linked document's title by calling ``frappe.db.get_value`` /
``frappe.db.get_values`` with the linked DocType and document name. Those methods go
straight to the SQL query builder, which assumes a real ``tab<DocType>`` table. Virtual
DocTypes (such as ``Ascend Product``) have no such table — their data lives in an external
SQL Server, reachable only through their controller — so every link-title lookup raises a
"Table doesn't exist" error and breaks any form that links to them.

Every broken path (form load, the on-demand ``get_link_title`` endpoint, version diffing,
print view, etc.) bottoms out at the same two ``Database`` methods. This module wraps both
so that, when the target DocType is virtual and the filters select rows purely by ``name``
(the shape every title path uses), the value is resolved through the controller instead of
the database. All other calls are delegated to the original implementation untouched.

The wrappers are installed once, from ``bullwheel/__init__.py``, via :func:`apply`.
"""

import threading

import frappe
from frappe.database.database import Database
from frappe.model.base_document import get_controller
from frappe.model.utils import is_virtual_doctype

_PATCHED_FLAG = "_bullwheel_virtual_link_title_patched"

_original_get_value = Database.get_value
_original_get_values = Database.get_values

# Re-entrancy guard. Determining whether a DocType is virtual goes through
# `frappe.get_meta`, which itself issues `frappe.db.get_value("DocType", ...)` — i.e. it
# re-enters the very methods we patch. Without a guard that nested lookup would call
# `is_virtual_doctype` again and recurse forever. The guard is thread-local so concurrent
# requests do not interfere.
_guard = threading.local()


def _is_virtual_link_doctype(doctype):
	"""Return True when `doctype` is a virtual DocType, without recursing through the patch.

	While the virtual check runs (which loads meta via `frappe.db.get_value`), the guard is
	set so any nested call delegates straight to the original implementation.
	"""
	if not isinstance(doctype, str) or getattr(_guard, "active", False):
		return False

	_guard.active = True
	try:
		return is_virtual_doctype(doctype)
	finally:
		_guard.active = False


def _names_from_filters(filters):
	"""Return a list of document names when ``filters`` selects rows purely by ``name``.

	Handles every shape the link-title call sites use:

	* a bare name string — ``"PROD-0001"``
	* a dict keyed only on name — ``{"name": "PROD-0001"}`` or
	  ``{"name": ("in", ["PROD-0001", "PROD-0002"])}``
	* list-format filters referencing only name — ``[["name", "=", "PROD-0001"]]`` or
	  ``[["Ascend Product", "name", "in", [...]]]``
	* Int name (e.g. UPC) - ``194151633641``

	Returns ``None`` for any other shape so the caller falls back to the original,
	table-based implementation untouched. Returning ``None`` (rather than an empty list)
	is deliberate: an empty list is a valid "no names requested" result, whereas ``None``
	means "this is not a name-only lookup — do not intercept".
	"""

	if isinstance(filters, str):
		return [filters]
	

	if isinstance(filters, dict):
		if set(filters) != {"name"}:
			return None
		return _names_from_operator_value(filters["name"])

	if isinstance(filters, (list, tuple)):
		names = []
		for condition in filters:
			fieldname, value = _parse_list_condition(condition)
			if fieldname != "name":
				return None
			extracted = _names_from_operator_value(value)
			if extracted is None:
				return None
			names.extend(extracted)
		return names
	
	if isinstance(filters, int):
		return [str(filters)] # Convert integer names to string

	return None


def _parse_list_condition(condition):
	"""Return ``(fieldname, operator_value)`` from a single list-format filter condition.

	Accepts both ``[fieldname, operator, value]`` and the qualified
	``[doctype, fieldname, operator, value]`` forms. ``operator_value`` is the
	``(operator, value)`` pair, which :func:`_names_from_operator_value` then interprets.
	Returns ``(None, None)`` for any unrecognised shape.
	"""
	if not isinstance(condition, (list, tuple)):
		return None, None

	if len(condition) == 3:
		fieldname, operator, value = condition
	elif len(condition) == 4:
		_doctype, fieldname, operator, value = condition
	else:
		return None, None

	return fieldname, (operator, value)


def _names_from_operator_value(value):
	"""Resolve the document name(s) from the value side of a ``name`` filter.

	``value`` may be a plain name, or an ``(operator, operand)`` pair. Only equality
	(``=``) and membership (``in``) are supported, since those are the only operators the
	link-title paths use. Returns a list of names, or ``None`` for unsupported operators.
	"""
	if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], str):
		operator = value[0].lower()
		operand = value[1]
		if operator == "in":
			return list(operand)
		if operator == "=":
			return [operand]
		return None

	return [value]


def _read_fields(doctype, name, fieldnames):
	"""Return the requested field values for one virtual document, in the requested order.

	Prefers an optional, optimized ``get_link_field_values(name, fieldnames)`` classmethod on
	the controller (which can fetch just the needed columns) when one is defined. Otherwise
	falls back to loading the whole document via ``get_cached_doc`` — which also lets repeated
	lookups within a request hit the document cache, matching the ``cache=True`` intent of the
	title call sites. Returns ``None`` when the record does not exist.
	"""
	controller = get_controller(doctype)
	fast_fetch = getattr(controller, "get_link_field_values", None)
	if callable(fast_fetch):
		values = fast_fetch(name, fieldnames)
		return None if values is None else [values.get(fieldname) for fieldname in fieldnames]

	try:
		document = frappe.get_cached_doc(doctype, name)
	except frappe.DoesNotExistError:
		frappe.clear_last_message()
		return None

	return [document.get(fieldname) for fieldname in fieldnames]


def _patched_get_value(self, doctype, filters=None, fieldname="name", *args, **kwargs):
	"""Virtual-aware replacement for ``Database.get_value`` (single-row semantics)."""
	names = _names_from_filters(filters) if _is_virtual_link_doctype(doctype) else None
	if names is None:
		return _original_get_value(self, doctype, filters, fieldname, *args, **kwargs)

	fieldnames = [fieldname] if isinstance(fieldname, str) else list(fieldname)
	row = _read_fields(doctype, names[0], fieldnames) if names else None
	if row is None:
		return None

	if kwargs.get("pluck"):
		return row[0]
	if kwargs.get("as_dict"):
		return frappe._dict(zip(fieldnames, row, strict=False))
	return row[0] if isinstance(fieldname, str) else row


def _patched_get_values(self, doctype, filters=None, fieldname="name", *args, **kwargs):
	"""Virtual-aware replacement for ``Database.get_values`` (multi-row semantics)."""
	names = _names_from_filters(filters) if _is_virtual_link_doctype(doctype) else None
	if names is None:
		return _original_get_values(self, doctype, filters, fieldname, *args, **kwargs)

	fieldnames = [fieldname] if isinstance(fieldname, str) else list(fieldname)
	rows = [row for name in names if (row := _read_fields(doctype, name, fieldnames)) is not None]

	if kwargs.get("pluck"):
		return [row[0] for row in rows]
	if kwargs.get("as_dict"):
		return [frappe._dict(zip(fieldnames, row, strict=False)) for row in rows]
	return rows


def apply():
	"""Install the virtual-doctype-aware ``get_value`` / ``get_values`` wrappers.

	Idempotent: a flag on the ``Database`` class guards against re-patching, so repeated
	imports (one per process is expected) are harmless.
	"""
	if getattr(Database, _PATCHED_FLAG, False):
		return

	Database.get_value = _patched_get_value
	Database.get_values = _patched_get_values
	setattr(Database, _PATCHED_FLAG, True)
