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

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType, DISABLE_ROW_GOAL_HINT
from bullwheel.ascend.schema_config import collapse_related_value, normalize_schema_config, quote_column
from bullwheel.ascend.validate_virtual_doctypes import (
	validate_schema_config,
	autoname_mismatch_reason,
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


# ─── EXCLUDE_NULL_NAME ─────────────────────────────────────────────────────────


class _ExcludeNullNameVirtualDocType(AbstractVirtualDocType):
	"""Mirrors AscendUser-shaped config: 'name' maps to a business field (EmployeeId-like)
	that isn't populated for every row, so null-named rows must be excluded everywhere."""
	TABLE_NAME = "Users"
	SHOW_FIELD_WARNINGS = False
	EXCLUDE_NULL_NAME = True
	SCHEMA_CONFIG = {
		'name':       {'column': 'EmployeeId'},
		'first_name': {'column': 'FirstName'},
	}


class UnitTestExcludeNullName(UnitTestCase):

	def test_default_is_false_and_unaffected(self):
		"""Existing doctypes never opt in, so their WHERE clause is unchanged by default —
		this is what keeps every pre-existing _build_where_clause test passing unmodified."""
		self.assertFalse(_SimpleVirtualDocType.EXCLUDE_NULL_NAME)

	def test_guard_added_with_no_other_filters(self):
		values = []
		result = _ExcludeNullNameVirtualDocType._build_where_clause(values, [], [])
		self.assertEqual(result, 'WHERE Users.[EmployeeId] IS NOT NULL')
		self.assertEqual(values, [])

	def test_guard_combined_with_and_filter(self):
		values = []
		result = _ExcludeNullNameVirtualDocType._build_where_clause(
			values, [('Ascend User', 'first_name', '=', 'Carter')], []
		)
		self.assertEqual(
			result,
			'WHERE Users.[EmployeeId] IS NOT NULL AND (Users.[FirstName] = %s)'
		)
		self.assertEqual(values, ['Carter'])

	def test_get_list_applies_guard_even_without_filters(self):
		"""Regression: get_list previously skipped _build_where_clause entirely when called
		with no filters/or_filters (the common case for a freshly opened Link search dropdown),
		which would have silently dropped the null-name guard for exactly the query that
		crashed Frappe's relevance sort."""
		captured = {}
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.sql.side_effect = lambda query=None, values=None, as_dict=True: captured.update(query=query) or []

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			_ExcludeNullNameVirtualDocType.get_list(
				doctype='Ascend User', fields=['name'], filters=[], start=0, page_length=10,
				with_comment_count=False, save_user_settings=False,
			)

		self.assertIn('WHERE Users.[EmployeeId] IS NOT NULL', captured['query'])

	def test_get_count_applies_guard_even_without_filters(self):
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		captured = {}
		fake_database.sql.side_effect = lambda query=None, values=None, as_dict=True: (
			captured.update(query=query) or [{'count': 3}]
		)

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			count = _ExcludeNullNameVirtualDocType.get_count(
				doctype='Ascend User', filters=[], fields=[], distinct=False, save_user_settings=False, strict=None,
			)

		self.assertIn('WHERE Users.[EmployeeId] IS NOT NULL', captured['query'])
		self.assertEqual(count, 3)


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


# ─── get_bulk_values ──────────────────────────────────────────────────────────


class _SmallBatchVirtualDocType(_SimpleVirtualDocType):
	"""Small MAX_BATCH_INSERT_SIZE so chunking is exercised without 1000 fixture names."""
	MAX_BATCH_INSERT_SIZE = 2


class UnitTestGetBulkValues(UnitTestCase):

	def test_empty_fields_raises(self):
		with self.assertRaises(ValueError):
			_SimpleVirtualDocType.get_bulk_values(['SKU-1'], [])

	def test_non_list_fields_raises(self):
		with self.assertRaises(ValueError):
			_SimpleVirtualDocType.get_bulk_values(['SKU-1'], 'description')

	def test_empty_names_returns_empty_dict_without_querying(self):
		with patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase') as fake_database_class:
			result = _SimpleVirtualDocType.get_bulk_values([], ['description'])

		self.assertEqual(result, {})
		fake_database_class.assert_not_called()

	def test_creates_temp_table_inserts_names_and_joins_on_it(self):
		"""The batch lookup goes through a #lookup_names temp table joined against TABLE_NAME,
		not a WHERE name IN (...) clause — _format_condition's 'in' handling appends the whole
		list as a single bound value rather than expanding it into one placeholder per name,
		which does not render correctly against pymssql."""
		queries = []

		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database

		def fake_sql(query=None, values=None, as_dict=True):
			queries.append((query, values))
			if query.strip().startswith('SELECT'):
				return [{'name': 'SKU-1', 'description': 'Red Ski'}]
			return []

		fake_database.sql.side_effect = fake_sql

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			result = _SimpleVirtualDocType.get_bulk_values(['SKU-1', 'SKU-2'], ['description'])

		create_query, insert_query, select_query = (query for query, _ in queries)
		self.assertIn('CREATE TABLE #lookup_names', create_query)
		self.assertIn('INSERT INTO #lookup_names', insert_query)
		self.assertEqual(queries[1][1], ['SKU-1', 'SKU-2'])
		self.assertIn('INNER JOIN #lookup_names ON Products.[ID] = #lookup_names.lookup_name', select_query)
		self.assertEqual(result, {'SKU-1': {'description': 'Red Ski'}})

	def test_missing_name_absent_from_result(self):
		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database
		fake_database.sql.side_effect = lambda query=None, values=None, as_dict=True: (
			[{'name': 'SKU-1', 'description': 'Red Ski'}] if query.strip().startswith('SELECT') else []
		)

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			result = _SimpleVirtualDocType.get_bulk_values(['SKU-1', 'SKU-404'], ['description'])

		self.assertEqual(list(result), ['SKU-1'])

	def test_name_expression_used_as_join_column(self):
		"""A NAME_EXPRESSION-backed primary key (a computed SQL expression, not a raw column)
		must be used as the join predicate, matching _column_for('name')."""
		captured = {}

		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database

		def fake_sql(query=None, values=None, as_dict=True):
			if query.strip().startswith('SELECT'):
				captured['select'] = query
			return []

		fake_database.sql.side_effect = fake_sql

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			_NameExpressionVirtualDocType.get_bulk_values(['A-1'], ['description'])

		self.assertIn(
			"INNER JOIN #lookup_names ON CONCAT(StyleNumber, '-', Size) = #lookup_names.lookup_name",
			captured['select'],
		)

	def test_chunks_insert_at_max_batch_insert_size(self):
		insert_values = []

		fake_database = MagicMock()
		fake_database.__enter__.return_value = fake_database

		def fake_sql(query=None, values=None, as_dict=True):
			if query.strip().startswith('INSERT'):
				insert_values.append(values)
			return []

		fake_database.sql.side_effect = fake_sql

		with (
			patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
			patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
		):
			_SmallBatchVirtualDocType.get_bulk_values(['A', 'B', 'C'], ['description'])

		self.assertEqual(insert_values, [['A', 'B'], ['C']])


# ─── get_bulk_short_cached_values ─────────────────────────────────────────────


class UnitTestGetBulkShortCachedValues(UnitTestCase):

	def test_cold_cache_queries_once_and_caches_each_field(self):
		set_calls = []

		with (
			patch('frappe.cache.get_value', return_value=None),
			patch('frappe.cache.set_value', side_effect=lambda key, value, expires_in_sec=None: set_calls.append((key, value, expires_in_sec))),
			patch.object(
				_SimpleVirtualDocType, 'get_bulk_values',
				return_value={'SKU-1': frappe._dict({'description': 'Red Ski', 'quantity': 3})},
			) as fake_get_bulk_values,
		):
			result = _SimpleVirtualDocType.get_bulk_short_cached_values(['SKU-1'], ['description', 'quantity'])

		fake_get_bulk_values.assert_called_once_with(['SKU-1'], ['description', 'quantity'])
		self.assertEqual(result, {'SKU-1': {'description': 'Red Ski', 'quantity': 3}})
		self.assertEqual(len(set_calls), 2)
		for _key, _value, ttl in set_calls:
			self.assertEqual(ttl, _SimpleVirtualDocType.SHORT_CACHE_TTL_SECONDS)

	def test_warm_cache_never_queries(self):
		with (
			patch('frappe.cache.get_value', return_value='cached-value'),
			patch.object(_SimpleVirtualDocType, 'get_bulk_values') as fake_get_bulk_values,
		):
			result = _SimpleVirtualDocType.get_bulk_short_cached_values(['SKU-1'], ['description'])

		fake_get_bulk_values.assert_not_called()
		self.assertEqual(result, {'SKU-1': {'description': 'cached-value'}})

	def test_mixed_hot_and_cold_only_fetches_misses(self):
		def fake_get_value(key, expires=False):
			return 'Warm Ski' if 'SKU-1' in key else None

		with (
			patch('frappe.cache.get_value', side_effect=fake_get_value),
			patch('frappe.cache.set_value'),
			patch.object(
				_SimpleVirtualDocType, 'get_bulk_values',
				return_value={'SKU-2': frappe._dict({'description': 'Cold Ski'})},
			) as fake_get_bulk_values,
		):
			result = _SimpleVirtualDocType.get_bulk_short_cached_values(['SKU-1', 'SKU-2'], ['description'])

		fake_get_bulk_values.assert_called_once_with(['SKU-2'], ['description'])
		self.assertEqual(result, {'SKU-1': {'description': 'Warm Ski'}, 'SKU-2': {'description': 'Cold Ski'}})

	def test_name_with_no_ascend_match_is_absent_and_never_cached(self):
		with (
			patch('frappe.cache.get_value', return_value=None),
			patch('frappe.cache.set_value') as fake_set_value,
			patch.object(_SimpleVirtualDocType, 'get_bulk_values', return_value={}),
		):
			result = _SimpleVirtualDocType.get_bulk_short_cached_values(['SKU-404'], ['description'])

		self.assertEqual(result, {})
		fake_set_value.assert_not_called()


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

	def test_linked_id_key_is_no_longer_valid(self):
		"""linked_id belonged to the removed write path; leaving it in a config must fail loudly."""
		with self.assertRaises(ValueError):
			self._normalize({'category': {'column': 'Topic', 'linked_id': {'id_field': 'category_id'}}})

	def test_quote_column_is_idempotent(self):
		self.assertEqual(quote_column('Store UPC'), '[Store UPC]')
		self.assertEqual(quote_column('[Store UPC]'), '[Store UPC]')


class UnitTestNormalizedSchemaMemoization(UnitTestCase):

	def test_each_controller_resolves_its_own_config(self):
		"""The memo is keyed by class on the base class. A plain class attribute would let one
		controller's normalized config leak into every other, so this is the one subtle way the
		cache can break."""
		self.assertEqual(_SimpleVirtualDocType._column_for('description'), 'Products.[Description]')
		self.assertEqual(_AliasedJoinVirtualDocType._column_for('category'), 'cat.[Topic]')
		# Re-read after the others have populated the cache.
		self.assertEqual(_SimpleVirtualDocType._column_for('description'), 'Products.[Description]')
		self.assertIsNone(_SimpleVirtualDocType._column_for('category'))

	def test_accessors_derive_from_the_field_config(self):
		self.assertEqual(_AltNameVirtualDocType.alternate_name_fields(), ['upc'])
		self.assertEqual(_SimpleVirtualDocType.alternate_name_fields(), [])
		self.assertEqual(_SimpleVirtualDocType.cache_fields(), [])


# ─── read-only guards ─────────────────────────────────────────────────────────


class UnitTestReadOnlyGuards(UnitTestCase):
	"""Bullwheel never writes to Ascend: every virtual DocType refuses to insert or update."""

	def test_db_insert_and_db_update_refuse(self):
		document = _SimpleVirtualDocType.__new__(_SimpleVirtualDocType)
		document.doctype = 'Simple Virtual'
		for write in (document.db_insert, document.db_update):
			with self.subTest(write=write.__name__):
				with self.assertRaises(frappe.PermissionError):
					write()

	def test_no_source_module_issues_a_write_against_products_or_vendor_products(self):
		"""Guards against the write path creeping back in: no module may INSERT/UPDATE/DELETE
		Ascend's Products or VendorProducts. (get_bulk_values' INSERT INTO #lookup_names is a
		temp table, not Ascend data.)"""
		import pathlib
		import re

		pattern = re.compile(r'\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(dbo\.)?\[?(Products|VendorProducts)\b', re.IGNORECASE)
		root = pathlib.Path(__file__).resolve().parent.parent
		offenders = []
		for path in root.rglob('*.py'):
			if path.name.startswith('test_'):
				continue
			if pattern.search(path.read_text()):
				offenders.append(str(path.relative_to(root)))
		self.assertEqual(offenders, [])


# ─── related (one-to-many) fields ─────────────────────────────────────────────


class _RelatedFieldVirtualDocType(AbstractVirtualDocType):
	"""A product identified by Store SKU, then UPC, then any vendor's part number — the part
	numbers living one-per-vendor on VendorProducts."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	SCHEMA_CONFIG = {
		'name':                {'column': 'Store UPC'},
		'upc':                 {'column': 'UPC', 'alternate_name': True},
		'vendor_part_numbers': {
			'table': 'VendorProducts', 'column': 'PartNumber',
			'foreign_key': 'ProductID', 'references': 'ID', 'alternate_name': True,
		},
		'description':         {'column': 'Description'},
	}


VENDOR_PART_NUMBER_EXISTS = (
	'EXISTS (SELECT 1 FROM VendorProducts AS related_vendor_part_numbers '
	'WHERE related_vendor_part_numbers.[ProductID] = Products.[ID] AND related_vendor_part_numbers.[PartNumber] {})'
)


def _fake_database(results):
	"""A mocked MSSQLDatabase whose sql() returns each of `results` in turn, recording every
	(query, values) it was called with."""
	fake_database = MagicMock()
	fake_database.__enter__.return_value = fake_database
	fake_database.calls = []
	responses = iter(results)

	def fake_sql(query=None, values=None, as_dict=True):
		fake_database.calls.append((query, values))
		return next(responses)

	fake_database.sql.side_effect = fake_sql
	return fake_database


def _patched_database(fake_database):
	return (
		patch('bullwheel.ascend.virtual_doctype_base.MSSQLDatabase', return_value=fake_database),
		patch('bullwheel.ascend.virtual_doctype_base.get_default_ascend_database', return_value=None),
	)


class UnitTestNormalizeRelatedField(UnitTestCase):

	def _normalize(self, field_config):
		fixture = type('_Fixture', (AbstractVirtualDocType,), {
			'TABLE_NAME': 'Products', 'SCHEMA_CONFIG': {'vendor_part_numbers': field_config},
		})
		return normalize_schema_config(fixture)['vendor_part_numbers']

	def test_related_field_projects_a_sorted_aggregate_subquery(self):
		"""A related field is never JOINed, so selecting it cannot repeat the record per row."""
		normalized = self._normalize({
			'table': 'VendorProducts', 'column': 'PartNumber', 'foreign_key': 'ProductID', 'references': 'ID',
		})
		self.assertEqual(
			normalized['sql'],
			"(SELECT STRING_AGG(CAST(related_vendor_part_numbers.[PartNumber] AS NVARCHAR(MAX)), NCHAR(31)) "
			"WITHIN GROUP (ORDER BY related_vendor_part_numbers.[PartNumber]) "
			"FROM VendorProducts AS related_vendor_part_numbers "
			"WHERE related_vendor_part_numbers.[ProductID] = Products.[ID])"
		)
		# No DISTINCT/derived table: combined with an alternate-name WHERE it made SQL Server
		# aggregate all of VendorProducts (~0.7s per load). Duplicates are removed in Python.
		self.assertNotIn('DISTINCT', normalized['sql'])
		self.assertEqual(normalized['related']['table'], 'VendorProducts')

	def test_plain_field_is_not_related(self):
		self.assertIsNone(self._normalize({'column': 'Description'})['related'])

	def test_half_declared_relationship_raises(self):
		for field_config in (
			{'table': 'VendorProducts', 'column': 'PartNumber', 'foreign_key': 'ProductID'},
			{'table': 'VendorProducts', 'column': 'PartNumber', 'references': 'ID'},
		):
			with self.subTest(field_config=field_config):
				with self.assertRaises(ValueError):
					self._normalize(field_config)

	def test_related_field_without_explicit_table_raises(self):
		with self.assertRaises(ValueError) as context:
			self._normalize({'column': 'PartNumber', 'foreign_key': 'ProductID', 'references': 'ID'})
		self.assertIn("'table'", str(context.exception))

	def test_qualified_foreign_key_raises(self):
		with self.assertRaises(ValueError):
			self._normalize({
				'table': 'VendorProducts', 'column': 'PartNumber',
				'foreign_key': 'VendorProducts.ProductID', 'references': 'ID',
			})


class UnitTestRelatedFieldWhereClause(UnitTestCase):

	def _where(self, filters):
		values = []
		return _RelatedFieldVirtualDocType._build_where_clause(values, filters, []), values

	def test_filter_matches_any_related_row(self):
		result, values = self._where([('Product', 'vendor_part_numbers', '=', 'ABC-1')])
		self.assertEqual(result, f"WHERE ({VENDOR_PART_NUMBER_EXISTS.format('= %s')})")
		self.assertEqual(values, ['ABC-1'])

	def test_negated_operators_become_not_exists(self):
		"""'!= X' means no part number equals X, not that some part number differs from X."""
		for operator, positive in (('!=', '= %s'), ('not like', 'LIKE %s'), ('not in', 'IN %s')):
			with self.subTest(operator=operator):
				result, _values = self._where([('Product', 'vendor_part_numbers', operator, 'ABC-1')])
				self.assertEqual(result, f"WHERE (NOT {VENDOR_PART_NUMBER_EXISTS.format(positive)})")

	def test_is_set_and_not_set(self):
		result, values = self._where([('Product', 'vendor_part_numbers', 'is', 'set')])
		self.assertEqual(result, f"WHERE ({VENDOR_PART_NUMBER_EXISTS.format('IS NOT NULL')})")
		self.assertEqual(values, [])
		result, _values = self._where([('Product', 'vendor_part_numbers', 'is', 'not set')])
		self.assertEqual(result, f"WHERE (NOT {VENDOR_PART_NUMBER_EXISTS.format('IS NOT NULL')})")

	def test_unsupported_operator_still_raises(self):
		with self.assertRaises(frappe.ValidationError):
			self._where([('Product', 'vendor_part_numbers', 'between', 'ABC-1')])

	def test_name_filter_widens_into_related_field_with_exists(self):
		result, values = self._where([('Product', 'name', '=', 'ABC-1')])
		self.assertEqual(
			result,
			f"WHERE ((Products.[Store UPC] = %s OR Products.[UPC] = %s OR {VENDOR_PART_NUMBER_EXISTS.format('= %s')}))"
		)
		self.assertEqual(values, ['ABC-1', 'ABC-1', 'ABC-1'])

	def test_count_query_never_joins_the_related_table(self):
		"""The whole point: no JOIN, so a product with three vendors still counts once."""
		fake_database = _fake_database([[{'count': 1}]])
		database_patch, server_patch = _patched_database(fake_database)
		with database_patch, server_patch:
			_RelatedFieldVirtualDocType.get_count(
				doctype='Product', filters=[('Product', 'name', '=', 'ABC-1')], fields=[],
				distinct=False, save_user_settings=False, strict=None,
			)
		query, _values = fake_database.calls[0]
		self.assertNotIn('JOIN', query)
		self.assertIn('EXISTS (SELECT 1 FROM VendorProducts', query)

	def _list_query(self, filters, order_by=None):
		fake_database = _fake_database([[]])
		database_patch, server_patch = _patched_database(fake_database)
		with database_patch, server_patch:
			_RelatedFieldVirtualDocType.get_list(
				doctype='Product', fields=['name'], filters=filters, start=0, page_length=20,
				with_comment_count=False, save_user_settings=False, order_by=order_by,
			)
		return fake_database.calls[0][0]

	def test_paged_query_through_related_field_disables_the_row_goal(self):
		"""Without the hint a one-match lookup scans every product (measured ~1.3s on Ascend)."""
		for filters in ([('Product', 'name', '=', 'ABC-1')], [('Product', 'vendor_part_numbers', 'in', ['ABC-1', 'XYZ-2'])]):
			with self.subTest(filters=filters):
				self.assertTrue(self._list_query(filters).endswith(DISABLE_ROW_GOAL_HINT))

	def test_other_paged_queries_keep_the_row_goal(self):
		"""The hint slows an ORDER BY page roughly tenfold and a broad Link-search LIKE threefold,
		so it is only applied to exact related lookups."""
		for filters in ([('Product', 'description', 'like', '%ski%')], [('Product', 'name', 'like', '%ski%')]):
			with self.subTest(filters=filters):
				self.assertNotIn('USE HINT', self._list_query(filters, order_by='description asc'))


class UnitTestFindByIdentifier(UnitTestCase):

	def _find(self, records, fields=None):
		fake_database = _fake_database([records])
		database_patch, server_patch = _patched_database(fake_database)
		with database_patch, server_patch:
			result = _RelatedFieldVirtualDocType.find_by_identifier('ABC-1', fields)
		return result, fake_database.calls[0]

	def test_rank_orders_name_then_alternates_in_declaration_order(self):
		"""The WHERE guarantees a match, so the last field is the ELSE — keeping the part number
		EXISTS out of the CASE, where it was slow."""
		_result, (query, values) = self._find([])
		self.assertIn(
			"CASE WHEN Products.[Store UPC] = %s THEN 0 WHEN Products.[UPC] = %s THEN 1 "
			"ELSE 2 END AS _identifier_rank",
			query,
		)
		self.assertTrue(query.endswith('ORDER BY _identifier_rank, name'))
		# Two for the rank in SELECT, then three for the WHERE — in placeholder order.
		self.assertEqual(values, ['ABC-1'] * 5)

	def test_rank_without_alternate_names_is_constant(self):
		self.assertEqual(_SimpleVirtualDocType._identifier_rank_sql('SKU-1', []), '0')

	def test_only_the_best_rank_is_returned(self):
		"""A Store SKU match beats another product's part number match."""
		result, _call = self._find([
			{'name': 'SKU-B', 'description': 'By SKU', '_identifier_rank': 0},
			{'name': 'SKU-A', 'description': 'By part number', '_identifier_rank': 2},
		], ['description'])
		self.assertEqual(result, [{'description': 'By SKU'}])

	def test_shared_identifier_returns_every_record_at_that_rank(self):
		result, _call = self._find([
			{'name': 'SKU-A', 'description': 'Ski A', '_identifier_rank': 2},
			{'name': 'SKU-B', 'description': 'Ski B', '_identifier_rank': 2},
		])
		self.assertEqual([record.name for record in result], ['SKU-A', 'SKU-B'])
		self.assertNotIn('_identifier_rank', result[0])

	def test_duplicate_rows_collapse_by_name(self):
		result, _call = self._find([
			{'name': 'SKU-A', '_identifier_rank': 2},
			{'name': 'SKU-A', '_identifier_rank': 2},
		])
		self.assertEqual(len(result), 1)

	def test_requested_fields_are_strict(self):
		with self.assertRaises(ValueError):
			_RelatedFieldVirtualDocType.find_by_identifier('ABC-1', ['not_a_field'])

	def test_get_values_returns_the_first_candidate(self):
		fake_database = _fake_database([[
			{'name': 'SKU-A', 'description': 'Ski A', '_identifier_rank': 2},
			{'name': 'SKU-B', 'description': 'Ski B', '_identifier_rank': 2},
		]])
		database_patch, server_patch = _patched_database(fake_database)
		with database_patch, server_patch:
			result = _RelatedFieldVirtualDocType.get_values('ABC-1', ['description'])
		self.assertEqual(result, {'description': 'Ski A'})


class UnitTestRelatedEchoMatchedIdentifier(UnitTestCase):

	def test_record_found_by_part_number_echoes_the_part_number(self):
		"""Frappe's Link check compares returned names with the typed value, so a product found by
		part number must come back named by that part number."""
		fake_database = _fake_database([[{'name': 'SKU-A', 'matched_value': 'ABC-1'}]])
		database_patch, server_patch = _patched_database(fake_database)
		with database_patch, server_patch:
			echoed = _RelatedFieldVirtualDocType._echo_matched_identifier(
				[{'name': 'SKU-A', 'upc': '111'}], {'ABC-1'}
			)
		self.assertEqual(echoed[0]['name'], 'ABC-1')
		query, values = fake_database.calls[0]
		self.assertIn('INNER JOIN VendorProducts AS related_vendor_part_numbers', query)
		self.assertEqual(values, [('SKU-A',), ('ABC-1',)])

	def test_in_row_match_needs_no_related_query(self):
		fake_database = _fake_database([])
		database_patch, server_patch = _patched_database(fake_database)
		with database_patch, server_patch:
			echoed = _RelatedFieldVirtualDocType._echo_matched_identifier(
				[{'name': 'SKU-A', 'upc': '111'}], {'111'}
			)
		self.assertEqual(echoed[0]['name'], '111')
		self.assertEqual(fake_database.calls, [])

	def test_unmatched_record_keeps_its_name(self):
		fake_database = _fake_database([[]])
		database_patch, server_patch = _patched_database(fake_database)
		with database_patch, server_patch:
			echoed = _RelatedFieldVirtualDocType._echo_matched_identifier(
				[{'name': 'SKU-A', 'upc': '111'}], {'%ski%'}
			)
		self.assertEqual(echoed[0]['name'], 'SKU-A')


class UnitTestValidateRelatedField(UnitTestCase):

	def test_related_table_need_not_be_declared_in_join_config(self):
		self.assertTrue(validate_schema_config(_RelatedFieldVirtualDocType))

	def test_related_name_field_raises(self):
		class _RelatedName(AbstractVirtualDocType):
			TABLE_NAME = "Products"
			SCHEMA_CONFIG = {
				'name': {'table': 'VendorProducts', 'column': 'PartNumber', 'foreign_key': 'ProductID', 'references': 'ID'},
			}
		with self.assertRaises(ValueError):
			validate_schema_config(_RelatedName)

	def test_live_columns_are_checked_against_the_related_table(self):
		primary = ['Store UPC', 'UPC', 'ID', 'Description']
		self.assertTrue(validate_schema_config(
			_RelatedFieldVirtualDocType, discovered_columns=primary,
			related_discovered_columns={'VendorProducts': ['ID', 'ProductID', 'PartNumber']},
		))
		with self.assertRaises(ValueError) as context:
			validate_schema_config(
				_RelatedFieldVirtualDocType, discovered_columns=primary,
				related_discovered_columns={'VendorProducts': ['ID', 'ProductID']},
			)
		self.assertIn('PartNumber', str(context.exception))

	def test_missing_references_column_on_primary_table_raises(self):
		with self.assertRaises(ValueError) as context:
			validate_schema_config(_RelatedFieldVirtualDocType, discovered_columns=['Store UPC', 'UPC', 'Description'])
		self.assertIn("'ID'", str(context.exception))


class UnitTestCollapseRelatedValues(UnitTestCase):
	"""Related values arrive joined by the unit separator, duplicates included; the framework turns
	them into the display string."""

	def test_duplicates_are_removed_case_insensitively_keeping_sql_order(self):
		self.assertEqual(collapse_related_value('A-1\x1fa-1\x1fB-2\x1fB-2'), 'A-1, B-2')

	def test_value_containing_the_display_separator_is_kept_whole(self):
		self.assertEqual(collapse_related_value('ABC, 1\x1fXYZ'), 'ABC, 1, XYZ')
		self.assertEqual(collapse_related_value('ABC, 1'), 'ABC, 1')

	def test_no_related_rows_stays_none(self):
		self.assertIsNone(collapse_related_value(None))

	def test_every_read_path_collapses(self):
		raw = 'PN-1\x1fPN-1\x1fPN-2'
		cases = {
			'find_by_identifier': (
				[[{'name': 'SKU-A', 'vendor_part_numbers': raw, '_identifier_rank': 0}]],
				lambda: _RelatedFieldVirtualDocType.find_by_identifier('SKU-A')[0].vendor_part_numbers,
			),
			'get_list': (
				[[{'name': 'SKU-A', 'vendor_part_numbers': raw}]],
				lambda: _RelatedFieldVirtualDocType.get_list(
					doctype='Product', fields=['name', 'vendor_part_numbers'], filters=[], start=0,
					page_length=20, with_comment_count=False, save_user_settings=False,
				)[0].vendor_part_numbers,
			),
			'get_bulk_values': (
				[[], [], [{'name': 'SKU-A', 'vendor_part_numbers': raw}]],
				lambda: _RelatedFieldVirtualDocType.get_bulk_values(['SKU-A'], ['vendor_part_numbers'])['SKU-A'].vendor_part_numbers,
			),
		}
		for label, (responses, read) in cases.items():
			with self.subTest(path=label):
				fake_database = _fake_database(responses)
				database_patch, server_patch = _patched_database(fake_database)
				with database_patch, server_patch:
					self.assertEqual(read(), 'PN-1, PN-2')
