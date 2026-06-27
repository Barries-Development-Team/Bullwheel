# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import re
import uuid

import frappe
from frappe.model.document import Document

from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core.doctype.bullwheel_settings.bullwheel_settings import get_default_ascend_database

# ─── Static Helper Functions ───────────────────────────────────────


def _to_document_dict(record):
	"""Returns a proper frappe dict with every `uuid.UUID` value converted to its string form"""
	return frappe._dict({
		fieldname: (str(value) if isinstance(value, uuid.UUID) else value)
		for fieldname, value in record.items()
	})

def _clean_fieldname(field):
	"""Removes assumed table name and formating from field names.
	For example, the parameter '`tabVendor`.`name`' should be resolved to just 'name'."""
	return field.split('.')[-1].replace('`','')

def _parse_parameter(parameter: str) -> list[str]:
	"""Split a string on whitespace, but text inside backtick pairs is treated as a single token."""
	return re.findall(r'(?:`[^`]*`|\S)+', parameter)


class AbstractVirtualDocType(Document):

	# ─── Subclass Contract — override these ───────────────────────────────────
	TABLE_NAME: str = None       		# Ascend SQL table name, e.g. "Products"
	JOIN_CONFIG: list = None     		# List of JOIN descriptors — see _build_join_clause for the dict shape
	SCHEMA_CONFIG: dict = None    		# Fieldname -> SQL Column. Must include a "name" entry whose sql_column is the primary key.
	SHOW_FIELD_WARNINGS: bool = True	# Display a warning in the console if an expected field has no mapping in SCHEMA_CONFIG


	# ─── Helper Methods  ──────────────────────────────────────────────────────

	@classmethod
	def _build_select_clause(cls, fields: list = [], limit: int = 20) -> str:
		"""Generate an SQL Select clause to fetch the provided fields. If no fields are provided, all are selected."""
		if len(fields) <= 0:
			fields = cls.SCHEMA_CONFIG.keys()

		select_statements = []
		for field in fields:
			sql_column = cls.SCHEMA_CONFIG.get(field)
			if sql_column is not None:
				select_statements.append(f'{cls.SCHEMA_CONFIG.get(field)} AS {field}')
			
		return f'SELECT TOP {limit} ' + ', '.join(select_statements)
	
	@classmethod
	def _build_join_clause(cls) -> str:
		join_statements = []
		for config in cls.JOIN_CONFIG:
			join_statements.append(f'{config.get('join')} {config.get('table')} AS {config.get('alias')} ON {config.get('on')}')
		return ' '.join(join_statements)
	
	@classmethod
	def _build_where_clause(cls, filters: list, values: list = []) -> str:
		"""Build the WHERE clause from a list of filters. Filter values are appended to the passed values list."""
		where_statements = []
		for doctype, field, type, value in filters:
			where_statements.append(f'{cls.SCHEMA_CONFIG.get(field)} {type} %s')
			values.append(value) # Appends the value to the list of values passed as an argument.
		return 'WHERE ' + ' AND '.join(where_statements)
	
	@classmethod
	def _build_order_by_clause(cls, order_by: str) -> str:
		parameters = order_by.split(', ')
		order_by_statements = []
		
		for parameter in parameters:
			field, order = _parse_parameter(parameter)
			sql_column = cls.SCHEMA_CONFIG.get(field)
			if sql_column is not None:
				order_by_statements.append(f'{_clean_fieldname(field)} {order.upper()}')
			else:
				order_by_statements.append('(SELECT NULL)')

		if len(order_by_statements) <= 0:
			return None

		return 'ORDER BY ' + ', '.join(order_by_statements)

	
	# ─── Read Operations ──────────────────────────────────────────────────────

	# TODO: Finish
	def load_from_db(self):
		query_clauses = []
		# SELECT
		query_clauses.append(self._build_select_clause())
		# FROM
		query_clauses.append(f'FROM {self.TABLE_NAME}')
		# JOIN
		if self.JOIN_CONFIG is not None:
			query_clauses.append(self._build_join_clause())
		# WHERE
		query_clauses.append(f'WHERE {self.SCHEMA_CONFIG.get('name')} = %s')

		with MSSQLDatabase(get_default_ascend_database()) as db:
			records = db.sql(
				query=' '.join(query_clauses),
				values=[self.name],
				as_dict=True
			)

		if not records:
			raise frappe.DoesNotExistError(f"{self.doctype} '{self.name}' not found.")

		super(Document, self).__init__(_to_document_dict(records[0]))
	
	@classmethod
	def get_list(cls, doctype: str, fields: list, filters: list, start: int, page_length: int, with_comment_count: str, save_user_settings: bool, group_by: str = None, order_by: str = None, strict = None, **args):
		
		# Reformat incorrectly assumed table names from fields list. E.g. '`tabAscend Product`.`name`' to 'name' 
		invalid_field_indices = [] # List of field paramater indicies not compatible with this virtual doctype.
		for i in range(len(fields)):
			if type(fields[i]) != str:
				invalid_field_indices.append(i)
				print(f"\033[33mAscend Virtual Doc Warning: Invalid field parameter {fields[i]}.\033[0m")
			fields[i] = _clean_fieldname(fields[i])

		for i in invalid_field_indices:
			del fields[i]

		# Display a warning to the console if an expected field has no mapping in the schema config.
		if cls.SHOW_FIELD_WARNINGS:
			for field in fields:
				if cls.SCHEMA_CONFIG.get(field) is None:
					print(f"\033[33mAscend Virtual Doc Warning: No field mapping exists for {field} in {doctype}.\033[0m")
			print(f"\033[33mIf this is expected, you can disable this warning with SHOW_FIELD_WARNINGS = False.\033[0m")

		query_clauses = []
		values = []

		# SELECT
		query_clauses.append(cls._build_select_clause(fields, page_length))
		# FROM
		query_clauses.append(f'FROM {cls.TABLE_NAME}')
		# JOIN
		if cls.JOIN_CONFIG is not None:
			query_clauses.append(cls._build_join_clause())
		# WHERE
		query_clauses.append(cls._build_where_clause(filters, values)) # Values are appended to the list inside this method.
		# ORDER BY
		query_clauses.append(cls._build_order_by_clause(order_by))

		with MSSQLDatabase(get_default_ascend_database()) as db:
			records = db.sql(
				query=' '.join(query_clauses),
				values=values,
				as_dict=True
			)

		return [_to_document_dict(record) for record in records]
	
	def get_count():
		pass

	# ─── Search Function Hook ─────────────────────────────────────────────


	# ─── Order-By Resolution ──────────────────────────────────────────────────

		  	
	# ─── Read-Only Guards ─────────────────────────────────────────────────────
	
	'''The following methods are required for Virtual Doctypes, however they are not implemented in order to maintain
	the read-only nature of the Ascend Virtual Doctypes.'''

	def db_insert(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")

	def db_update(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")

	def delete(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")