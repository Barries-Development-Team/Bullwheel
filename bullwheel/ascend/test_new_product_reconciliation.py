# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for matching imported New Products to their Ascend Products.

No site or Ascend connection: the New Product lookups, the Vendor Product bulk read and the
database commit/rollback are patched at their seams in bullwheel.ascend.new_product_reconciliation."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from bullwheel.ascend import new_product_reconciliation as reconciliation

MODULE = 'bullwheel.ascend.new_product_reconciliation'


def _candidate(name, vpn, vendor='Acme'):
	return frappe._dict(name=name, vpn=vpn, vendor=vendor)


@contextmanager
def _environment(candidates, vendor_products):
	"""Serve `candidates` as the waiting New Products and `vendor_products` ({name: store sku}) as
	Ascend's imported Vendor Products. Yields (database mock, {new product name: document mock})."""
	database = MagicMock()
	documents = {}

	def get_doc(doctype, name):
		documents.setdefault(name, MagicMock(name=f'New Product {name}'))
		return documents[name]

	with (
		patch(f'{MODULE}.frappe.get_all', return_value=candidates),
		patch(f'{MODULE}.VendorProduct.get_bulk_values', return_value={
			name: frappe._dict(product=sku) for name, sku in vendor_products.items()
		}),
		patch(f'{MODULE}.frappe.get_doc', side_effect=get_doc),
		patch(f'{MODULE}.repoint_references') as repoint,
		patch(f'{MODULE}.adopt_imported_base_products', return_value=0),
		patch.object(frappe.local, 'db', database, create=True),
		patch(f'{MODULE}.frappe.log_error') as log_error,
	):
		yield SimpleNamespace(database=database, documents=documents, repoint=repoint, log_error=log_error)


class UnitTestVendorProductName(UnitTestCase):

	def test_matches_vendor_product_name_expression(self):
		"""Ascend's Vendor Product is named '<part number> (<vendor>)' — VendorProduct.NAME_EXPRESSION."""
		self.assertEqual(reconciliation.vendor_product_name(_candidate('NP-1', 'AB-SKI-1', 'Acme')), 'AB-SKI-1 (Acme)')


class UnitTestReconcilePendingNewProducts(UnitTestCase):

	def test_imported_product_is_linked_repointed_and_committed(self):
		with _environment([_candidate('NP-1', 'AB-SKI-1')], {'AB-SKI-1 (Acme)': 'ABC12345678Z'}) as env:
			result = reconciliation.reconcile_pending_new_products()

		self.assertEqual(result, {'matched': ['NP-1'], 'waiting': 0, 'failed': []})
		env.documents['NP-1'].link_imported_product.assert_called_once_with('ABC12345678Z')
		env.repoint.assert_called_once_with(env.documents['NP-1'].name, 'ABC12345678Z')
		env.database.commit.assert_called()

	def test_product_ascend_does_not_have_yet_keeps_waiting(self):
		with _environment([_candidate('NP-1', 'AB-SKI-1')], {}) as env:
			result = reconciliation.reconcile_pending_new_products()

		self.assertEqual(result, {'matched': [], 'waiting': 1, 'failed': []})
		self.assertEqual(env.documents, {})

	def test_one_failure_rolls_back_only_itself_and_does_not_stop_the_rest(self):
		candidates = [_candidate('NP-1', 'AB-SKI-1'), _candidate('NP-2', 'AB-SKI-2')]
		vendor_products = {'AB-SKI-1 (Acme)': 'AAA', 'AB-SKI-2 (Acme)': 'BBB'}
		with _environment(candidates, vendor_products) as env:
			failing = MagicMock()
			failing.link_imported_product.side_effect = frappe.ValidationError('bad')
			env.documents['NP-1'] = failing
			result = reconciliation.reconcile_pending_new_products()

		self.assertEqual(result, {'matched': ['NP-2'], 'waiting': 0, 'failed': ['NP-1']})
		env.database.rollback.assert_called_once()
		env.log_error.assert_called_once()

	def test_nothing_waiting_makes_no_ascend_query(self):
		with _environment([], {}) as env:
			with patch(f'{MODULE}.VendorProduct.get_bulk_values') as bulk:
				result = reconciliation.reconcile_pending_new_products()

		self.assertEqual(result, {'matched': [], 'waiting': 0, 'failed': []})
		bulk.assert_not_called()
		del env

	def test_only_waiting_statuses_are_considered(self):
		self.assertEqual(reconciliation.MATCHABLE_STATUSES, ['Pending', 'Exported'])


class UnitTestScheduledReconciliation(UnitTestCase):

	def test_unreachable_ascend_is_logged_not_raised(self):
		with (
			patch(f'{MODULE}.reconcile_pending_new_products', side_effect=ConnectionError('down')),
			patch(f'{MODULE}.frappe.log_error') as log_error,
		):
			reconciliation.scheduled_reconciliation()

		log_error.assert_called_once()
