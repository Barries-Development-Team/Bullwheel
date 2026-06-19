# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for the Virtual DocType schema config builders.

These exercise pure functions with no database access, so they run as fast
UnitTestCases. They lock in the contract the framework relies on: NULL-column
handling, bracket-quote preservation, primary-key resolution, search-column
extraction, and SCHEMA_CONFIG validation.
"""

import uuid

from frappe.tests import UnitTestCase

from bullwheel.ascend.schema_config_builder import (
	_bare_column,
	build_field_to_column,
	build_json_schema,
	build_search_columns,
	build_select_clause,
	normalize_record,
	validate_schema_config,
)

# A small fixture covering every interesting case: an explicit name entry (primary
# key), a hidden secondary id field, a NULL placeholder, a bracket-quoted column,
# and mixed searchable flags.
SAMPLE_CONFIG = {
	"name":               {"sql_column": "ID",          "fieldtype": "Data", "display": "hidden",    "searchable": False},
	"ascend_database_id": {"sql_column": "ID",          "fieldtype": "Data", "display": "hidden",    "searchable": False},
	"description":        {"sql_column": "Description", "fieldtype": "Data", "display": "primary",   "searchable": True},
	"category":           {"sql_column": None,          "fieldtype": "Data", "display": None,        "searchable": False},
	"store_sku":          {"sql_column": "[Store UPC]", "fieldtype": "Data", "display": "secondary", "searchable": True},
	"quantity":           {"sql_column": "Quantity",    "fieldtype": "Int",  "display": "secondary", "searchable": False},
}


class UnitTestSchemaConfigBuilder(UnitTestCase):
	"""Unit tests for schema_config_builder pure functions."""

	def test_build_field_to_column_maps_fields_and_meta_name(self):
		field_to_column = build_field_to_column(SAMPLE_CONFIG)
		self.assertEqual(field_to_column["description"], "Description")
		self.assertEqual(field_to_column["store_sku"], "[Store UPC]")
		# `name` is declared in SCHEMA_CONFIG and resolves to the primary key column.
		self.assertEqual(field_to_column["name"], "ID")

	def test_build_field_to_column_omits_null_columns(self):
		field_to_column = build_field_to_column(SAMPLE_CONFIG)
		# `category` has no SQL column, so it must not be filterable.
		self.assertNotIn("category", field_to_column)

	def test_build_select_clause_aliases_and_preserves_brackets(self):
		select_clause = build_select_clause(SAMPLE_CONFIG)
		self.assertIn("ID AS ascend_database_id", select_clause)
		self.assertIn("[Store UPC] AS store_sku", select_clause)
		# NULL placeholder is projected rather than dropped.
		self.assertIn("NULL AS category", select_clause)

	def test_build_search_columns_only_searchable_with_columns(self):
		search_columns = build_search_columns(SAMPLE_CONFIG)
		self.assertEqual(search_columns, ["Description", "[Store UPC]"])

	def test_build_json_schema_flags(self):
		fields = build_json_schema(SAMPLE_CONFIG)
		by_name = {field["fieldname"]: field for field in fields}
		self.assertEqual(by_name["ascend_database_id"].get("hidden"), 1)
		self.assertEqual(by_name["description"].get("in_list_view"), 1)
		self.assertEqual(by_name["description"].get("search_index"), 1)
		self.assertEqual(by_name["quantity"]["fieldtype"], "Int")
		self.assertEqual(by_name["description"]["label"], "Description")

	def test_validate_schema_config_accepts_valid(self):
		self.assertTrue(validate_schema_config(SAMPLE_CONFIG))

	def test_validate_schema_config_rejects_missing_name_entry(self):
		no_name = {"x": {"sql_column": "ID", "fieldtype": "Data", "display": None}}
		with self.assertRaises(ValueError):
			validate_schema_config(no_name)

	def test_validate_schema_config_rejects_null_name_column(self):
		null_name = {"name": {"sql_column": None, "fieldtype": "Data", "display": None}}
		with self.assertRaises(ValueError):
			validate_schema_config(null_name)

	def test_validate_schema_config_rejects_bad_display(self):
		bad = {"name": {"sql_column": "ID", "fieldtype": "Data", "display": None},
		       "x":    {"sql_column": "X",  "fieldtype": "Data", "display": "banner"}}
		with self.assertRaises(ValueError):
			validate_schema_config(bad)

	def test_validate_schema_config_against_discovered_columns(self):
		discovered = ["ID", "Description", "Store UPC", "Quantity"]
		# Valid: every non-NULL column (bracket-stripped) exists in the table.
		self.assertTrue(validate_schema_config(SAMPLE_CONFIG, discovered))

	def test_normalize_record_stringifies_uuids(self):
		# SQL Server uniqueidentifier columns arrive from pymssql as uuid.UUID objects.
		identifier = uuid.UUID("12345678-1234-5678-1234-567812345678")
		parent = uuid.UUID("87654321-4321-8765-4321-876543218765")
		normalized = normalize_record({"name": identifier, "parent_id": parent, "qty": 5, "topic": "Skis"})
		self.assertEqual(normalized["name"], "12345678-1234-5678-1234-567812345678")
		self.assertEqual(normalized["parent_id"], "87654321-4321-8765-4321-876543218765")
		self.assertIsInstance(normalized["name"], str)
		# Non-UUID values pass through untouched.
		self.assertEqual(normalized["qty"], 5)
		self.assertEqual(normalized["topic"], "Skis")

	def test_normalize_record_preserves_none(self):
		self.assertEqual(normalize_record({"category": None})["category"], None)

	def test_validate_schema_config_detects_unknown_column(self):
		typo_config = {
			"ascend_database_id": {"sql_column": "ID", "fieldtype": "Data"},
			"description": {"sql_column": "Descriptionn", "fieldtype": "Data"},  # typo
		}
		discovered = ["ID", "Description"]
		with self.assertRaises(ValueError):
			validate_schema_config(typo_config, "ID", discovered)

	# ─── JOIN-aware tests ────────────────────────────────────────────────────────

	def test_bare_column_strips_table_prefix(self):
		self.assertEqual(_bare_column("Products.ID"), "id")
		self.assertEqual(_bare_column("cat.Topic"), "topic")

	def test_bare_column_strips_brackets(self):
		self.assertEqual(_bare_column("[Store UPC]"), "store upc")
		self.assertEqual(_bare_column("[Year]"), "year")

	def test_bare_column_handles_unqualified(self):
		self.assertEqual(_bare_column("Description"), "description")
		self.assertEqual(_bare_column("ID"), "id")

	def test_bare_column_handles_empty_and_none(self):
		self.assertEqual(_bare_column(""), "")
		self.assertEqual(_bare_column(None), "")

	def test_validate_skips_qualified_columns_when_no_additional_columns_provided(self):
		# Qualified sql_column references should not raise even if discovered_columns
		# only covers the primary table.
		joined_config = {
			"name":               {"sql_column": "Products.ID",          "fieldtype": "Data", "display": "hidden",  "searchable": False},
			"ascend_database_id": {"sql_column": "Products.ID",          "fieldtype": "Data", "display": "hidden",  "searchable": False},
			"description":        {"sql_column": "Products.Description",  "fieldtype": "Data", "display": "primary", "searchable": True},
			"category":           {"sql_column": "Categories.Topic",      "fieldtype": "Data", "display": None,      "searchable": False},
		}
		# Only primary table columns passed — joined columns have no validator.
		discovered = ["ID", "Description"]
		self.assertTrue(validate_schema_config(joined_config, discovered))

	def test_validate_checks_qualified_columns_against_additional_discovered_columns(self):
		# When additional_discovered_columns is provided, qualified references are checked.
		joined_config = {
			"name":     {"sql_column": "Products.ID",      "fieldtype": "Data", "display": "hidden", "searchable": False},
			"category": {"sql_column": "Categories.Topik", "fieldtype": "Data", "display": None,     "searchable": False},  # typo
		}
		discovered = ["ID"]
		additional = ["Topic", "ParentID"]  # correct column names from Categories
		with self.assertRaises(ValueError):
			validate_schema_config(joined_config, discovered, additional)

	def test_validate_accepts_valid_qualified_columns_with_additional(self):
		joined_config = {
			"name":     {"sql_column": "Products.ID",     "fieldtype": "Data", "display": "hidden", "searchable": False},
			"category": {"sql_column": "Categories.Topic","fieldtype": "Data", "display": None,     "searchable": False},
		}
		discovered = ["ID"]
		additional = ["Topic", "ParentID"]
		self.assertTrue(validate_schema_config(joined_config, discovered, additional))
