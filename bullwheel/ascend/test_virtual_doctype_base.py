# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for AbstractVirtualDocType's query builders and schema validation.

All tests are pure unit tests with no SQL Server dependency (get_count is exercised
against a mocked MSSQLDatabase). SCHEMA_CONFIG uses the current simplified format:
fieldname -> sql_column string.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType
from bullwheel.ascend.validate_virtual_doctypes import validate_schema_config


# ─── Test Fixtures ────────────────────────────────────────────────────────────


class _SimpleVirtualDocType(AbstractVirtualDocType):
	"""No JOINs — straightforward field-to-column mapping."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	SCHEMA_CONFIG = {
		'name':        'ID',
		'description': 'Description',
		'quantity':    'Quantity',
		'store_sku':   '[Store UPC]',
	}


class _AliasedJoinVirtualDocType(AbstractVirtualDocType):
	"""JOIN with an alias — table-qualified column references."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	JOIN_CONFIG = [
		{'join': 'LEFT JOIN', 'table': 'Categories', 'alias': 'cat', 'on': 'Products.TopicID = cat.ID'}
	]
	SCHEMA_CONFIG = {
		'name':        'Products.ID',
		'description': 'Products.Description',
		'category':    'cat.Topic',
	}


class _UnaliasedJoinVirtualDocType(AbstractVirtualDocType):
	"""JOIN without an alias — no AS clause should appear in the output."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	JOIN_CONFIG = [
		{'join': 'LEFT JOIN', 'table': 'Categories', 'on': 'Products.TopicID = Categories.ID'}
	]
	SCHEMA_CONFIG = {
		'name':        'Products.ID',
		'description': 'Products.Description',
	}


class _NameExpressionVirtualDocType(AbstractVirtualDocType):
	"""Primary key is a computed SQL expression; 'name' is omitted from SCHEMA_CONFIG."""
	TABLE_NAME = "Things"
	SHOW_FIELD_WARNINGS = False
	NAME_EXPRESSION = "CONCAT(StyleNumber, '-', Size)"
	SCHEMA_CONFIG = {
		'description': 'Description',
		'size':        'Size',
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
		'description': 'Products.Description',
	}


class _AltNameVirtualDocType(AbstractVirtualDocType):
	"""'name' filters widen across ALT_NAME_RESOLUTION_FIELDS."""
	TABLE_NAME = "Products"
	SHOW_FIELD_WARNINGS = False
	ALT_NAME_RESOLUTION_FIELDS = ['upc']
	SCHEMA_CONFIG = {
		'name':        '[Store UPC]',
		'upc':         'UPC',
		'description': 'Description',
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
			SCHEMA_CONFIG = {'description': 'Description'}
		with self.assertRaises(ValueError):
			validate_schema_config(_NoName)

	def test_null_name_column_raises(self):
		class _NullName(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {'name': None}
		with self.assertRaises(ValueError):
			validate_schema_config(_NullName)

	def test_non_string_value_raises(self):
		"""A dict value (old SCHEMA_CONFIG format accidentally used) should be caught."""
		class _DictValue(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {
				'name':        'ID',
				'description': {'sql_column': 'Description'},
			}
		with self.assertRaises(ValueError):
			validate_schema_config(_DictValue)

	def test_alt_name_resolution_fields_must_be_mapped(self):
		class _UnmappedAltField(AbstractVirtualDocType):
			TABLE_NAME = "T"
			ALT_NAME_RESOLUTION_FIELDS = ['upc']
			SCHEMA_CONFIG = {'name': 'ID'}
		with self.assertRaises(ValueError) as context:
			validate_schema_config(_UnmappedAltField)
		self.assertIn('upc', str(context.exception))

	def test_mapped_alt_name_resolution_fields_pass(self):
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
		"""A sql_column qualified with a table/alias not in TABLE_NAME + JOIN_CONFIG is a
		structural error, caught without any introspected columns."""
		class _UndeclaredColumnQualifier(AbstractVirtualDocType):
			TABLE_NAME = "Products"
			SCHEMA_CONFIG = {
				'name':     'Products.ID',
				'category': 'cat.Topic',  # no JOIN_CONFIG declares 'cat'
			}
		with self.assertRaises(ValueError) as context:
			validate_schema_config(_UndeclaredColumnQualifier)
		self.assertIn('cat', str(context.exception))


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
			SCHEMA_CONFIG = {'description': 'Description'}
		with self.assertRaises(ValueError):
			validate_schema_config(_NoPrimaryKey)

	def test_non_string_name_expression_raises(self):
		class _BadExpression(AbstractVirtualDocType):
			TABLE_NAME = "T"
			NAME_EXPRESSION = 123
			SCHEMA_CONFIG = {'description': 'Description'}
		with self.assertRaises(ValueError):
			validate_schema_config(_BadExpression)

	def test_declared_qualifiers_pass(self):
		"""Qualifiers resolving to TABLE_NAME or a JOIN_CONFIG alias are accepted."""
		self.assertTrue(validate_schema_config(_NameExpressionJoinVirtualDocType))

	def test_undeclared_qualifier_raises(self):
		class _UndeclaredAlias(AbstractVirtualDocType):
			TABLE_NAME = "Products"
			NAME_EXPRESSION = "CONCAT(Products.ID, '-', missing.Topic)"
			SCHEMA_CONFIG = {'description': 'Products.Description'}
		with self.assertRaises(ValueError) as context:
			validate_schema_config(_UndeclaredAlias)
		self.assertIn('missing', str(context.exception))

	def test_dots_inside_brackets_and_literals_do_not_false_positive(self):
		"""Dots inside bracket-quoted names or string literals must not register as qualifiers."""
		class _DottedLiteral(AbstractVirtualDocType):
			TABLE_NAME = "Things"
			NAME_EXPRESSION = "CONCAT([Style.No], '.', Size)"
			SCHEMA_CONFIG = {'description': 'Description'}
		self.assertTrue(validate_schema_config(_DottedLiteral))


# ─── _build_select_clause ─────────────────────────────────────────────────────


class UnitTestBuildSelectClause(UnitTestCase):

	def test_no_fields_selects_all_schema_fields(self):
		result = _SimpleVirtualDocType._build_select_clause()
		self.assertEqual(
			result,
			'SELECT ID AS name, Description AS description, Quantity AS quantity, [Store UPC] AS store_sku'
		)

	def test_specific_fields_are_selected(self):
		result = _SimpleVirtualDocType._build_select_clause(['name', 'description'])
		self.assertEqual(result, 'SELECT ID AS name, Description AS description')

	def test_unmapped_fields_are_skipped(self):
		result = _SimpleVirtualDocType._build_select_clause(['name', 'nonexistent', 'description'])
		self.assertEqual(result, 'SELECT ID AS name, Description AS description')

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
		self.assertEqual(result, 'WHERE (Description = %s)')
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
		self.assertEqual(result, 'WHERE (Description = %s AND Quantity > %s)')
		self.assertEqual(values, ['Red Ski', 0])

	def test_single_or_filter(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, [], [('AscendProduct', 'store_sku', 'LIKE', '%12345%')]
		)
		self.assertEqual(result, 'WHERE ([Store UPC] LIKE %s)')
		self.assertEqual(values, ['%12345%'])

	def test_combined_and_and_or_filters(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values,
			[('AscendProduct', 'quantity',    '>',    0)],
			[('AscendProduct', 'description', 'LIKE', '%ski%')]
		)
		self.assertEqual(result, 'WHERE (Quantity > %s) AND (Description LIKE %s)')
		self.assertEqual(values, [0, '%ski%'])

	def test_three_element_conditions_are_accepted(self):
		"""Frappe's desk validation allows [fieldname, operator, value] conditions."""
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, [('description', '=', 'Red Ski')], []
		)
		self.assertEqual(result, 'WHERE (Description = %s)')
		self.assertEqual(values, ['Red Ski'])

	def test_dict_filters_are_accepted(self):
		"""Programmatic callers pass {field: value} or {field: (operator, value)}."""
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, {'description': 'Red Ski', 'quantity': ('>', 0)}, []
		)
		self.assertEqual(result, 'WHERE (Description = %s AND Quantity > %s)')
		self.assertEqual(values, ['Red Ski', 0])

	def test_qualified_filter_fieldname_is_cleaned(self):
		"""A backtick-qualified fieldname must resolve like its bare form."""
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, [('AscendProduct', '`tabAscend Product`.`description`', '=', 'Red Ski')], []
		)
		self.assertEqual(result, 'WHERE (Description = %s)')
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
		self.assertEqual(result, 'WHERE (Description = %s)')
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
		self.assertEqual(result, 'WHERE (Description IS NOT NULL)')
		self.assertEqual(values, [])

	def test_is_not_set_translates_to_is_null(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			values, [('AscendProduct', 'description', 'is', 'not set')], []
		)
		self.assertEqual(result, 'WHERE (Description IS NULL)')
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
		self.assertEqual(result, 'WHERE (([Store UPC] = %s OR UPC = %s))')
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
		self.assertIn('Description = %s', captured['query'])
		self.assertEqual(captured['values'], ['Red Ski'])
