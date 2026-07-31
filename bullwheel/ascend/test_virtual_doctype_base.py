# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for AbstractVirtualDocType's query builders and schema validation.

All tests are pure unit tests with no SQL Server dependency (get_count is exercised
against a mocked MSSQLDatabase). SCHEMA_CONFIG uses the field config format: every
entry is a dict of per-field options, with the table defaulting to TABLE_NAME and
column names bracket-quoted by the framework. See schema_config.py for the contract.
"""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType
from bullwheel.ascend.schema_config import normalize_schema_config, quote_column
from bullwheel.ascend.validate_virtual_doctypes import (
	validate_schema_config,
	autoname_mismatch_reason,
	_linked_id_field_structural_problems,
)


# ─── Test Fixtures ────────────────────────────────────────────────────────────


class _SimpleVirtualDocType(AbstractVirtualDocType):
	"""No JOINs — every column defaults to TABLE_NAME."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	SCHEMA_CONFIG = {
		'name':        {'column': 'ID'},
		'description': {'column': 'Description'},
		'quantity':    {'column': 'Quantity'},
		'store_sku':   {'column': 'Store UPC'},
	}


class _AliasedJoinVirtualDocType(AbstractVirtualDocType):
	"""JOIN with an alias — the joined field names that alias as its table."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	JOIN_CONFIG = [
		{'join': 'LEFT JOIN', 'table': 'Categories', 'alias': 'cat', 'on': 'Products.TopicID = cat.ID'}
	]
	SCHEMA_CONFIG = {
		'name':        {'column': 'ID'},
		'description': {'column': 'Description'},
		'category':    {'table': 'cat', 'column': 'Topic'},
	}


class _UnaliasedJoinVirtualDocType(AbstractVirtualDocType):
	"""JOIN without an alias — no AS clause should appear in the output."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	JOIN_CONFIG = [
		{'join': 'LEFT JOIN', 'table': 'Categories', 'on': 'Products.TopicID = Categories.ID'}
	]
	SCHEMA_CONFIG = {
		'name':        {'column': 'ID'},
		'description': {'column': 'Description'},
	}


class _NameExpressionVirtualDocType(AbstractVirtualDocType):
	"""Primary key is a computed SQL expression; 'name' is omitted from SCHEMA_CONFIG."""
	TABLE_NAME = "Things"
	SHOW_FIELD_WARNINGS = False
	NAME_EXPRESSION = "CONCAT(StyleNumber, '-', Size)"
	SCHEMA_CONFIG = {
		'description': {'column': 'Description'},
		'size':        {'column': 'Size'},
	}


class _NameExpressionJoinVirtualDocType(AbstractVirtualDocType):
	"""NAME_EXPRESSION that references a declared join alias and the primary table."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	JOIN_CONFIG = [
		{'join': 'LEFT JOIN', 'table': 'Categories', 'alias': 'cat', 'on': 'Products.TopicID = cat.ID'}
	]
	NAME_EXPRESSION = "CONCAT(Products.ID, '-', cat.Topic)"
	SCHEMA_CONFIG = {
		'description': {'column': 'Description'},
	}


class _AltNameVirtualDocType(AbstractVirtualDocType):
	"""'name' filters widen across every field flagged 'alternate_name'."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	SCHEMA_CONFIG = {
		'name':        {'column': 'Store UPC'},
		'upc':         {'column': 'UPC', 'alternate_name': True},
		'description': {'column': 'Description'},
	}


# ─── validate_schema_config ───────────────────────────────────────────────────


class UnitTestValidateSchemaConfig(UnitTestCase):

	def test_valid_schema_returns_true(self):
		self.assertTrue(validate_schema_config(_SimpleVirtualDocType))

	def test_empty_schema_raises(self):
		class _Empty(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {}
		with self.assertRaises(ValueError):
			validate_schema_config(_Empty)

	def test_none_schema_raises(self):
		class _NullSchema(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = None
		with self.assertRaises(ValueError):
			validate_schema_config(_NullSchema)

	def test_missing_name_entry_raises(self):
		class _NoName(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {'description': {'column': 'Description'}}
		with self.assertRaises(ValueError):
			validate_schema_config(_NoName)

	def test_null_name_column_raises(self):
		class _NullName(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {'name': None}
		with self.assertRaises(ValueError):
			validate_schema_config(_NullName)

	def test_flat_string_value_raises(self):
		"""A bare string (the older flat SCHEMA_CONFIG format accidentally used) must be caught
		rather than silently treated as a column name."""
		class _StringValue(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {
				'name':        {'column': 'ID'},
				'description': 'T.Description',
			}
		with self.assertRaises(ValueError):
			validate_schema_config(_StringValue)

	def test_alternate_name_on_name_field_raises(self):
		"""'name' is what the alternate-name fields are alternatives to; flagging it would widen
		a name filter into a meaningless self-OR."""
		class _AlternateNameOnName(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {'name': {'column': 'ID', 'alternate_name': True}}
		with self.assertRaises(ValueError) as context:
			validate_schema_config(_AlternateNameOnName)
		self.assertIn('alternate_name', str(context.exception))

	def test_alternate_name_fields_pass(self):
		self.assertTrue(validate_schema_config(_AltNameVirtualDocType))

	def test_discovered_columns_valid_passes(self):
		self.assertTrue(
			validate_schema_config(
				_SimpleVirtualDocType,
				discovered_columns=['ID', 'Description', 'Quantity', 'Store UPC']
			)
		)

	def test_discovered_columns_missing_column_raises(self):
		with self.assertRaises(ValueError):
			validate_schema_config(
				_SimpleVirtualDocType,
				discovered_columns=['ID', 'Description']  # Quantity and Store UPC absent
			)

	def test_join_qualified_columns_skipped_without_additional_discovered(self):
		"""JOIN-qualified columns (e.g. cat.Topic) are not checked when
		additional_discovered_columns is not provided."""
		self.assertTrue(
			validate_schema_config(
				_AliasedJoinVirtualDocType,
				discovered_columns=['ID', 'Description', 'Topic']
			)
		)

	def test_join_qualified_columns_checked_against_additional_discovered(self):
		with self.assertRaises(ValueError):
			validate_schema_config(
				_AliasedJoinVirtualDocType,
				additional_discovered_columns=['ID', 'Description']  # Topic (for cat.Topic) absent
			)

	def test_primary_qualified_columns_checked_against_primary_schema(self):
		"""Regression: a column qualified with the primary table (Products.ID) must be
		validated against the primary table's columns, not the joined tables'."""
		self.assertTrue(
			validate_schema_config(
				_AliasedJoinVirtualDocType,
				discovered_columns=['ID', 'Description'],
				additional_discovered_columns=['ID', 'Topic'],
			)
		)

	def test_primary_qualified_column_missing_from_primary_schema_raises(self):
		with self.assertRaises(ValueError):
			validate_schema_config(
				_AliasedJoinVirtualDocType,
				discovered_columns=['ID'],  # Description absent from the primary table
				additional_discovered_columns=['ID', 'Topic'],
			)

	def test_undeclared_column_qualifier_raises(self):
		"""A field whose table is not TABLE_NAME nor in JOIN_CONFIG is a structural error,
		caught without any introspected columns."""
		class _UndeclaredColumnQualifier(AbstractVirtualDocType):
			TABLE_NAME = "Products"
			SCHEMA_CONFIG = {
				'name':     {'column': 'ID'},
				'category': {'table': 'cat', 'column': 'Topic'},  # no JOIN_CONFIG declares 'cat'
			}
		with self.assertRaises(ValueError) as context:
			validate_schema_config(_UndeclaredColumnQualifier)
		self.assertIn('cat', str(context.exception))

	def test_unknown_field_config_key_raises(self):
		"""The main new failure mode of a nested config: a misspelled option key must be named
		rather than silently leaving the field unmapped."""
		class _TypoKey(AbstractVirtualDocType):
			TABLE_NAME = "Products"
			SCHEMA_CONFIG = {
				'name':        {'column': 'ID'},
				'description': {'colum': 'Description'},  # typo
			}
		with self.assertRaises(ValueError) as context:
			validate_schema_config(_TypoKey)
		self.assertIn('colum', str(context.exception))
		self.assertIn('description', str(context.exception))


# ─── autoname_mismatch_reason ──────────────────────────────────────────────────


class UnitTestAutonameMismatchReason(UnitTestCase):

	def test_non_field_autoname_is_always_safe(self):
		"""Only a literal 'field:' autoname triggers Frappe's _sync_autoname_field — Prompt,
		hash, naming_series, etc. never touch this path."""
		self.assertIsNone(autoname_mismatch_reason(_SimpleVirtualDocType, 'Prompt'))
		self.assertIsNone(autoname_mismatch_reason(_SimpleVirtualDocType, 'hash'))
		self.assertIsNone(autoname_mismatch_reason(_SimpleVirtualDocType, None))
		self.assertIsNone(autoname_mismatch_reason(_SimpleVirtualDocType, ''))

	def test_field_autoname_matching_name_column_is_safe(self):
		"""Mirrors AscendProduct's real shape: 'name' and 'store_sku' both map to the same
		underlying column, so _sync_autoname_field's self-check is always a harmless no-op."""
		class _MirroredNameField(AbstractVirtualDocType):
			TABLE_NAME = "Products"
			SCHEMA_CONFIG = {
				'name':      {'column': 'Store UPC'},
				'store_sku': {'column': 'Store UPC'},
			}
		self.assertIsNone(autoname_mismatch_reason(_MirroredNameField, 'field:store_sku'))

	def test_field_autoname_mismatched_column_is_unsafe(self):
		"""Regression: the exact real-world incident — autoname='field:description' on
		AscendProduct-shaped SCHEMA_CONFIG silently overwrote Description with the SKU."""
		reason = autoname_mismatch_reason(_SimpleVirtualDocType, 'field:description')
		self.assertIsNotNone(reason)
		self.assertIn('description', reason)

	def test_field_autoname_pointing_at_unmapped_field_is_unsafe(self):
		reason = autoname_mismatch_reason(_SimpleVirtualDocType, 'field:nonexistent_field')
		self.assertIsNotNone(reason)

	def test_field_autoname_with_name_expression_is_always_unsafe(self):
		"""A computed NAME_EXPRESSION has no literal 'name' column at all, so any 'field:'
		autoname is unsafe regardless of what it points at."""
		reason = autoname_mismatch_reason(_NameExpressionVirtualDocType, 'field:description')
		self.assertIsNotNone(reason)
		self.assertIn('NAME_EXPRESSION', reason)


# ─── validate_schema_config — NAME_EXPRESSION ─────────────────────────────────


class UnitTestValidateNameExpression(UnitTestCase):

	def test_name_expression_without_name_entry_passes(self):
		"""A NAME_EXPRESSION satisfies the primary-key requirement even when SCHEMA_CONFIG omits 'name'."""
		self.assertTrue(validate_schema_config(_NameExpressionVirtualDocType))

	def test_name_expression_skips_column_existence_check(self):
		"""The expression is not a plain column, so it isn't checked against discovered_columns —
		only the other mapped fields are."""
		self.assertTrue(
			validate_schema_config(
				_NameExpressionVirtualDocType,
				discovered_columns=['Description', 'Size']  # deliberately omits StyleNumber
			)
		)

	def test_neither_name_nor_expression_raises(self):
		class _NoPrimaryKey(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {'description': {'column': 'Description'}}
		with self.assertRaises(ValueError):
			validate_schema_config(_NoPrimaryKey)

	def test_non_string_name_expression_raises(self):
		class _BadExpression(AbstractVirtualDocType):
			TABLE_NAME = "T"
			NAME_EXPRESSION = 123
			SCHEMA_CONFIG = {'description': {'column': 'Description'}}
		with self.assertRaises(ValueError):
			validate_schema_config(_BadExpression)

	def test_declared_qualifiers_pass(self):
		"""Qualifiers resolving to TABLE_NAME or a JOIN_CONFIG alias are accepted."""
		self.assertTrue(validate_schema_config(_NameExpressionJoinVirtualDocType))

	def test_undeclared_qualifier_raises(self):
		class _UndeclaredAlias(AbstractVirtualDocType):
			TABLE_NAME = "Products"
			NAME_EXPRESSION = "CONCAT(Products.ID, '-', missing.Topic)"
			SCHEMA_CONFIG = {'description': {'column': 'Description'}}
		with self.assertRaises(ValueError) as context:
			validate_schema_config(_UndeclaredAlias)
		self.assertIn('missing', str(context.exception))

	def test_dots_inside_brackets_and_literals_do_not_false_positive(self):
		"""Dots inside bracket-quoted names or string literals must not register as qualifiers."""
		class _DottedLiteral(AbstractVirtualDocType):
			TABLE_NAME = "Things"
			NAME_EXPRESSION = "CONCAT([Style.No], '.', Size)"
			SCHEMA_CONFIG = {'description': {'column': 'Description'}}
		self.assertTrue(validate_schema_config(_DottedLiteral))


# ─── _build_select_clause ─────────────────────────────────────────────────────


class UnitTestBuildSelectClause(UnitTestCase):

	def test_no_fields_selects_all_schema_fields(self):
		result = _SimpleVirtualDocType._build_select_clause()
		self.assertEqual(
			result,
			'SELECT Products.[ID] AS name, Products.[Description] AS description, '
			'Products.[Quantity] AS quantity, Products.[Store UPC] AS store_sku'
		)

	def test_specific_fields_are_selected(self):
		result = _SimpleVirtualDocType._build_select_clause(['name', 'description'])
		self.assertEqual(result, 'SELECT Products.[ID] AS name, Products.[Description] AS description')

	def test_unmapped_fields_are_skipped(self):
		result = _SimpleVirtualDocType._build_select_clause(['name', 'nonexistent', 'description'])
		self.assertEqual(result, 'SELECT Products.[ID] AS name, Products.[Description] AS description')

	def test_strict_raises_on_unmapped_field(self):
		"""strict mode (used by get_values) surfaces typos instead of silently narrowing results."""
		with self.assertRaises(ValueError) as context:
			_SimpleVirtualDocType._build_select_clause(['description', 'nonexistent'], strict=True)
		self.assertIn('nonexistent', str(context.exception))

	def test_zero_resolved_fields_raises(self):
		"""No resolvable fields must raise rather than emit the invalid 'SELECT FROM ...'."""
		with self.assertRaises(frappe.ValidationError):
			_SimpleVirtualDocType._build_select_clause(['nonexistent'])

	def test_name_expression_is_projected_in_default_select(self):
		"""With NAME_EXPRESSION set and 'name' omitted from SCHEMA_CONFIG, the default projection
		still emits the expression aliased as name."""
		result = _NameExpressionVirtualDocType._build_select_clause()
		self.assertIn("CONCAT(StyleNumber, '-', Size) AS name", result)


# ─── _build_join_clause ───────────────────────────────────────────────────────


class UnitTestBuildJoinClause(UnitTestCase):

	def test_single_join_with_alias(self):
		result = _AliasedJoinVirtualDocType._build_join_clause()
		self.assertEqual(result, 'LEFT JOIN Categories AS cat ON Products.TopicID = cat.ID')

	def test_single_join_without_alias(self):
		result = _UnaliasedJoinVirtualDocType._build_join_clause()
		self.assertEqual(result, 'LEFT JOIN Categories ON Products.TopicID = Categories.ID')

	def test_multiple_joins_are_concatenated(self):
		class _MultiJoin(AbstractVirtualDocType):
			TABLE_NAME = "Products"
			JOIN_CONFIG = [
				{'join': 'LEFT JOIN',  'table': 'Categories', 'alias': 'cat', 'on': 'Products.TopicID = cat.ID'},
				{'join': 'INNER JOIN', 'table': 'Vendors',                    'on': 'Products.VendorID = Vendors.ID'},
			]
			SCHEMA_CONFIG = {'name': 'Products.ID'}

		self.assertEqual(
			_MultiJoin._build_join_clause(),
			'LEFT JOIN Categories AS cat ON Products.TopicID = cat.ID'
			' INNER JOIN Vendors ON Products.VendorID = Vendors.ID'
		)


# ─── _build_where_clause ──────────────────────────────────────────────────────


class UnitTestBuildWhereClause(UnitTestCase):

	def test_no_filters_returns_passthrough(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(values, [], [])
		self.assertEqual(result, 'WHERE 1=1')
		self.assertEqual(values, [])

	def test_single_and_filter(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, [('AscendProduct', 'description', '=', 'Red Ski')], []
		)
		self.assertEqual(result, 'WHERE (Products.[Description] = %s)')
		self.assertEqual(values, ['Red Ski'])

	def test_multiple_and_filters(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values,
			[
				('AscendProduct', 'description', '=',  'Red Ski'),
				('AscendProduct', 'quantity',    '>',   0),
			], []
		)
		self.assertEqual(result, 'WHERE (Products.[Description] = %s AND Products.[Quantity] > %s)')
		self.assertEqual(values, ['Red Ski', 0])

	def test_single_or_filter(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, [], [('AscendProduct', 'store_sku', 'LIKE', '%12345%')]
		)
		self.assertEqual(result, 'WHERE (Products.[Store UPC] LIKE %s)')
		self.assertEqual(values, ['%12345%'])

	def test_combined_and_and_or_filters(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values,
			[('AscendProduct', 'quantity',    '>',    0)],
			[('AscendProduct', 'description', 'LIKE', '%ski%')]
		)
		self.assertEqual(result, 'WHERE (Products.[Quantity] > %s) AND (Products.[Description] LIKE %s)')
		self.assertEqual(values, [0, '%ski%'])

	def test_three_element_conditions_are_accepted(self):
		"""Frappe's desk validation allows [fieldname, operator, value] conditions."""
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, [('description', '=', 'Red Ski')], []
		)
		self.assertEqual(result, 'WHERE (Products.[Description] = %s)')
		self.assertEqual(values, ['Red Ski'])

	def test_dict_filters_are_accepted(self):
		"""Programmatic callers pass {field: value} or {field: (operator, value)}."""
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, {'description': 'Red Ski', 'quantity': ('>', 0)}, []
		)
		self.assertEqual(result, 'WHERE (Products.[Description] = %s AND Products.[Quantity] > %s)')
		self.assertEqual(values, ['Red Ski', 0])

	def test_qualified_filter_fieldname_is_cleaned(self):
		"""A backtick-qualified fieldname must resolve like its bare form."""
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, [('AscendProduct', '`tabAscend Product`.`description`', '=', 'Red Ski')], []
		)
		self.assertEqual(result, 'WHERE (Products.[Description] = %s)')
		self.assertEqual(values, ['Red Ski'])

	def test_unmapped_filter_field_raises(self):
		"""Filtering on a field with no SCHEMA_CONFIG mapping must raise a clear error
		instead of emitting invalid SQL like 'None = %s'."""
		with self.assertRaises(frappe.ValidationError):
			_SimpleVirtualDocType._build_where_clause(
				[], [('AscendProduct', 'nonexistent', '=', 'x')], []
			)

	def test_unmapped_standard_field_is_dropped(self):
		"""Frappe's own meta-fields (tags, assignments, ...) are silently skipped so stock
		desk features do not crash."""
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values,
			[
				('AscendProduct', '_user_tags',  'like', '%new%'),
				('AscendProduct', 'description', '=',    'Red Ski'),
			], []
		)
		self.assertEqual(result, 'WHERE (Products.[Description] = %s)')
		self.assertEqual(values, ['Red Ski'])

	def test_only_ignored_fields_returns_passthrough(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, [('AscendProduct', '_assign', 'like', '%Administrator%')], []
		)
		self.assertEqual(result, 'WHERE 1=1')
		self.assertEqual(values, [])

	def test_is_set_translates_to_is_not_null(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, [('AscendProduct', 'description', 'is', 'set')], []
		)
		self.assertEqual(result, 'WHERE (Products.[Description] IS NOT NULL)')
		self.assertEqual(values, [])

	def test_is_not_set_translates_to_is_null(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, [('AscendProduct', 'description', 'is', 'not set')], []
		)
		self.assertEqual(result, 'WHERE (Products.[Description] IS NULL)')
		self.assertEqual(values, [])

	def test_unsupported_operator_raises(self):
		"""Operators outside OPERATOR_MAP must never be interpolated into the query."""
		with self.assertRaises(frappe.ValidationError):
			_SimpleVirtualDocType._build_where_clause(
				[], [('AscendProduct', 'description', 'timespan', 'today')], []
			)

	def test_name_filter_uses_expression(self):
		"""A filter on 'name' resolves to NAME_EXPRESSION, so link-title and list name lookups
		match against the same expression used in the projection."""
		values = []
		result = _NameExpressionVirtualDocType._build_where_clause(
			values, [('Thing', 'name', '=', 'SN-100-M')], []
		)
		self.assertEqual(result, "WHERE (CONCAT(StyleNumber, '-', Size) = %s)")
		self.assertEqual(values, ['SN-100-M'])

	def test_name_filter_widens_across_alt_name_resolution_fields(self):
		values = []
		result = _AltNameVirtualDocType._build_where_clause(
			values, [('AscendProduct', 'name', '=', '012345678905')], []
		)
		self.assertEqual(result, 'WHERE ((Products.[Store UPC] = %s OR Products.[UPC] = %s))')
		self.assertEqual(values, ['012345678905', '012345678905'])


# ─── _build_order_by_clause ───────────────────────────────────────────────────


class UnitTestBuildOrderByClause(UnitTestCase):

	def test_simple_field_ascending(self):
		result = _SimpleVirtualDocType._build_order_by_clause('description asc')
		self.assertEqual(result, 'ORDER BY description ASC')

	def test_simple_field_descending(self):
		result = _SimpleVirtualDocType._build_order_by_clause('quantity desc')
		self.assertEqual(result, 'ORDER BY quantity DESC')

	def test_frappe_fully_qualified_field_name(self):
		"""Frappe passes order_by as '`tabX`.`fieldname` dir'; the table prefix must be stripped."""
		result = _SimpleVirtualDocType._build_order_by_clause('`tabAscend Product`.`description` asc')
		self.assertEqual(result, 'ORDER BY description ASC')

	def test_unmapped_field_produces_null_fallback(self):
		result = _SimpleVirtualDocType._build_order_by_clause('creation desc')
		self.assertEqual(result, 'ORDER BY (SELECT NULL)')

	def test_field_without_direction_defaults_to_ascending(self):
		result = _SimpleVirtualDocType._build_order_by_clause('description')
		self.assertEqual(result, 'ORDER BY description ASC')

	def test_invalid_direction_token_is_discarded(self):
		"""The direction token comes from the client and must never be interpolated verbatim."""
		result = _SimpleVirtualDocType._build_order_by_clause('description evil_token')
		self.assertEqual(result, 'ORDER BY description ASC')


# ─── _validate_and_clean_fields ───────────────────────────────────────────────


class UnitTestValidateAndCleanFields(UnitTestCase):

	def test_strips_backtick_qualified_table_name(self):
		fields = ['`tabAscend Product`.`name`', 'description']
		_SimpleVirtualDocType._validate_and_clean_fields(fields)
		self.assertEqual(fields, ['name', 'description'])

	def test_removes_non_string_field_entries(self):
		fields = [0, 'name']
		_SimpleVirtualDocType._validate_and_clean_fields(fields)
		self.assertEqual(fields, ['name'])

	def test_plain_fieldnames_are_not_modified(self):
		fields = ['name', 'description', 'quantity']
		_SimpleVirtualDocType._validate_and_clean_fields(fields)
		self.assertEqual(fields, ['name', 'description', 'quantity'])


# ─── get_values ───────────────────────────────────────────────────────────────


class UnitTestGetValues(UnitTestCase):

	def test_empty_fields_raises(self):
		with self.assertRaises(ValueError):
			_SimpleVirtualDocType.get_values('SKU-1', [])

	def test_non_list_fields_raises(self):
		with self.assertRaises(ValueError):
			_SimpleVirtualDocType.get_values('SKU-1', 'description')

	def test_unmapped_field_raises(self):
		"""get_values field lists are developer-authored, so a typo must raise instead of
		silently returning None for that field."""
		with self.assertRaises(ValueError) as context:
			_SimpleVirtualDocType.get_values('SKU-1', ['description', 'upc'])
		self.assertIn('upc', str(context.exception))


# ─── get_count ────────────────────────────────────────────────────────────────


class UnitTestGetCount(UnitTestCase):

	def test_filters_are_applied_to_count_query(self):
		"""Regression: get_count previously passed _build_where_clause's arguments in the
		wrong order, silently dropping the filters from the count."""
		captured = {}

		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database

		def fake_sql(query=None, values=None, as_dict=True):
			captured['query'] = query
			captured['values'] = values
			return [{'count': 7}]

		fake_database.sql.side_effect = fake_sql

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			count = _SimpleVirtualDocType.get_count(
				doctype='Simple Virtual DocType',
				filters=[('Simple Virtual DocType', 'description', '=', 'Red Ski')],
				fields=[],
				distinct=False,
				save_user_settings=False,
				strict=None,
			)

		self.assertEqual(count, 7)
		self.assertIn('Products.[Description] = %s', captured['query'])
		self.assertEqual(captured['values'], ['Red Ski'])


# ─── db_update ────────────────────────────────────────────────────────────────


class _WritableSimpleVirtualDocType(_SimpleVirtualDocType):
	ALLOW_WRITE = True


class _WritableAliasedJoinVirtualDocType(_AliasedJoinVirtualDocType):
	ALLOW_WRITE = True


class _WritableWithModifiedVirtualDocType(AbstractVirtualDocType):
	"""Mirrors the real Ascend Product config that maps Frappe's 'modified' field to an
	Ascend column, to guard the datetime-string-to-native-object conversion in db_update."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	ALLOW_WRITE = True
	SCHEMA_CONFIG = {
		'name':          {'column': 'ID'},
		'modified':      {'column': 'DateModified'},
		'purchase_date': {'column': 'PurchaseDate'},
	}


class _FakeMetaField:
	def __init__(self, fieldtype=None, read_only=False, is_virtual=False):
		self.fieldtype = fieldtype
		self.read_only = read_only
		self.is_virtual = is_virtual


class _FakeMeta:
	"""Minimal stand-in for Document.meta — db_insert/db_update's field selection and value
	normalization only call get_field(fieldname), which real meta resolves from the DocType's
	declared fields. A fieldname is only treated as having a declared meta field when it's
	named in one of these three collections; anything else resolves to None, matching real
	meta.get_field() for a standard/default field like 'creation' or 'modified'."""
	def __init__(self, fieldtypes: dict = None, read_only_fields: set = None, virtual_fields: set = None):
		self._fieldtypes = fieldtypes or {}
		self._read_only_fields = read_only_fields or set()
		self._virtual_fields = virtual_fields or set()

	def get_field(self, fieldname):
		known_fields = self._fieldtypes.keys() | self._read_only_fields | self._virtual_fields
		if fieldname not in known_fields:
			return None
		return _FakeMetaField(
			fieldtype=self._fieldtypes.get(fieldname),
			read_only=fieldname in self._read_only_fields,
			is_virtual=fieldname in self._virtual_fields,
		)


def _make_document(document_class, name, fieldtypes=None, read_only_fields=None, virtual_fields=None, is_new=True, **field_values):
	"""Build a bare instance of a virtual doctype test fixture without going through
	Document.__init__ (which requires a real registered DocType's meta). db_insert/db_update
	only read self.name, self.doctype, self.meta, and self.as_dict() off the instance —
	everything else they touch (SCHEMA_CONFIG, TABLE_NAME, ALLOW_WRITE, _build_where_clause,
	...) is a class attribute or classmethod, so it resolves normally through the class."""
	document = object.__new__(document_class)
	document.doctype = document_class.__name__
	document.name = name
	document.meta = _FakeMeta(fieldtypes, read_only_fields, virtual_fields)
	document.as_dict = lambda: {'name': name, **field_values}
	# BaseDocument.set() consults self._table_fieldnames; the real attribute is populated by
	# BaseDocument.__init__, which object.__new__ bypasses. An empty tuple lets set() treat every
	# key as a scalar field (the only kind these fixtures use).
	document._table_fieldnames = ()
	# is_new() reads __islocal off the document. It drives _resolve_linked_id_fields' change
	# detection (a new record always resolves; an update only resolves changed display fields).
	# Update-path tests pass is_new=False and stub get_latest() to supply the prior values.
	document.__dict__['__islocal'] = 1 if is_new else 0
	# Field values are also exposed as real instance attributes so self.get(fieldname) — used by
	# _resolve_linked_id_fields to read a display field — resolves them from __dict__.
	for fieldname, field_value in field_values.items():
		setattr(document, fieldname, field_value)
	return document


class UnitTestDbUpdate(UnitTestCase):

	def test_read_only_doctype_raises(self):
		document = _make_document(_SimpleVirtualDocType, 'SKU-1', description='Red Ski')
		with self.assertRaises(NotImplementedError):
			document.db_update()

	def test_missing_name_raises(self):
		document = _make_document(_WritableSimpleVirtualDocType, None, description='Red Ski')
		with self.assertRaises(frappe.ValidationError):
			document.db_update()

	def test_normal_update_matches_exactly_one_row(self):
		captured = {}

		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.cursor.rowcount = 1

		def fake_sql(query=None, values=None, as_dict=True):
			captured['query'] = query
			captured['values'] = values
			return []

		fake_database.sql.side_effect = fake_sql

		document = _make_document(
			_WritableSimpleVirtualDocType, 'SKU-1',
			description='Red Ski', quantity=4, store_sku='UPC-1',
		)

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			document.db_update()

		self.assertIn('UPDATE Products SET', captured['query'])
		self.assertIn('Products.[Description] = %s', captured['query'])
		self.assertIn('Products.[Quantity] = %s', captured['query'])
		self.assertIn('Products.[Store UPC] = %s', captured['query'])
		self.assertIn('Products.[ID] = %s', captured['query'])
		self.assertEqual(captured['values'], ['Red Ski', 4, 'UPC-1', 'SKU-1'])

	def test_zero_matched_rows_raises_does_not_exist(self):
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.cursor.rowcount = 0
		fake_database.sql.return_value = []

		document = _make_document(_WritableSimpleVirtualDocType, 'SKU-1', description='Red Ski')

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			with self.assertRaises(frappe.DoesNotExistError):
				document.db_update()

	def test_multiple_matched_rows_raises(self):
		"""The core safeguard: an UPDATE that touches more than one row must never be
		treated as a success, even though the write already executed against the database."""
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.cursor.rowcount = 2
		fake_database.sql.return_value = []

		document = _make_document(_WritableSimpleVirtualDocType, 'SKU-1', description='Red Ski')

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			with self.assertRaises(frappe.ValidationError):
				document.db_update()

	def test_unmapped_field_excluded_from_set_clause(self):
		captured = {}
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.cursor.rowcount = 1

		def fake_sql(query=None, values=None, as_dict=True):
			captured['query'] = query
			captured['values'] = values
			return []

		fake_database.sql.side_effect = fake_sql

		document = _make_document(
			_WritableSimpleVirtualDocType, 'SKU-1',
			description='Red Ski', quantity=4, store_sku='UPC-1',
			creation='2026-01-01',  # not present in SCHEMA_CONFIG
		)

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			document.db_update()

		self.assertNotIn('2026-01-01', captured['values'])

	def test_joined_table_column_excluded_from_set_clause(self):
		"""A plain UPDATE can only target TABLE_NAME — a field mapped to a JOIN_CONFIG
		table/alias must never end up in the SET clause."""
		captured = {}
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.cursor.rowcount = 1

		def fake_sql(query=None, values=None, as_dict=True):
			captured['query'] = query
			captured['values'] = values
			return []

		fake_database.sql.side_effect = fake_sql

		document = _make_document(
			_WritableAliasedJoinVirtualDocType, 'ID-1',
			description='Red Ski', category='Skis',
		)

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			document.db_update()

		self.assertNotIn('cat.[Topic]', captured['query'])
		self.assertNotIn('Skis', captured['values'])
		self.assertIn('Products.[Description] = %s', captured['query'])

	def test_modified_field_string_is_converted_to_datetime(self):
		"""Regression: Frappe sets 'modified' to a plain string (e.g. via now()) before
		save, and pymssql needs a native datetime.datetime object — not that string — to
		bind a SQL Server datetime parameter correctly."""
		captured = {}
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.cursor.rowcount = 1

		def fake_sql(query=None, values=None, as_dict=True):
			captured['values'] = values
			return []

		fake_database.sql.side_effect = fake_sql

		document = _make_document(
			_WritableWithModifiedVirtualDocType, 'SKU-1',
			modified='2026-07-17 12:36:35.321314',
		)

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			document.db_update()

		modified_value = captured['values'][0]
		self.assertIsInstance(modified_value, datetime)
		self.assertEqual(modified_value, datetime(2026, 7, 17, 12, 36, 35, 321314))

	def test_meta_declared_date_field_string_is_converted(self):
		"""Same conversion applies to any meta-declared Date field, not just the
		standard-field fallback used for 'modified'/'creation'."""
		captured = {}
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.cursor.rowcount = 1

		def fake_sql(query=None, values=None, as_dict=True):
			captured['values'] = values
			return []

		fake_database.sql.side_effect = fake_sql

		document = _make_document(
			_WritableWithModifiedVirtualDocType, 'SKU-1',
			fieldtypes={'purchase_date': 'Date'},
			purchase_date='2026-07-17',
		)

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			document.db_update()

		self.assertEqual(captured['values'], [date(2026, 7, 17), 'SKU-1'])

	def test_read_only_field_excluded_from_set_clause(self):
		"""Regression: a SCHEMA_CONFIG-mapped field marked read_only in the DocType meta
		(mirroring AscendProduct.id, backed by a SQL Server IDENTITY column) must never be
		written — SQL Server rejects an explicit SET on an identity column."""
		captured = {}
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.cursor.rowcount = 1

		def fake_sql(query=None, values=None, as_dict=True):
			captured['query'] = query
			captured['values'] = values
			return []

		fake_database.sql.side_effect = fake_sql

		document = _make_document(
			_WritableSimpleVirtualDocType, 'SKU-1',
			read_only_fields={'quantity'},
			description='Red Ski', quantity=4, store_sku='UPC-1',
		)

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			document.db_update()

		self.assertNotIn('Products.[Quantity] = %s', captured['query'])
		self.assertNotIn(4, captured['values'])


# ─── db_insert ────────────────────────────────────────────────────────────────


class UnitTestDbInsert(UnitTestCase):

	def test_read_only_doctype_raises(self):
		document = _make_document(_SimpleVirtualDocType, 'SKU-1', description='Red Ski')
		with self.assertRaises(NotImplementedError):
			document.db_insert()

	def test_name_expression_raises(self):
		document = _make_document(_NameExpressionVirtualDocType, 'STYLE-1-M', description='Red Ski')
		document.ALLOW_WRITE = True
		with self.assertRaises(frappe.ValidationError):
			document.db_insert()

	def test_missing_name_raises(self):
		document = _make_document(_WritableSimpleVirtualDocType, None, description='Red Ski')
		with self.assertRaises(frappe.ValidationError):
			document.db_insert()

	def test_existing_record_raises_duplicate_entry(self):
		"""The core safeguard: Frappe performs no name-uniqueness check of its own for
		virtual doctypes before calling db_insert, so db_insert must guard against
		silently duplicating an existing record."""
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.sql.return_value = [{'count': 1}]

		document = _make_document(_WritableSimpleVirtualDocType, 'SKU-1', description='Red Ski')

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			with self.assertRaises(frappe.DuplicateEntryError):
				document.db_insert()

		# The INSERT itself must never run once a duplicate is detected.
		for call in fake_database.sql.call_args_list:
			query = call.kwargs.get('query') or (call.args[0] if call.args else '')
			self.assertNotIn('INSERT', query)

	def test_normal_insert_includes_primary_key_column(self):
		captured = {}
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database

		def fake_sql(query=None, values=None, as_dict=True):
			if query and query.strip().startswith('SELECT COUNT'):
				return [{'count': 0}]
			captured['query'] = query
			captured['values'] = values
			fake_database.cursor.rowcount = 1
			return []

		fake_database.sql.side_effect = fake_sql

		document = _make_document(
			_WritableSimpleVirtualDocType, 'SKU-1',
			description='Red Ski', quantity=4, store_sku='UPC-1',
		)

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			document.db_insert()

		self.assertIn('INSERT INTO Products', captured['query'])
		self.assertIn('Products.[ID]', captured['query'])
		self.assertIn('Products.[Description]', captured['query'])
		self.assertIn('Products.[Quantity]', captured['query'])
		self.assertIn('Products.[Store UPC]', captured['query'])
		self.assertIn('SKU-1', captured['values'])
		self.assertIn('Red Ski', captured['values'])

	def test_unaffected_insert_raises(self):
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database

		def fake_sql(query=None, values=None, as_dict=True):
			if query and query.strip().startswith('SELECT COUNT'):
				return [{'count': 0}]
			fake_database.cursor.rowcount = 0
			return []

		fake_database.sql.side_effect = fake_sql

		document = _make_document(_WritableSimpleVirtualDocType, 'SKU-1', description='Red Ski')

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			with self.assertRaises(frappe.ValidationError):
				document.db_insert()

	def test_unwritable_fields_excluded_from_insert(self):
		"""read_only, is_virtual, and no-value fieldtypes must never appear in the INSERT
		column list — none of them can hold a caller-supplied value."""
		captured = {}
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database

		def fake_sql(query=None, values=None, as_dict=True):
			if query and query.strip().startswith('SELECT COUNT'):
				return [{'count': 0}]
			captured['query'] = query
			captured['values'] = values
			fake_database.cursor.rowcount = 1
			return []

		fake_database.sql.side_effect = fake_sql

		document = _make_document(
			_WritableSimpleVirtualDocType, 'SKU-1',
			read_only_fields={'quantity'},
			virtual_fields={'store_sku'},
			description='Red Ski', quantity=4, store_sku='UPC-1',
		)

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			document.db_insert()

		self.assertNotIn('Products.[Quantity]', captured['query'])
		self.assertNotIn('Products.[Store UPC]', captured['query'])
		self.assertIn('Products.[Description]', captured['query'])


# ─── linked_id — resolution on write ──────────────────────────────────────────


class _LinkedCategoryDocType(AbstractVirtualDocType):
	"""Stands in for the 'Product Category' linked DocType — the resolution target whose
	database_id (Categories.ID) backs a product's category_id (Products.TopicID)."""
	TABLE_NAME = "Categories"
	SHOW_FIELD_WARNINGS = False
	SCHEMA_CONFIG = {
		'name':        {'column': 'Topic'},
		'database_id': {'column': 'ID', 'cache': True},
	}


class _LinkedIdVirtualDocType(AbstractVirtualDocType):
	"""AscendProduct-shaped: a JOIN-sourced 'category' display field paired with a writable
	'category_id' on the primary table, resolved through the linked 'Product Category' DocType."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	ALLOW_WRITE = True
	JOIN_CONFIG = [
		{'join': 'LEFT JOIN', 'table': 'Categories', 'alias': 'cat', 'on': 'Products.TopicID = cat.ID'}
	]
	SCHEMA_CONFIG = {
		'name':        {'column': 'ID'},
		'description': {'column': 'Description'},
		'category':    {'table': 'cat', 'column': 'Topic',
		                'linked_id': {'id_field':      'category_id',
		                              'link_doctype':  'Product Category',
		                              'link_id_field': 'database_id'}},
		'category_id': {'column': 'TopicID'},
	}


def _stub_linked_controller(return_value, match_count=1):
	"""A minimal linked controller standing in for the real linked DocType that get_controller
	resolves at runtime (patched into the base module). get_values returns a fixed value; get_count
	returns match_count, letting a test drive the ambiguity guard (match_count > 1)."""
	class _StubLinked:
		@classmethod
		def get_values(cls, name, fields):
			return return_value

		@classmethod
		def get_count(cls, **kwargs):
			return match_count
	return _StubLinked


class UnitTestResolveLinkedIdFields(UnitTestCase):

	def test_resolves_and_sets_id_field(self):
		"""The chosen display value is resolved through the linked DocType and its id written
		onto the paired id field, so the writable FK column reflects the edit."""
		document = _make_document(_LinkedIdVirtualDocType, 'ID-1', category='Skis')
		stub = _stub_linked_controller(frappe._dict({'database_id': 'GUID-1'}))
		with patch('bullwheel.ascend.virtual_doctype_base.get_controller', return_value=stub):
			document._resolve_linked_id_fields()
		self.assertEqual(document.get('category_id'), 'GUID-1')

	def test_unresolvable_display_value_aborts(self):
		"""A display value that resolves to no linked record aborts the save rather than writing
		a stale or NULL id."""
		document = _make_document(_LinkedIdVirtualDocType, 'ID-1', category='Ghost')
		with patch(
			'bullwheel.ascend.virtual_doctype_base.get_controller',
			return_value=_stub_linked_controller(None),
		):
			with self.assertRaises(frappe.ValidationError):
				document._resolve_linked_id_fields()

	def test_none_resolved_id_aborts(self):
		"""A linked record found but with a NULL id column is treated as unresolvable."""
		document = _make_document(_LinkedIdVirtualDocType, 'ID-1', category='Ghost')
		with patch(
			'bullwheel.ascend.virtual_doctype_base.get_controller',
			return_value=_stub_linked_controller(frappe._dict({'database_id': None})),
		):
			with self.assertRaises(frappe.ValidationError):
				document._resolve_linked_id_fields()

	def test_empty_display_clears_id_without_lookup(self):
		"""An empty display value clears the id field and skips the resolution query entirely."""
		document = _make_document(_LinkedIdVirtualDocType, 'ID-1', category='', category_id='OLD-GUID')
		with patch('bullwheel.ascend.virtual_doctype_base.get_controller') as fake_get_controller:
			document._resolve_linked_id_fields()
			fake_get_controller.assert_not_called()
		self.assertIsNone(document.get('category_id'))

	def test_no_linked_id_fields_is_noop(self):
		"""A controller with no 'linked_id' pairing resolves nothing and never touches get_controller."""
		document = _make_document(_WritableSimpleVirtualDocType, 'SKU-1', description='Red Ski')
		with patch('bullwheel.ascend.virtual_doctype_base.get_controller') as fake_get_controller:
			document._resolve_linked_id_fields()
			fake_get_controller.assert_not_called()

	def test_ambiguous_display_value_aborts(self):
		"""A display value matching more than one linked record yields no single id, so the save
		is rejected rather than silently picking an arbitrary one."""
		document = _make_document(_LinkedIdVirtualDocType, 'ID-1', category='Duplicated')
		stub = _stub_linked_controller(frappe._dict({'database_id': 'GUID-1'}), match_count=2)
		with patch('bullwheel.ascend.virtual_doctype_base.get_controller', return_value=stub):
			with self.assertRaises(frappe.ValidationError):
				document._resolve_linked_id_fields()

	def test_update_skips_resolution_when_display_unchanged(self):
		"""On update, a display field unchanged from the persisted record is left alone — no lookup,
		and the existing id field is preserved (guards against clobbering an orphaned/empty value)."""
		document = _make_document(
			_LinkedIdVirtualDocType, 'ID-1', is_new=False, category='Skis', category_id='EXISTING-ID',
		)
		document.get_latest = lambda: frappe._dict({'category': 'Skis'})
		with patch('bullwheel.ascend.virtual_doctype_base.get_controller') as fake_get_controller:
			document._resolve_linked_id_fields()
			fake_get_controller.assert_not_called()
		self.assertEqual(document.get('category_id'), 'EXISTING-ID')

	def test_update_resolves_when_display_changed(self):
		"""On update, a changed display field is resolved and its id field rewritten."""
		document = _make_document(_LinkedIdVirtualDocType, 'ID-1', is_new=False, category='NewCat')
		document.get_latest = lambda: frappe._dict({'category': 'OldCat'})
		stub = _stub_linked_controller(frappe._dict({'database_id': 'GUID-NEW'}))
		with patch('bullwheel.ascend.virtual_doctype_base.get_controller', return_value=stub):
			document._resolve_linked_id_fields()
		self.assertEqual(document.get('category_id'), 'GUID-NEW')

	def test_db_update_aborts_on_unresolvable_display(self):
		"""Resolution runs inside db_update, so an unresolvable category rejects the whole save
		before any SQL write is attempted."""
		document = _make_document(_LinkedIdVirtualDocType, 'ID-1', description='Red Ski', category='Ghost')
		with patch(
			'bullwheel.ascend.virtual_doctype_base.get_controller',
			return_value=_stub_linked_controller(None),
		):
			with self.assertRaises(frappe.ValidationError):
				document.db_update()


# ─── linked_id — structural validation ────────────────────────────────────────


def _linked_id_fixture(name, category_config=None, category_id_config=None):
	"""Build a _LinkedIdVirtualDocType variant overriding the 'category' and/or 'category_id'
	entries. Subclasses can't just override SCHEMA_CONFIG piecemeal (it is one dict), so each
	variant gets a full copy with the named entries replaced."""
	schema_config = dict(_LinkedIdVirtualDocType.SCHEMA_CONFIG)
	if category_config is not None:
		schema_config['category'] = category_config
	if category_id_config is not None:
		schema_config['category_id'] = category_id_config
	return type(name, (_LinkedIdVirtualDocType,), {'SCHEMA_CONFIG': schema_config})


class UnitTestLinkedIdFieldStructuralProblems(UnitTestCase):
	"""The DB-free structural half of the convention check. A pairing's own key set is enforced
	during normalization (see UnitTestNormalizeSchemaConfig), and its display field is mapped by
	construction, so those cases are no longer reachable here. The meta-dependent coverage and
	read-only checks are exercised end-to-end by `bench migrate`."""

	def _patch_get_controller(self):
		"""Resolve the 'Product Category' link_doctype to the stand-in controller above."""
		return patch(
			'bullwheel.ascend.validate_virtual_doctypes.get_controller',
			side_effect=lambda name: {'Product Category': _LinkedCategoryDocType}[name],
		)

	def test_valid_config_has_no_problems(self):
		with self._patch_get_controller():
			self.assertEqual(_linked_id_field_structural_problems(_LinkedIdVirtualDocType), [])

	def test_id_field_on_join_table_is_flagged(self):
		"""A JOIN column can't be written, so an id_field mapped to one defeats the convention."""
		_JoinIdField = _linked_id_fixture(
			'_JoinIdField',
			category_id_config={'table': 'cat', 'column': 'ID'},  # on the joined table, not Products
		)
		with self._patch_get_controller():
			problems = _linked_id_field_structural_problems(_JoinIdField)
		self.assertTrue(any('category_id' in problem for problem in problems))

	def test_unmapped_id_field_is_flagged(self):
		"""The pairing names an id_field with no SCHEMA_CONFIG entry, so there is no column to
		write the resolved id to."""
		_UnmappedIdField = _linked_id_fixture(
			'_UnmappedIdField',
			category_config={'table': 'cat', 'column': 'Topic',
			                 'linked_id': {'id_field':      'nonexistent',
			                               'link_doctype':  'Product Category',
			                               'link_id_field': 'database_id'}},
		)
		with self._patch_get_controller():
			problems = _linked_id_field_structural_problems(_UnmappedIdField)
		self.assertTrue(any('nonexistent' in problem for problem in problems))

	def test_unmapped_link_id_field_is_flagged(self):
		_BadLinkIdField = _linked_id_fixture(
			'_BadLinkIdField',
			category_config={'table': 'cat', 'column': 'Topic',
			                 'linked_id': {'id_field':      'category_id',
			                               'link_doctype':  'Product Category',
			                               'link_id_field': 'not_a_field'}},
		)
		with self._patch_get_controller():
			problems = _linked_id_field_structural_problems(_BadLinkIdField)
		self.assertTrue(any('not_a_field' in problem for problem in problems))

	def test_unresolvable_link_doctype_is_flagged(self):
		_BadLinkDoctype = _linked_id_fixture(
			'_BadLinkDoctype',
			category_config={'table': 'cat', 'column': 'Topic',
			                 'linked_id': {'id_field':      'category_id',
			                               'link_doctype':  'Nope',
			                               'link_id_field': 'database_id'}},
		)
		with patch(
			'bullwheel.ascend.validate_virtual_doctypes.get_controller',
			side_effect=Exception('no such doctype'),
		):
			problems = _linked_id_field_structural_problems(_BadLinkDoctype)
		self.assertTrue(any('Nope' in problem for problem in problems))


# ─── schema_config normalization ──────────────────────────────────────────────


class UnitTestNormalizeSchemaConfig(UnitTestCase):
	"""The field config contract: what a valid entry looks like, and which authoring mistakes
	are rejected at normalization time (and so block `bench migrate`)."""

	def _normalize(self, schema_config, table_name="Products"):
		fixture = type('_Fixture', (AbstractVirtualDocType,), {
			'TABLE_NAME': table_name, 'SCHEMA_CONFIG': schema_config,
		})
		return normalize_schema_config(fixture)

	def test_table_defaults_to_table_name(self):
		normalized = self._normalize({'description': {'column': 'Description'}})
		self.assertEqual(normalized['description']['table'], 'Products')
		self.assertEqual(normalized['description']['sql'], 'Products.[Description]')

	def test_explicit_table_is_used(self):
		normalized = self._normalize({'category': {'table': 'cat', 'column': 'Topic'}})
		self.assertEqual(normalized['category']['sql'], 'cat.[Topic]')

	def test_column_is_always_bracket_quoted(self):
		"""Quoting is the framework's job, so a name with a space and a reserved word are both
		safe without the author doing anything."""
		normalized = self._normalize({
			'store_sku': {'column': 'Store UPC'},
			'year':      {'column': 'Year'},
		})
		self.assertEqual(normalized['store_sku']['sql'], 'Products.[Store UPC]')
		self.assertEqual(normalized['year']['sql'], 'Products.[Year]')

	def test_author_supplied_brackets_are_stripped(self):
		"""'[Store UPC]' and 'Store UPC' must normalize identically rather than double-quoting."""
		bracketed = self._normalize({'store_sku': {'column': '[Store UPC]'}})
		bare = self._normalize({'store_sku': {'column': 'Store UPC'}})
		self.assertEqual(bracketed['store_sku']['sql'], bare['store_sku']['sql'])
		self.assertEqual(bracketed['store_sku']['column'], 'Store UPC')

	def test_flags_default_to_false(self):
		normalized = self._normalize({'description': {'column': 'Description'}})
		self.assertFalse(normalized['description']['alternate_name'])
		self.assertFalse(normalized['description']['cache'])
		self.assertIsNone(normalized['description']['linked_id'])

	def test_none_entry_declares_an_unmapped_field(self):
		normalized = self._normalize({'placeholder': None})
		self.assertIsNone(normalized['placeholder']['sql'])
		self.assertIsNone(normalized['placeholder']['table'])

	def test_declaration_order_is_preserved(self):
		"""The default SELECT projection and the alternate-name OR widening both depend on it."""
		normalized = self._normalize({
			'name':        {'column': 'ID'},
			'description': {'column': 'Description'},
			'quantity':    {'column': 'Quantity'},
		})
		self.assertEqual(list(normalized), ['name', 'description', 'quantity'])

	def test_unknown_key_raises_naming_the_field(self):
		with self.assertRaises(ValueError) as context:
			self._normalize({'description': {'colum': 'Description'}})
		self.assertIn('colum', str(context.exception))
		self.assertIn('description', str(context.exception))

	def test_flat_string_entry_raises(self):
		with self.assertRaises(ValueError):
			self._normalize({'description': 'Products.Description'})

	def test_missing_column_raises(self):
		with self.assertRaises(ValueError):
			self._normalize({'description': {'table': 'Products'}})

	def test_table_qualified_column_raises(self):
		"""The hallmark of an entry half-converted from the older flat format."""
		with self.assertRaises(ValueError) as context:
			self._normalize({'description': {'column': 'Products.Description'}})
		self.assertIn('table', str(context.exception))

	def test_non_boolean_flag_raises(self):
		for key in ('alternate_name', 'cache'):
			with self.subTest(key=key):
				with self.assertRaises(ValueError):
					self._normalize({'description': {'column': 'Description', key: 'yes'}})

	def test_malformed_linked_id_raises(self):
		with self.assertRaises(ValueError) as context:
			self._normalize({'category': {'column': 'Topic', 'linked_id': {'id_field': 'category_id'}}})
		self.assertIn('link_doctype', str(context.exception))

	def test_unknown_linked_id_key_raises(self):
		with self.assertRaises(ValueError):
			self._normalize({'category': {'column': 'Topic', 'linked_id': {
				'id_field': 'category_id', 'link_doctype': 'Product Category',
				'link_id_field': 'database_id', 'extra': 'x',
			}}})

	def test_quote_column_is_idempotent(self):
		self.assertEqual(quote_column('Store UPC'), '[Store UPC]')
		self.assertEqual(quote_column('[Store UPC]'), '[Store UPC]')


class UnitTestNormalizedSchemaMemoization(UnitTestCase):

	def test_each_controller_resolves_its_own_config(self):
		"""The memo is keyed by class on the base class. A plain class attribute would let one
		controller's normalized config leak into every other, so this is the one subtle way the
		cache can break."""
		self.assertEqual(_SimpleVirtualDocType._column_for('description'), 'Products.[Description]')
		self.assertEqual(_LinkedCategoryDocType._column_for('name'), 'Categories.[Topic]')
		self.assertEqual(_AliasedJoinVirtualDocType._column_for('category'), 'cat.[Topic]')
		# Re-read after the others have populated the cache.
		self.assertEqual(_SimpleVirtualDocType._column_for('description'), 'Products.[Description]')
		self.assertIsNone(_SimpleVirtualDocType._column_for('category'))

	def test_accessors_derive_from_the_field_config(self):
		self.assertEqual(_AltNameVirtualDocType.alternate_name_fields(), ['upc'])
		self.assertEqual(_SimpleVirtualDocType.alternate_name_fields(), [])
		self.assertEqual(list(_LinkedIdVirtualDocType.linked_id_fields()), ['category'])
		self.assertEqual(
			_LinkedIdVirtualDocType.linked_id_fields()['category']['id_field'], 'category_id'
		)
		self.assertEqual(_LinkedCategoryDocType.cache_fields(), ['database_id'])
		self.assertEqual(_SimpleVirtualDocType.cache_fields(), [])

	def test_column_belongs_to_table_uses_the_structural_table(self):
		self.assertTrue(_AliasedJoinVirtualDocType._column_belongs_to_table('description'))
		self.assertFalse(_AliasedJoinVirtualDocType._column_belongs_to_table('category'))
		self.assertFalse(_AliasedJoinVirtualDocType._column_belongs_to_table('nonexistent'))
