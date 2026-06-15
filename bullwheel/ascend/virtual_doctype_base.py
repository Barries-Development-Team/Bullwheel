# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Reusable base class for Ascend RMS virtual DocTypes.

`AbstractVirtualDocType` removes the boilerplate that every Ascend virtual
DocType controller used to repeat — `load_from_db`, `get_list`, `get_count`, the
read-only guards, connection management, and constant wiring. A concrete
controller only declares three class attributes:

    class AscendProduct(AbstractVirtualDocType):
        TABLE_NAME = "Products"
        PRIMARY_KEY_COLUMN = "ID"
        SCHEMA_CONFIG = { ... }

Everything else — FIELD_TO_COLUMN, SELECT_CLAUSE, SEARCH_COLUMNS, list ordering —
is derived from SCHEMA_CONFIG via schema_config_builder. Crucially, `get_list`
passes the list view's `order_by` through to AscendDatabase, so clicking a
column header sorts correctly (the prior per-controller bug, fixed here once for
every subclass).
"""

import re

import frappe
from frappe.model.document import Document

from bullwheel.ascend.AscendDatabase import AscendDatabase, get_default_ascend_database
from bullwheel.ascend.schema_config_builder import (
	build_field_to_column,
	build_search_columns,
	build_select_clause,
	find_primary_key_field,
)
from bullwheel.ascend.search_hook_helper import create_virtual_doctype_search


class AbstractVirtualDocType(Document):
	"""Base controller for read-only virtual DocTypes backed by an Ascend SQL table.

	Subclasses must override TABLE_NAME, PRIMARY_KEY_COLUMN, and SCHEMA_CONFIG.
	All query logic is inherited; the derived SQL constants are built lazily from
	SCHEMA_CONFIG and cached per subclass.
	"""

	# ─── Subclass Contract — override these ───────────────────────────────────
	TABLE_NAME: str = None          # Ascend SQL table name, e.g. "Products"
	PRIMARY_KEY_COLUMN: str = None  # SQL primary key column name, e.g. "ID"
	SCHEMA_CONFIG: dict = None      # fieldname -> {sql_column, fieldtype, display, searchable}

	# ─── Derived Constants (lazily built & cached per subclass) ───────────────

	@classmethod
	def field_to_column(cls):
		"""Return (and cache) the fieldname -> SQL column map for filter resolution."""
		return cls._derived("_field_to_column", lambda: build_field_to_column(cls.SCHEMA_CONFIG, cls.PRIMARY_KEY_COLUMN))

	@classmethod
	def select_clause(cls):
		"""Return (and cache) the aliased SELECT clause for this table."""
		return cls._derived("_select_clause", lambda: build_select_clause(cls.SCHEMA_CONFIG))

	@classmethod
	def search_columns(cls):
		"""Return (and cache) the list of searchable SQL columns."""
		return cls._derived("_search_columns", lambda: build_search_columns(cls.SCHEMA_CONFIG))

	@classmethod
	def primary_key_field(cls):
		"""Return (and cache) the fieldname mapped to the primary key column."""
		return cls._derived("_primary_key_field", lambda: find_primary_key_field(cls.SCHEMA_CONFIG, cls.PRIMARY_KEY_COLUMN))

	@classmethod
	def _derived(cls, attribute_name, builder):
		"""Compute a derived constant once per subclass and cache it in the subclass __dict__.

		The cache is stored on the concrete subclass (not the shared base) so two
		different DocTypes never collide on the same cached value.
		"""
		if attribute_name not in cls.__dict__:
			setattr(cls, attribute_name, builder())
		return cls.__dict__[attribute_name]

	# ─── Read Operations ──────────────────────────────────────────────────────

	def load_from_db(self):
		"""Load a single record from SQL Server by primary key and populate this document."""
		with AscendDatabase(get_default_ascend_database()) as ascend:
			record = ascend.get_record(
				self.TABLE_NAME, self.select_clause(), self.PRIMARY_KEY_COLUMN, self.name
			)

		if not record:
			raise frappe.DoesNotExistError(f"{self.doctype} '{self.name}' not found.")

		primary_key_field = self.primary_key_field()
		super(Document, self).__init__(frappe._dict({**record, "name": record[primary_key_field]}))

	@classmethod
	def get_list(cls, filters=None, page_length=20, start=0, txt=None, or_filters=None, **kwargs):
		"""Fetch a paginated, filtered, sorted list of records.

		Wires the list view's `order_by` through to AscendDatabase (mapping the
		Frappe fieldname to its SQL column) so column-header sorting works. Returns
		a list of frappe._dict rows, each with `name` set to the primary key value.
		"""
		order_column, order_direction = cls._resolve_order_by(kwargs.get("order_by"))

		with AscendDatabase(get_default_ascend_database()) as ascend:
			records = ascend.get_list(
				cls.TABLE_NAME,
				cls.select_clause(),
				cls.PRIMARY_KEY_COLUMN,
				cls.field_to_column(),
				filters=filters,
				search_columns=cls.search_columns(),
				page_length=page_length,
				start=start,
				txt=txt,
				or_filters=or_filters,
				order_by=order_column,
				order=order_direction,
			)

		primary_key_field = cls.primary_key_field()
		return [frappe._dict({**record, "name": record[primary_key_field]}) for record in records]

	@classmethod
	def get_count(cls, filters=None, txt=None, or_filters=None, **_):
		"""Return the number of records matching the current filters or search text."""
		with AscendDatabase(get_default_ascend_database()) as ascend:
			return ascend.count_records(
				cls.TABLE_NAME,
				cls.field_to_column(),
				filters=filters,
				search_columns=cls.search_columns(),
				txt=txt,
				or_filters=or_filters,
			)

	@staticmethod
	def get_stats(**_):
		"""No sidebar stats for Ascend virtual DocTypes."""
		pass

	@classmethod
	def make_search_function(cls, display_fields):
		"""Build a Link-field search hook for this DocType using its derived constants.

		Bind the result to a module-level name in the controller and register that
		dotted path under `standard_queries` in hooks.py. `display_fields` are the
		fieldnames shown after the id in each autocomplete tuple.
		"""
		return create_virtual_doctype_search(
			table_name=cls.TABLE_NAME,
			primary_key_column=cls.PRIMARY_KEY_COLUMN,
			primary_key_field=cls.primary_key_field(),
			select_clause=cls.select_clause(),
			field_to_column=cls.field_to_column(),
			search_columns=cls.search_columns(),
			display_fields=display_fields,
		)

	# ─── Order-By Resolution ──────────────────────────────────────────────────

	# Trailing sort direction on an order_by clause, e.g. " asc" / " DESC".
	_ORDER_DIRECTION_PATTERN = re.compile(r"\s+(asc|desc)\s*$", re.IGNORECASE)
	# Backtick-quoted identifier segments, e.g. `tabAscend Product` and `description`.
	_BACKTICK_SEGMENT_PATTERN = re.compile(r"`([^`]+)`")

	@classmethod
	def _resolve_order_by(cls, order_by):
		"""Translate a Frappe order_by string into an (sql_column, direction) pair.

		Frappe sends order clauses like `` `tabAscend Product`.`description` asc ``.
		Only the first clause is honored. The fieldname is mapped to its SQL column;
		if it has no mapping (e.g. the default `creation`, which no Ascend table
		has), returns (None, "ASC") so AscendDatabase falls back to ordering by the
		primary key. Direction is constrained to ASC/DESC.

		Parsing is backtick-aware rather than whitespace-split: the `tab<DocType>`
		prefix can itself contain spaces (e.g. "Ascend Product"), which would break
		a naive split.
		"""
		if not order_by:
			return None, "ASC"

		first_clause = order_by.split(",")[0].strip()
		if not first_clause:
			return None, "ASC"

		direction = "ASC"
		direction_match = cls._ORDER_DIRECTION_PATTERN.search(first_clause)
		if direction_match:
			direction = direction_match.group(1).upper()
			first_clause = first_clause[: direction_match.start()].strip()

		# The fieldname is the last backtick-quoted segment (`tabX`.`field`), or, for
		# an unquoted clause, the identifier after the final dot.
		backtick_segments = cls._BACKTICK_SEGMENT_PATTERN.findall(first_clause)
		fieldname = backtick_segments[-1] if backtick_segments else first_clause.split(".")[-1].strip()

		sql_column = cls.field_to_column().get(fieldname)
		return sql_column, direction

	# ─── Read-Only Guards ─────────────────────────────────────────────────────

	def db_insert(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")

	def db_update(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")

	def delete(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")
