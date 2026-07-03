# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Unit tests for AbstractVirtualDocType's query builders and schema validation.

All tests are pure unit tests with no database dependency. SCHEMA_CONFIG uses
the current simplified format: fieldname -> sql_column string.
"""

from frappe.tests import UnitTestCase

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


# ─── Test Fixtures ────────────────────────────────────────────────────────────


class _SimpleVirtualDocType(AbstractVirtualDocType):
	"""No JOINs — straightforward field-to-column mapping."""
	TABLE_NAME = "Products"
	SCHEMA_CONFIG = {
		'name':        'ID',
		'description': 'Description',
		'quantity':    'Quantity',
		'store_sku':   '[Store UPC]',
	}


class _AliasedJoinVirtualDocType(AbstractVirtualDocType):
	"""JOIN with an alias — table-qualified column references."""
	TABLE_NAME = "Products"
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
	NAME_EXPRESSION = "CONCAT(StyleNumber, '-', Size)"
	SCHEMA_CONFIG = {
		'description': 'Description',
		'size':        'Size',
	}


class _NameExpressionJoinVirtualDocType(AbstractVirtualDocType):
	"""NAME_EXPRESSION that references a declared join alias and the primary table."""
	TABLE_NAME = "Products"
	JOIN_CONFIG = [
		{'join': 'LEFT JOIN', 'table': 'Categories', 'alias': 'cat', 'on': 'Products.TopicID = cat.ID'}
	]
	NAME_EXPRESSION = "CONCAT(Products.ID, '-', cat.Topic)"
	SCHEMA_CONFIG = {
		'description': 'Products.Description',
	}


# ─── validate_schema_config ───────────────────────────────────────────────────


class UnitTestValidateSchemaConfig(UnitTestCase):

	def test_valid_schema_returns_true(self):
		self.assertTrue(_SimpleVirtualDocType.validate_schema_config())

	def test_empty_schema_raises(self):
		class _Empty(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {}
		with self.assertRaises(ValueError):
			_Empty.validate_schema_config()

	def test_none_schema_raises(self):
		class _NullSchema(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = None
		with self.assertRaises(ValueError):
			_NullSchema.validate_schema_config()

	def test_missing_name_entry_raises(self):
		class _NoName(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {'description': 'Description'}
		with self.assertRaises(ValueError):
			_NoName.validate_schema_config()

	def test_null_name_column_raises(self):
		class _NullName(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {'name': None}
		with self.assertRaises(ValueError):
			_NullName.validate_schema_config()

	def test_non_string_value_raises(self):
		"""A dict value (old SCHEMA_CONFIG format accidentally used) should be caught."""
		class _DictValue(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {
				'name':        'ID',
				'description': {'sql_column': 'Description'},
			}
		with self.assertRaises(ValueError):
			_DictValue.validate_schema_config()

	def test_discovered_columns_valid_passes(self):
		self.assertTrue(
			_SimpleVirtualDocType.validate_schema_config(
				discovered_columns=['ID', 'Description', 'Quantity', 'Store UPC']
			)
		)

	def test_discovered_columns_missing_column_raises(self):
		with self.assertRaises(ValueError):
			_SimpleVirtualDocType.validate_schema_config(
				discovered_columns=['ID', 'Description']  # Quantity and Store UPC absent
			)

	def test_qualified_columns_skipped_without_additional_discovered(self):
		"""Table-qualified columns (e.g. Products.ID) are not checked when
		additional_discovered_columns is not provided."""
		self.assertTrue(
			_AliasedJoinVirtualDocType.validate_schema_config(
				discovered_columns=['ID', 'Description', 'Topic']
			)
		)

	def test_qualified_columns_checked_against_additional_discovered(self):
		with self.assertRaises(ValueError):
			_AliasedJoinVirtualDocType.validate_schema_config(
				additional_discovered_columns=['ID', 'Description']  # Topic (for cat.Topic) absent
			)


# ─── validate_schema_config — NAME_EXPRESSION ─────────────────────────────────


class UnitTestValidateNameExpression(UnitTestCase):

	def test_name_expression_without_name_entry_passes(self):
		"""A NAME_EXPRESSION satisfies the primary-key requirement even when SCHEMA_CONFIG omits 'name'."""
		self.assertTrue(_NameExpressionVirtualDocType.validate_schema_config())

	def test_name_expression_skips_column_existence_check(self):
		"""The expression is not a plain column, so it isn't checked against discovered_columns —
		only the other mapped fields are."""
		self.assertTrue(
			_NameExpressionVirtualDocType.validate_schema_config(
				discovered_columns=['Description', 'Size']  # deliberately omits StyleNumber
			)
		)

	def test_neither_name_nor_expression_raises(self):
		class _NoPrimaryKey(AbstractVirtualDocType):
			TABLE_NAME = "T"
			SCHEMA_CONFIG = {'description': 'Description'}
		with self.assertRaises(ValueError):
			_NoPrimaryKey.validate_schema_config()

	def test_non_string_name_expression_raises(self):
		class _BadExpression(AbstractVirtualDocType):
			TABLE_NAME = "T"
			NAME_EXPRESSION = 123
			SCHEMA_CONFIG = {'description': 'Description'}
		with self.assertRaises(ValueError):
			_BadExpression.validate_schema_config()

	def test_declared_qualifiers_pass(self):
		"""Qualifiers resolving to TABLE_NAME or a JOIN_CONFIG alias are accepted."""
		self.assertTrue(_NameExpressionJoinVirtualDocType.validate_schema_config())

	def test_undeclared_qualifier_raises(self):
		class _UndeclaredAlias(AbstractVirtualDocType):
			TABLE_NAME = "Products"
			NAME_EXPRESSION = "CONCAT(Products.ID, '-', missing.Topic)"
			SCHEMA_CONFIG = {'description': 'Products.Description'}
		with self.assertRaises(ValueError) as context:
			_UndeclaredAlias.validate_schema_config()
		self.assertIn('missing', str(context.exception))

	def test_dots_inside_brackets_and_literals_do_not_false_positive(self):
		"""Dots inside bracket-quoted names or string literals must not register as qualifiers."""
		class _DottedLiteral(AbstractVirtualDocType):
			TABLE_NAME = "Things"
			NAME_EXPRESSION = "CONCAT([Style.No], '.', Size)"
			SCHEMA_CONFIG = {'description': 'Description'}
		self.assertTrue(_DottedLiteral.validate_schema_config())


# ─── _build_select_clause ─────────────────────────────────────────────────────


class UnitTestBuildSelectClause(UnitTestCase):

	def test_no_fields_selects_all_schema_fields(self):
		result = _SimpleVirtualDocType._build_select_clause()
		self.assertEqual(
			result,
			'SELECT TOP 20 ID AS name, Description AS description, Quantity AS quantity, [Store UPC] AS store_sku'
		)

	def test_specific_fields_are_selected(self):
		result = _SimpleVirtualDocType._build_select_clause(['name', 'description'], limit=10)
		self.assertEqual(result, 'SELECT TOP 10 ID AS name, Description AS description')

	def test_custom_limit_is_applied(self):
		result = _SimpleVirtualDocType._build_select_clause(['name'], limit=50)
		self.assertIn('SELECT TOP 50', result)

	def test_unmapped_fields_are_skipped(self):
		result = _SimpleVirtualDocType._build_select_clause(['name', 'nonexistent', 'description'])
		self.assertEqual(result, 'SELECT TOP 20 ID AS name, Description AS description')

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
		result = _SimpleVirtualDocType._build_where_clause([], [], values)
		self.assertEqual(result, 'WHERE 1=1')
		self.assertEqual(values, [])

	def test_single_and_filter(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			[('AscendProduct', 'description', '=', 'Red Ski')], [], values
		)
		self.assertEqual(result, 'WHERE (Description = %s)')
		self.assertEqual(values, ['Red Ski'])

	def test_multiple_and_filters(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			[
				('AscendProduct', 'description', '=',  'Red Ski'),
				('AscendProduct', 'quantity',    '>',   0),
			], [], values
		)
		self.assertEqual(result, 'WHERE (Description = %s AND Quantity > %s)')
		self.assertEqual(values, ['Red Ski', 0])

	def test_single_or_filter(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			[], [('AscendProduct', 'store_sku', 'LIKE', '%12345%')], values
		)
		self.assertEqual(result, 'WHERE ([Store UPC] LIKE %s)')
		self.assertEqual(values, ['%12345%'])

	def test_combined_and_and_or_filters(self):
		values = []
		result = _SimpleVirtualDocType._build_where_clause(
			[('AscendProduct', 'quantity',    '>',    0)],
			[('AscendProduct', 'description', 'LIKE', '%ski%')],
			values
		)
		self.assertEqual(result, 'WHERE (Quantity > %s) AND (Description LIKE %s)')
		self.assertEqual(values, [0, '%ski%'])

	def test_name_filter_uses_expression(self):
		"""A filter on 'name' resolves to NAME_EXPRESSION, so link-title and list name lookups
		match against the same expression used in the projection."""
		values = []
		result = _NameExpressionVirtualDocType._build_where_clause(
			[('Thing', 'name', '=', 'SN-100-M')], [], values
		)
		self.assertEqual(result, "WHERE (CONCAT(StyleNumber, '-', Size) = %s)")
		self.assertEqual(values, ['SN-100-M'])


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


# ─── _validate_and_clean_fields ───────────────────────────────────────────────


class UnitTestValidateAndCleanFields(UnitTestCase):

	def test_strips_backtick_qualified_table_name(self):
		fields = ['`tabAscend Product`.`name`', 'description']
		_SimpleVirtualDocType._validate_and_clean_fields(fields, 'Ascend Product')
		self.assertEqual(fields, ['name', 'description'])

	def test_removes_non_string_field_entries(self):
		fields = [0, 'name']
		_SimpleVirtualDocType._validate_and_clean_fields(fields, 'Ascend Product')
		self.assertEqual(fields, ['name'])

	def test_plain_fieldnames_are_not_modified(self):
		fields = ['name', 'description', 'quantity']
		_SimpleVirtualDocType._validate_and_clean_fields(fields, 'Ascend Product')
		self.assertEqual(fields, ['name', 'description', 'quantity'])
