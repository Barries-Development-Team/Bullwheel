# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for AbstractVirtualDocType's order_by resolution.

Sorting was the recurring bug the framework fixes: list-view column-header
clicks must translate Frappe's order_by string into the right SQL column and
direction. These tests lock that translation down, including the awkward case of
a DocType name containing a space (`tabAscend Product`), which breaks naive
whitespace parsing.
"""

from frappe.tests import UnitTestCase

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class _SampleVirtualDocType(AbstractVirtualDocType):
	"""Minimal concrete subclass used only to exercise classmethods (never persisted)."""

	TABLE_NAME = "Products"
	PRIMARY_KEY_COLUMN = "ID"
	SCHEMA_CONFIG = {
		"ascend_database_id": {"sql_column": "ID", "fieldtype": "Data", "display": "hidden", "searchable": False},
		"description": {"sql_column": "Description", "fieldtype": "Data", "display": "primary", "searchable": True},
		"quantity": {"sql_column": "Quantity", "fieldtype": "Int", "display": "secondary", "searchable": False},
		"store_sku": {"sql_column": "[Store UPC]", "fieldtype": "Data", "display": "secondary", "searchable": True},
	}


class UnitTestVirtualDocTypeBase(UnitTestCase):
	"""Unit tests for AbstractVirtualDocType helpers that need no database."""

	def test_derived_constants(self):
		self.assertEqual(_SampleVirtualDocType.search_columns(), ["Description", "[Store UPC]"])
		self.assertEqual(_SampleVirtualDocType.primary_key_field(), "ascend_database_id")
		self.assertEqual(_SampleVirtualDocType.field_to_column()["name"], "ID")

	def test_order_by_fully_qualified_with_spaced_doctype(self):
		# DocType name "Ascend Product" contains a space inside the backticks.
		self.assertEqual(
			_SampleVirtualDocType._resolve_order_by("`tabAscend Product`.`description` asc"),
			("Description", "ASC"),
		)
		self.assertEqual(
			_SampleVirtualDocType._resolve_order_by("`tabAscend Product`.`quantity` desc"),
			("Quantity", "DESC"),
		)

	def test_order_by_unmapped_field_falls_back(self):
		# `creation` has no Ascend column; AscendDatabase then defaults to the primary key.
		self.assertEqual(
			_SampleVirtualDocType._resolve_order_by("`tabAscend Product`.`creation` desc"),
			(None, "DESC"),
		)

	def test_order_by_bare_field(self):
		self.assertEqual(_SampleVirtualDocType._resolve_order_by("description asc"), ("Description", "ASC"))
		self.assertEqual(_SampleVirtualDocType._resolve_order_by("quantity"), ("Quantity", "ASC"))

	def test_order_by_empty_and_none(self):
		self.assertEqual(_SampleVirtualDocType._resolve_order_by(""), (None, "ASC"))
		self.assertEqual(_SampleVirtualDocType._resolve_order_by(None), (None, "ASC"))

	def test_order_by_only_first_clause_honored(self):
		self.assertEqual(
			_SampleVirtualDocType._resolve_order_by(
				"`tabAscend Product`.`quantity` desc, `tabAscend Product`.`description` asc"
			),
			("Quantity", "DESC"),
		)
