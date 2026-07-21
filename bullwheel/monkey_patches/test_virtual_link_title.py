# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for the virtual-DocType link-title patch.

Covers filter-shape parsing (`_names_from_filters`) and the return-shape parity of the
patched `get_value` / `get_values` wrappers against a stubbed virtual controller. No
database access is required — the controller lookup is mocked.
"""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from bullwheel.monkey_patches import virtual_link_title

_VIRTUAL_DOCTYPE = "Ascend Product"

# Stub data the fake controller returns, keyed by document name.
_RECORDS = {
	"PROD-1": {"name": "PROD-1", "description": "Red Ski", "quantity": 3},
	"PROD-2": {"name": "PROD-2", "description": "Blue Ski", "quantity": 7},
}


class _PlainController:
	"""A virtual controller with no optimized fast path — forces the get_cached_doc fallback."""


def _fake_get_cached_doc(doctype, name):
	"""Stand in for frappe.get_cached_doc against the in-memory _RECORDS table."""
	if name not in _RECORDS:
		raise frappe.DoesNotExistError(f"{doctype} '{name}' not found.")
	return frappe._dict(_RECORDS[name])


class UnitTestNamesFromFilters(UnitTestCase):
	"""Filter shapes that the link-title paths actually produce."""

	def test_bare_name_string(self):
		self.assertEqual(virtual_link_title._names_from_filters("PROD-1"), ["PROD-1"])

	def test_dict_name_equality(self):
		self.assertEqual(virtual_link_title._names_from_filters({"name": "PROD-1"}), ["PROD-1"])

	def test_dict_name_in_tuple(self):
		self.assertEqual(
			virtual_link_title._names_from_filters({"name": ("in", ["PROD-1", "PROD-2"])}),
			["PROD-1", "PROD-2"],
		)

	def test_dict_name_in_list_operator(self):
		self.assertEqual(
			virtual_link_title._names_from_filters({"name": ["in", ["PROD-1", "PROD-2"]]}),
			["PROD-1", "PROD-2"],
		)

	def test_dict_name_explicit_equality_operator(self):
		self.assertEqual(virtual_link_title._names_from_filters({"name": ("=", "PROD-1")}), ["PROD-1"])

	def test_list_condition_three_element(self):
		self.assertEqual(virtual_link_title._names_from_filters([["name", "=", "PROD-1"]]), ["PROD-1"])

	def test_list_condition_four_element_qualified(self):
		self.assertEqual(
			virtual_link_title._names_from_filters([[_VIRTUAL_DOCTYPE, "name", "in", ["PROD-1", "PROD-2"]]]),
			["PROD-1", "PROD-2"],
		)

	def test_non_name_dict_returns_none(self):
		self.assertIsNone(virtual_link_title._names_from_filters({"description": "Red Ski"}))

	def test_mixed_dict_returns_none(self):
		self.assertIsNone(virtual_link_title._names_from_filters({"name": "PROD-1", "quantity": 3}))

	def test_non_name_list_condition_returns_none(self):
		self.assertIsNone(virtual_link_title._names_from_filters([["description", "=", "Red Ski"]]))

	def test_unsupported_operator_returns_none(self):
		self.assertIsNone(virtual_link_title._names_from_filters({"name": ("like", "%ski%")}))


class UnitTestPatchedGetValue(UnitTestCase):
	"""Return-shape parity for the patched single-row get_value."""

	def setUp(self):
		self._is_virtual = patch.object(virtual_link_title, "is_virtual_doctype", return_value=True)
		self._controller = patch.object(virtual_link_title, "get_controller", return_value=_PlainController)
		self._cached_doc = patch.object(frappe, "get_cached_doc", side_effect=_fake_get_cached_doc)
		self._is_virtual.start()
		self._controller.start()
		self._cached_doc.start()

	def tearDown(self):
		self._is_virtual.stop()
		self._controller.stop()
		self._cached_doc.stop()

	def _get_value(self, *args, **kwargs):
		# `self` (the Database instance) is unused on the virtual branch.
		return virtual_link_title._patched_get_value(None, *args, **kwargs)

	def test_single_string_fieldname_returns_scalar(self):
		self.assertEqual(self._get_value(_VIRTUAL_DOCTYPE, "PROD-1", "description"), "Red Ski")

	def test_list_fieldname_returns_row(self):
		self.assertEqual(
			self._get_value(_VIRTUAL_DOCTYPE, "PROD-1", ["name", "description"]),
			["PROD-1", "Red Ski"],
		)

	def test_as_dict_returns_dict(self):
		self.assertEqual(
			self._get_value(_VIRTUAL_DOCTYPE, "PROD-1", ["name", "description"], as_dict=True),
			{"name": "PROD-1", "description": "Red Ski"},
		)

	def test_pluck_returns_scalar(self):
		self.assertEqual(
			self._get_value(_VIRTUAL_DOCTYPE, "PROD-1", ["description", "quantity"], pluck=True),
			"Red Ski",
		)

	def test_missing_record_returns_none(self):
		self.assertIsNone(self._get_value(_VIRTUAL_DOCTYPE, "PROD-404", "description"))

	def test_extra_keyword_arguments_are_tolerated(self):
		# The title call sites pass cache=True, order_by=None, etc.
		self.assertEqual(
			self._get_value(_VIRTUAL_DOCTYPE, "PROD-1", "description", cache=True, order_by=None),
			"Red Ski",
		)


class UnitTestPatchedGetValues(UnitTestCase):
	"""Return-shape parity for the patched multi-row get_values."""

	def setUp(self):
		self._is_virtual = patch.object(virtual_link_title, "is_virtual_doctype", return_value=True)
		self._controller = patch.object(virtual_link_title, "get_controller", return_value=_PlainController)
		self._cached_doc = patch.object(frappe, "get_cached_doc", side_effect=_fake_get_cached_doc)
		self._is_virtual.start()
		self._controller.start()
		self._cached_doc.start()

	def tearDown(self):
		self._is_virtual.stop()
		self._controller.stop()
		self._cached_doc.stop()

	def _get_values(self, *args, **kwargs):
		return virtual_link_title._patched_get_values(None, *args, **kwargs)

	def test_in_filter_returns_rows(self):
		# Mirrors version.py: get_values(dt, {"name": ("in", (...))}, ["name", title_field]).
		self.assertEqual(
			self._get_values(_VIRTUAL_DOCTYPE, {"name": ("in", ["PROD-1", "PROD-2"])}, ["name", "description"]),
			[["PROD-1", "Red Ski"], ["PROD-2", "Blue Ski"]],
		)

	def test_as_dict_returns_dicts(self):
		self.assertEqual(
			self._get_values(
				_VIRTUAL_DOCTYPE, {"name": ("in", ["PROD-1", "PROD-2"])}, ["name", "description"], as_dict=True
			),
			[{"name": "PROD-1", "description": "Red Ski"}, {"name": "PROD-2", "description": "Blue Ski"}],
		)

	def test_pluck_returns_scalars(self):
		self.assertEqual(
			self._get_values(_VIRTUAL_DOCTYPE, {"name": ("in", ["PROD-1", "PROD-2"])}, "description", pluck=True),
			["Red Ski", "Blue Ski"],
		)

	def test_missing_records_are_skipped(self):
		self.assertEqual(
			self._get_values(_VIRTUAL_DOCTYPE, {"name": ("in", ["PROD-1", "PROD-404"])}, ["name", "description"]),
			[["PROD-1", "Red Ski"]],
		)


class UnitTestReadFields(UnitTestCase):
	"""`_read_fields` prefers the controller's optimized fast path when one exists."""

	def test_uses_get_link_field_values_when_present(self):
		class _FastController:
			calls = []

			@classmethod
			def get_link_field_values(cls, name, fieldnames):
				cls.calls.append((name, list(fieldnames)))
				return {"name": name, "description": "Red Ski"}

		with (
			patch.object(virtual_link_title, "get_controller", return_value=_FastController),
			patch.object(frappe, "get_cached_doc", side_effect=AssertionError("fallback used")) as cached,
		):
			row = virtual_link_title._read_fields(_VIRTUAL_DOCTYPE, "PROD-1", ["name", "description"])

		self.assertEqual(row, ["PROD-1", "Red Ski"])
		self.assertEqual(_FastController.calls, [("PROD-1", ["name", "description"])])
		cached.assert_not_called()

	def test_fast_path_missing_record_returns_none(self):
		class _FastController:
			@classmethod
			def get_link_field_values(cls, name, fieldnames):
				return None

		with patch.object(virtual_link_title, "get_controller", return_value=_FastController):
			self.assertIsNone(virtual_link_title._read_fields(_VIRTUAL_DOCTYPE, "PROD-404", ["description"]))

	def test_falls_back_to_cached_doc_without_fast_path(self):
		with (
			patch.object(virtual_link_title, "get_controller", return_value=_PlainController),
			patch.object(frappe, "get_cached_doc", side_effect=_fake_get_cached_doc),
		):
			row = virtual_link_title._read_fields(_VIRTUAL_DOCTYPE, "PROD-1", ["name", "description"])

		self.assertEqual(row, ["PROD-1", "Red Ski"])


class UnitTestDelegation(UnitTestCase):
	"""Non-virtual and non-name lookups must fall through to the original implementation."""

	def test_non_virtual_doctype_delegates(self):
		sentinel = object()
		with (
			patch.object(virtual_link_title, "is_virtual_doctype", return_value=False),
			patch.object(virtual_link_title, "_original_get_value", return_value=sentinel) as original,
		):
			result = virtual_link_title._patched_get_value(None, "Item", "ITEM-1", "item_name")

		self.assertIs(result, sentinel)
		original.assert_called_once()

	def test_virtual_non_name_filter_delegates(self):
		sentinel = object()
		with (
			patch.object(virtual_link_title, "is_virtual_doctype", return_value=True),
			patch.object(virtual_link_title, "_original_get_value", return_value=sentinel) as original,
		):
			result = virtual_link_title._patched_get_value(
				None, _VIRTUAL_DOCTYPE, {"description": "Red Ski"}, "name"
			)

		self.assertIs(result, sentinel)
		original.assert_called_once()
