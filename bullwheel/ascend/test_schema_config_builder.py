# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for the Virtual DocType schema config builders.

These exercise pure functions with no database access, so they run as fast
UnitTestCases. They lock in the contract the framework relies on: NULL-column
handling, bracket-quote preservation, primary-key resolution, search-column
extraction, and SCHEMA_CONFIG validation.
"""

from frappe.tests import UnitTestCase

from bullwheel.ascend.schema_config_builder import (
	build_field_to_column,
	build_json_schema,
	build_search_columns,
	build_select_clause,
	find_primary_key_field,
	validate_schema_config,
)

# A small fixture covering every interesting case: a hidden primary key, a NULL
# placeholder column, a bracket-quoted column with a space, and mixed searchable.
SAMPLE_CONFIG = {
	"ascend_database_id": {"sql_column": "ID",          "fieldtype": "Data", "display": "hidden",    "searchable": False},
	"description":        {"sql_column": "Description", "fieldtype": "Data", "display": "primary",   "searchable": True},
	"category":          {"sql_column": None,          "fieldtype": "Data", "display": None,        "searchable": False},
	"store_sku":         {"sql_column": "[Store UPC]", "fieldtype": "Data", "display": "secondary", "searchable": True},
	"quantity":          {"sql_column": "Quantity",    "fieldtype": "Int",  "display": "secondary", "searchable": False},
}
PRIMARY_KEY_COLUMN = "ID"


class UnitTestSchemaConfigBuilder(UnitTestCase):
	"""Unit tests for schema_config_builder pure functions."""

	def test_build_field_to_column_maps_fields_and_meta_name(self):
		field_to_column = build_field_to_column(SAMPLE_CONFIG, PRIMARY_KEY_COLUMN)
		self.assertEqual(field_to_column["description"], "Description")
		self.assertEqual(field_to_column["store_sku"], "[Store UPC]")
		# Frappe meta-field `name` resolves to the primary key column.
		self.assertEqual(field_to_column["name"], "ID")

	def test_build_field_to_column_omits_null_columns(self):
		field_to_column = build_field_to_column(SAMPLE_CONFIG, PRIMARY_KEY_COLUMN)
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

	def test_find_primary_key_field(self):
		self.assertEqual(find_primary_key_field(SAMPLE_CONFIG, PRIMARY_KEY_COLUMN), "ascend_database_id")

	def test_find_primary_key_field_requires_exactly_one(self):
		ambiguous = {
			"a": {"sql_column": "ID", "fieldtype": "Data"},
			"b": {"sql_column": "ID", "fieldtype": "Data"},
		}
		with self.assertRaises(ValueError):
			find_primary_key_field(ambiguous, "ID")

	def test_build_json_schema_flags(self):
		fields = build_json_schema(SAMPLE_CONFIG)
		by_name = {field["fieldname"]: field for field in fields}
		self.assertEqual(by_name["ascend_database_id"].get("hidden"), 1)
		self.assertEqual(by_name["description"].get("in_list_view"), 1)
		self.assertEqual(by_name["description"].get("search_index"), 1)
		self.assertEqual(by_name["quantity"]["fieldtype"], "Int")
		self.assertEqual(by_name["description"]["label"], "Description")

	def test_validate_schema_config_accepts_valid(self):
		self.assertTrue(validate_schema_config(SAMPLE_CONFIG, PRIMARY_KEY_COLUMN))

	def test_validate_schema_config_rejects_bad_display(self):
		bad = {"x": {"sql_column": "ID", "fieldtype": "Data", "display": "banner"}}
		with self.assertRaises(ValueError):
			validate_schema_config(bad, "ID")

	def test_validate_schema_config_against_discovered_columns(self):
		discovered = ["ID", "Description", "Store UPC", "Quantity"]
		# Valid: every non-NULL column (bracket-stripped) exists in the table.
		self.assertTrue(validate_schema_config(SAMPLE_CONFIG, PRIMARY_KEY_COLUMN, discovered))

	def test_validate_schema_config_detects_unknown_column(self):
		typo_config = {
			"ascend_database_id": {"sql_column": "ID", "fieldtype": "Data"},
			"description": {"sql_column": "Descriptionn", "fieldtype": "Data"},  # typo
		}
		discovered = ["ID", "Description"]
		with self.assertRaises(ValueError):
			validate_schema_config(typo_config, "ID", discovered)
