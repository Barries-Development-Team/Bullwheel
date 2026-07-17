# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for the label-printing resolution module.

All tests are pure unit tests with no database dependency: the controller lookup,
meta lookup, and document fetch are each patched at their seam in
bullwheel.label_printing.resolution (the same approach test_virtual_doctype_base.py
takes with MSSQLDatabase).
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from bullwheel.label_printing.exceptions import LabelResolutionError
from bullwheel.label_printing.resolution import resolve_print_items, resolve_to_native


# ─── Test Fixtures ────────────────────────────────────────────────────────────


class _NativeController:
	"""A Native doctype's controller: declares no LABEL_RESOLUTION_FIELD."""
	pass


class _LinkResolvedController:
	"""Vendor Product-shaped: resolves through a plain Link field."""
	LABEL_RESOLUTION_FIELD = 'product'


class _DynamicLinkResolvedController:
	"""Order Receipt Item-shaped: resolves through a Dynamic Link field."""
	LABEL_RESOLUTION_FIELD = 'vpn'


class _NonLinkResolvedController:
	"""Misconfigured: LABEL_RESOLUTION_FIELD names a Data field."""
	LABEL_RESOLUTION_FIELD = 'description'


class _MissingFieldController:
	"""Misconfigured: LABEL_RESOLUTION_FIELD names a field that does not exist."""
	LABEL_RESOLUTION_FIELD = 'nonexistent'


class _CycleControllerA:
	LABEL_RESOLUTION_FIELD = 'linked'


class _CycleControllerB:
	LABEL_RESOLUTION_FIELD = 'linked'


CONTROLLERS = {
	'Ascend Product': _NativeController,
	'New Product': _NativeController,
	'Vendor Product': _LinkResolvedController,
	'Order Receipt Item': _DynamicLinkResolvedController,
	'Broken Doctype': _NonLinkResolvedController,
	'Fieldless Doctype': _MissingFieldController,
	'Cycle A': _CycleControllerA,
	'Cycle B': _CycleControllerB,
}

FIELDS = {
	('Vendor Product', 'product'): frappe._dict(fieldtype='Link', options='Ascend Product', label='Product'),
	('Order Receipt Item', 'vpn'): frappe._dict(fieldtype='Dynamic Link', options='item_type', label='VPN'),
	('Broken Doctype', 'description'): frappe._dict(fieldtype='Data', options=None, label='Description'),
	('Cycle A', 'linked'): frappe._dict(fieldtype='Link', options='Cycle B', label='Linked'),
	('Cycle B', 'linked'): frappe._dict(fieldtype='Link', options='Cycle A', label='Linked'),
}

DOCUMENTS = {
	('Vendor Product', 'VP-001'): {'product': '012345678905'},
	('Vendor Product', 'VP-EMPTY'): {'product': None},
	('Order Receipt Item', 'ORI-001'): {'vpn': 'VP-001', 'item_type': 'Vendor Product'},
	('Order Receipt Item', 'ORI-NEW'): {'vpn': 'NP-001', 'item_type': 'New Product'},
	('Cycle A', 'a1'): {'linked': 'b1'},
	('Cycle B', 'b1'): {'linked': 'a1'},
}


@contextmanager
def _resolution_environment(fetch_call_log=None):
	"""Patch the resolution module's three lookup seams to serve the module-level
	CONTROLLERS / FIELDS / DOCUMENTS fixtures instead of touching Frappe."""

	def fake_get_controller(doctype):
		return CONTROLLERS[doctype]

	def fake_get_meta(doctype):
		meta = MagicMock()
		meta.get_field.side_effect = lambda fieldname: FIELDS.get((doctype, fieldname))
		return meta

	def fake_fetch_document_values(doctype, name, fieldnames):
		if fetch_call_log is not None:
			fetch_call_log.append((doctype, name))
		document = DOCUMENTS.get((doctype, name))
		if document is None:
			return None
		return {fieldname: document.get(fieldname) for fieldname in fieldnames}

	with (
		patch('bullwheel.label_printing.resolution.get_controller', side_effect=fake_get_controller),
		patch('bullwheel.label_printing.resolution.frappe.get_meta', side_effect=fake_get_meta),
		patch('bullwheel.label_printing.resolution.fetch_document_values', side_effect=fake_fetch_document_values),
	):
		yield


# ─── resolve_to_native ────────────────────────────────────────────────────────


class UnitTestResolveToNative(UnitTestCase):

	def test_native_doctype_returns_itself_without_fetching(self):
		fetch_call_log = []
		with _resolution_environment(fetch_call_log):
			result = resolve_to_native('Ascend Product', '012345678905')
		self.assertEqual(result, ('Ascend Product', '012345678905'))
		self.assertEqual(fetch_call_log, [])

	def test_link_field_hops_to_linked_doctype(self):
		with _resolution_environment():
			result = resolve_to_native('Vendor Product', 'VP-001')
		self.assertEqual(result, ('Ascend Product', '012345678905'))

	def test_dynamic_link_field_reads_doctype_from_options_field(self):
		with _resolution_environment():
			result = resolve_to_native('Order Receipt Item', 'ORI-NEW')
		self.assertEqual(result, ('New Product', 'NP-001'))

	def test_two_hop_chain_resolves_through_intermediate_doctype(self):
		with _resolution_environment():
			result = resolve_to_native('Order Receipt Item', 'ORI-001')
		self.assertEqual(result, ('Ascend Product', '012345678905'))

	def test_target_doctype_stops_resolution_early(self):
		"""A doctype the label explicitly targets is printable as-is, even though its
		controller declares a resolution field."""
		fetch_call_log = []
		with _resolution_environment(fetch_call_log):
			result = resolve_to_native('Vendor Product', 'VP-001', target_doctypes=['Vendor Product'])
		self.assertEqual(result, ('Vendor Product', 'VP-001'))
		self.assertEqual(fetch_call_log, [])

	def test_empty_link_value_raises(self):
		with _resolution_environment():
			with self.assertRaises(LabelResolutionError) as context:
				resolve_to_native('Vendor Product', 'VP-EMPTY')
		self.assertIn('VP-EMPTY', str(context.exception))

	def test_missing_document_raises(self):
		with _resolution_environment():
			with self.assertRaises(LabelResolutionError) as context:
				resolve_to_native('Vendor Product', 'VP-MISSING')
		self.assertIn('VP-MISSING', str(context.exception))

	def test_non_link_resolution_field_raises(self):
		with _resolution_environment():
			with self.assertRaises(LabelResolutionError) as context:
				resolve_to_native('Broken Doctype', 'BD-001')
		self.assertIn('Data', str(context.exception))

	def test_nonexistent_resolution_field_raises(self):
		with _resolution_environment():
			with self.assertRaises(LabelResolutionError) as context:
				resolve_to_native('Fieldless Doctype', 'FD-001')
		self.assertIn('nonexistent', str(context.exception))

	def test_cyclic_chain_raises_instead_of_looping(self):
		with _resolution_environment():
			with self.assertRaises(LabelResolutionError):
				resolve_to_native('Cycle A', 'a1')


# ─── resolve_print_items ──────────────────────────────────────────────────────


class UnitTestResolvePrintItems(UnitTestCase):

	def test_mixed_batch_separates_resolved_items_from_failures(self):
		"""One resolvable item, one target mismatch (a New Product dead end), and one
		quantity-0 skip: exactly one triple and exactly one failure message."""
		items = [
			{'doctype': 'Order Receipt Item', 'name': 'ORI-001', 'quantity': 2},
			{'doctype': 'Order Receipt Item', 'name': 'ORI-NEW', 'quantity': 1},
			{'doctype': 'Order Receipt Item', 'name': 'ORI-001', 'quantity': 0},
		]
		with _resolution_environment():
			resolved_items, failure_messages = resolve_print_items(
				items, target_doctypes=['Ascend Product']
			)
		self.assertEqual(resolved_items, [('Ascend Product', '012345678905', 2)])
		self.assertEqual(len(failure_messages), 1)
		self.assertIn('New Product', failure_messages[0])

	def test_empty_target_list_skips_target_validation(self):
		items = [{'doctype': 'Order Receipt Item', 'name': 'ORI-NEW'}]
		with _resolution_environment():
			resolved_items, failure_messages = resolve_print_items(items, target_doctypes=[])
		self.assertEqual(resolved_items, [('New Product', 'NP-001', 1)])
		self.assertEqual(failure_messages, [])

	def test_quantity_defaults_to_one(self):
		items = [{'doctype': 'Ascend Product', 'name': '012345678905'}]
		with _resolution_environment():
			resolved_items, failure_messages = resolve_print_items(items)
		self.assertEqual(resolved_items, [('Ascend Product', '012345678905', 1)])
		self.assertEqual(failure_messages, [])

	def test_default_doctype_fills_items_without_their_own(self):
		items = [{'name': 'VP-001'}]
		with _resolution_environment():
			resolved_items, failure_messages = resolve_print_items(items, default_doctype='Vendor Product')
		self.assertEqual(resolved_items, [('Ascend Product', '012345678905', 1)])
		self.assertEqual(failure_messages, [])

	def test_missing_name_produces_failure_message_not_crash(self):
		items = [{'doctype': 'Ascend Product'}]
		with _resolution_environment():
			resolved_items, failure_messages = resolve_print_items(items)
		self.assertEqual(resolved_items, [])
		self.assertEqual(len(failure_messages), 1)

	def test_missing_doctype_without_default_produces_failure_message(self):
		items = [{'name': 'VP-001'}]
		with _resolution_environment():
			resolved_items, failure_messages = resolve_print_items(items)
		self.assertEqual(resolved_items, [])
		self.assertEqual(len(failure_messages), 1)

	def test_resolution_error_becomes_failure_message(self):
		items = [{'doctype': 'Vendor Product', 'name': 'VP-EMPTY'}]
		with _resolution_environment():
			resolved_items, failure_messages = resolve_print_items(items)
		self.assertEqual(resolved_items, [])
		self.assertEqual(len(failure_messages), 1)
		self.assertIn('VP-EMPTY', failure_messages[0])
