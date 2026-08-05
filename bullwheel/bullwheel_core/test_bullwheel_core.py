# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for resolve_attributed_ascend_user_id.

Pure unit tests with no database dependency: frappe.db.get_value/get_single_value and
get_controller are each patched at their seam in bullwheel.bullwheel_core, the same
approach test_virtual_doctype_base.py takes with MSSQLDatabase.
"""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from bullwheel.bullwheel_core import resolve_attributed_ascend_user_id
from bullwheel.bullwheel_core.exceptions import AscendAttributionUserNotConfigured


class _StubAscendUserController:
	"""Stands in for the Ascend User controller get_controller resolves at runtime.
	get_values returns whatever this test wired up for the given name."""
	def __init__(self, values_by_name: dict):
		self._values_by_name = values_by_name

	def get_values(self, name, fields):
		return self._values_by_name.get(name)


class UnitTestResolveAttributedAscendUserId(UnitTestCase):

	def test_linked_user_resolves(self):
		"""The common path: the Frappe User has an ascend_user link that resolves cleanly."""
		stub = _StubAscendUserController({'EMP-1': frappe._dict({'id': 'ASCEND-ID-1'})})
		with (
			patch('bullwheel.bullwheel_core.frappe.db.get_value', return_value='EMP-1'),
			patch('bullwheel.bullwheel_core.get_controller', return_value=stub),
		):
			result = resolve_attributed_ascend_user_id('carter@barriessports.com')
		self.assertEqual(result, 'ASCEND-ID-1')

	def test_orphaned_link_falls_back_to_default_user(self):
		"""The User's ascend_user points at an Ascend User that no longer resolves — falls back
		to Bullwheel Settings' default_user rather than raising immediately."""
		stub = _StubAscendUserController({'EMP-DEFAULT': frappe._dict({'id': 'ASCEND-ID-DEFAULT'})})
		with (
			patch('bullwheel.bullwheel_core.frappe.db.get_value', return_value='EMP-GHOST'),
			patch('bullwheel.bullwheel_core.frappe.db.get_single_value', return_value='EMP-DEFAULT'),
			patch('bullwheel.bullwheel_core.get_controller', return_value=stub),
		):
			result = resolve_attributed_ascend_user_id('carter@barriessports.com')
		self.assertEqual(result, 'ASCEND-ID-DEFAULT')

	def test_no_link_falls_back_to_default_user(self):
		"""A User with no ascend_user link at all goes straight to the fallback."""
		stub = _StubAscendUserController({'EMP-DEFAULT': frappe._dict({'id': 'ASCEND-ID-DEFAULT'})})
		with (
			patch('bullwheel.bullwheel_core.frappe.db.get_value', return_value=None),
			patch('bullwheel.bullwheel_core.frappe.db.get_single_value', return_value='EMP-DEFAULT'),
			patch('bullwheel.bullwheel_core.get_controller', return_value=stub),
		):
			result = resolve_attributed_ascend_user_id('guest@barriessports.com')
		self.assertEqual(result, 'ASCEND-ID-DEFAULT')

	def test_both_unresolved_raises(self):
		"""No link and no usable default_user must raise rather than return None (the caller
		binds this value straight into a FK column — a silent None is a worse failure mode)."""
		stub = _StubAscendUserController({})
		with (
			patch('bullwheel.bullwheel_core.frappe.db.get_value', return_value=None),
			patch('bullwheel.bullwheel_core.frappe.db.get_single_value', return_value=None),
			patch('bullwheel.bullwheel_core.get_controller', return_value=stub),
		):
			with self.assertRaises(AscendAttributionUserNotConfigured):
				resolve_attributed_ascend_user_id('guest@barriessports.com')

	def test_default_user_also_orphaned_raises(self):
		"""The link is orphaned AND the configured default_user is itself unresolvable."""
		stub = _StubAscendUserController({})
		with (
			patch('bullwheel.bullwheel_core.frappe.db.get_value', return_value='EMP-GHOST'),
			patch('bullwheel.bullwheel_core.frappe.db.get_single_value', return_value='EMP-ALSO-GHOST'),
			patch('bullwheel.bullwheel_core.get_controller', return_value=stub),
		):
			with self.assertRaises(AscendAttributionUserNotConfigured):
				resolve_attributed_ascend_user_id('guest@barriessports.com')

	def test_empty_frappe_user_skips_link_lookup_and_falls_back(self):
		"""A falsy frappe_user (shouldn't normally happen, but defensively handled) never
		queries User.ascend_user and goes straight to the default_user fallback."""
		stub = _StubAscendUserController({'EMP-DEFAULT': frappe._dict({'id': 'ASCEND-ID-DEFAULT'})})
		with (
			patch('bullwheel.bullwheel_core.frappe.db.get_value') as fake_get_value,
			patch('bullwheel.bullwheel_core.frappe.db.get_single_value', return_value='EMP-DEFAULT'),
			patch('bullwheel.bullwheel_core.get_controller', return_value=stub),
		):
			result = resolve_attributed_ascend_user_id(None)
		fake_get_value.assert_not_called()
		self.assertEqual(result, 'ASCEND-ID-DEFAULT')
