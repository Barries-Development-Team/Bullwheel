# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for AbstractVirtualDocType's derived constants and query helpers.

Covers order_by resolution (sorting was the recurring bug the framework fixes)
and JOIN clause construction from JOIN_CONFIG.
"""

import uuid
from unittest.mock import MagicMock, patch

from frappe.tests import UnitTestCase

from bullwheel.ascend import virtual_doctype_base
from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class _SampleVirtualDocType(AbstractVirtualDocType):
	"""Minimal concrete subclass — no JOINs, used for ordering and basic derived-constant tests."""

	TABLE_NAME = "Products"
	SCHEMA_CONFIG = {
		"name":               {"sql_column": "ID",          "fieldtype": "Data", "display": "hidden",    "searchable": False},
		"ascend_database_id": {"sql_column": "ID",          "fieldtype": "Data", "display": "hidden",    "searchable": False},
		"description":        {"sql_column": "Description", "fieldtype": "Data", "display": "primary",   "searchable": True},
		"quantity":           {"sql_column": "Quantity",    "fieldtype": "Int",  "display": "secondary", "searchable": False},
		"store_sku":          {"sql_column": "[Store UPC]", "fieldtype": "Data", "display": "secondary", "searchable": True},
	}


class _JoinedVirtualDocType(AbstractVirtualDocType):
	"""Concrete subclass with a JOIN_CONFIG — exercises join_clause() and qualified primary key."""

	TABLE_NAME = "Products"
	JOIN_CONFIG = [
		{"join": "LEFT JOIN", "table": "Categories", "on": "Products.TopicID = Categories.ID"}
	]
	SCHEMA_CONFIG = {
		"name":               {"sql_column": "Products.ID",         "fieldtype": "Data", "display": "hidden",  "searchable": False},
		"ascend_database_id": {"sql_column": "Products.ID",         "fieldtype": "Data", "display": "hidden",  "searchable": False},
		"description":        {"sql_column": "Products.Description", "fieldtype": "Data", "display": "primary", "searchable": True},
		"category":           {"sql_column": "Categories.Topic",     "fieldtype": "Data", "display": None,      "searchable": False},
	}


class _AliasedJoinVirtualDocType(AbstractVirtualDocType):
	"""Concrete subclass with an aliased JOIN — exercises the optional alias key."""

	TABLE_NAME = "Products"
	JOIN_CONFIG = [
		{"join": "LEFT JOIN", "table": "Categories", "alias": "cat", "on": "Products.TopicID = cat.ID"}
	]
	SCHEMA_CONFIG = {
		"name":               {"sql_column": "Products.ID", "fieldtype": "Data", "display": "hidden",  "searchable": False},
		"ascend_database_id": {"sql_column": "Products.ID", "fieldtype": "Data", "display": "hidden",  "searchable": False},
		"category":           {"sql_column": "cat.Topic",   "fieldtype": "Data", "display": "primary", "searchable": False},
	}


class UnitTestVirtualDocTypeBase(UnitTestCase):
	"""Unit tests for AbstractVirtualDocType helpers that need no database."""

	def test_derived_constants(self):
		self.assertEqual(_SampleVirtualDocType.search_columns(), ["Description", "[Store UPC]"])
		# `name` is declared in SCHEMA_CONFIG and resolves to the primary key column.
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


class UnitTestJoinClause(UnitTestCase):
	"""Unit tests for join_clause() construction from JOIN_CONFIG."""

	def test_no_join_config_produces_empty_string(self):
		self.assertEqual(_SampleVirtualDocType.join_clause(), "")

	def test_join_clause_is_built_from_config(self):
		self.assertEqual(
			_JoinedVirtualDocType.join_clause(),
			"LEFT JOIN Categories ON Products.TopicID = Categories.ID",
		)

	def test_join_clause_includes_alias_when_present(self):
		self.assertEqual(
			_AliasedJoinVirtualDocType.join_clause(),
			"LEFT JOIN Categories AS cat ON Products.TopicID = cat.ID",
		)

	def test_qualified_name_column_maps_correctly(self):
		# `name` with a table-qualified sql_column must resolve in field_to_column.
		self.assertEqual(_JoinedVirtualDocType.field_to_column()["name"], "Products.ID")

	def test_multiple_join_entries_concatenated(self):
		class _MultiJoin(AbstractVirtualDocType):
			TABLE_NAME = "Products"
			JOIN_CONFIG = [
				{"join": "LEFT JOIN",  "table": "Categories", "on": "Products.TopicID = Categories.ID"},
				{"join": "INNER JOIN", "table": "Vendors",    "on": "Products.VendorID = Vendors.ID"},
			]
			SCHEMA_CONFIG = {
				"name":               {"sql_column": "Products.ID",       "fieldtype": "Data", "display": "hidden",  "searchable": False},
				"ascend_database_id": {"sql_column": "Products.ID",       "fieldtype": "Data", "display": "hidden",  "searchable": False},
				"category":           {"sql_column": "Categories.Topic",  "fieldtype": "Data", "display": "primary", "searchable": False},
				"vendor":             {"sql_column": "Vendors.Name",      "fieldtype": "Data", "display": None,      "searchable": False},
			}

		self.assertEqual(
			_MultiJoin.join_clause(),
			"LEFT JOIN Categories ON Products.TopicID = Categories.ID"
			" INNER JOIN Vendors ON Products.VendorID = Vendors.ID",
		)


def _mock_ascend_returning(rows, captured):
	"""Return a MagicMock standing in for the MSSQLDatabase context manager.

	Records the executed query and values into `captured` and returns `rows` from sql().
	"""
	connection = MagicMock()

	def sql(query, values, as_dict=False):
		captured["query"] = query
		captured["values"] = values
		captured["as_dict"] = as_dict
		return rows

	connection.sql.side_effect = sql

	database = MagicMock()
	database.__enter__.return_value = connection
	database.__exit__.return_value = False
	return database


class UnitTestGetLinkFieldValues(UnitTestCase):
	"""Unit tests for the optimized single-row, column-limited fetch."""

	def _run(self, doctype_cls, name, fieldnames, rows):
		captured = {}
		database = _mock_ascend_returning(rows, captured)
		with (
			patch.object(virtual_doctype_base, "MSSQLDatabase", return_value=database),
			patch.object(virtual_doctype_base, "get_default_ascend_database", return_value=None),
		):
			result = doctype_cls.get_link_field_values(name, fieldnames)
		return result, captured

	def test_selects_only_requested_columns_by_primary_key(self):
		result, captured = self._run(
			_SampleVirtualDocType, "PROD-1", ["name", "description"],
			[{"name": "PROD-1", "description": "Red Ski"}],
		)
		self.assertEqual(result, {"name": "PROD-1", "description": "Red Ski"})
		self.assertEqual(
			captured["query"],
			"SELECT ID AS name, Description AS description FROM Products WHERE ID = %s",
		)
		self.assertEqual(captured["values"], ("PROD-1",))

	def test_unmapped_field_projects_null(self):
		_result, captured = self._run(
			_SampleVirtualDocType, "PROD-1", ["description", "category"],
			[{"description": "Red Ski", "category": None}],
		)
		self.assertEqual(
			captured["query"],
			"SELECT Description AS description, NULL AS category FROM Products WHERE ID = %s",
		)

	def test_join_clause_is_included(self):
		_result, captured = self._run(
			_JoinedVirtualDocType, "PROD-1", ["name", "category"],
			[{"name": "PROD-1", "category": "Skis"}],
		)
		self.assertEqual(
			captured["query"],
			"SELECT Products.ID AS name, Categories.Topic AS category"
			" FROM Products LEFT JOIN Categories ON Products.TopicID = Categories.ID"
			" WHERE Products.ID = %s",
		)

	def test_uuid_name_is_stringified(self):
		guid = uuid.UUID("12345678-1234-5678-1234-567812345678")
		result, _captured = self._run(
			_SampleVirtualDocType, str(guid), ["name", "description"],
			[{"name": guid, "description": "Red Ski"}],
		)
		self.assertEqual(result["name"], str(guid))

	def test_no_match_returns_none(self):
		result, _captured = self._run(
			_SampleVirtualDocType, "PROD-404", ["description"], []
		)
		self.assertIsNone(result)
