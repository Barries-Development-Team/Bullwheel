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

def _clean_field_parameter(field):
	"""Removes assumed table name and formating from field names.
	For example, the parameter '`tabVendor`.`name`' should be resolved to just 'name'."""
	return field.split('.')[-1].replace('`','')


class AbstractVirtualDocType(Document):

	# ─── Subclass Contract — override these ───────────────────────────────────
	TABLE_NAME: str = None        # Ascend SQL table name, e.g. "Products"
	JOIN_CONFIG: list = None      # List of JOIN descriptors — see _build_join_clause for the dict shape
	SCHEMA_CONFIG: dict = None    # Fieldname -> SQL Column
								   # Must include a "name" entry whose sql_column is the primary key.

	# ─── Helper Methods  ──────────────────────────────────────────────────────

	@classmethod
	def build_select_clause(cls, fields: list = []) -> str:
		"""Generate an SQL Select clause to fetch the provided fields. If no fields are provided, all are selected."""
		if len(fields) <= 0:
			fields = cls.SCHEMA_CONFIG.keys()
		else:
			fields = [_clean_field_parameter(field) for field in fields] # Pre-generated table names like "tabProducts" can sneak in. This removes those.
		select_statements = []
		for field in fields:
			sql_column = cls.SCHEMA_CONFIG.get(field)
			if sql_column is not None:
				select_statements.append(f'{cls.SCHEMA_CONFIG.get(field)} AS {field}')
		return ', '.join(select_statements)
	
	@classmethod
	def build_join_clause(cls) -> str:
		join_statements = []
		for config in cls.JOIN_CONFIG:
			join_statements.append(f'{config.get('join')} {config.get('table')} AS {config.get('alias')} ON {config.get('on')}')
		return ' '.join(join_statements)
	
	@classmethod
	def build_where_clause(cls, filters: list, values: list = []) -> str:
		where_statements = []
		for doctype, field, type, value in filters:
			where_statements.append(f' WHERE {cls.SCHEMA_CONFIG.get(field)} {type} %s')
			values.append(value) # Appends the value to the list of values passed as an argument.
		return ' '.join(where_statements)

	
	# ─── Read Operations ──────────────────────────────────────────────────────

	# TODO: Finish
	def load_from_db(self):
		query = f'SELECT {self.build_select_clause()} FROM {self.TABLE_NAME}'

		with MSSQLDatabase(get_default_ascend_database()) as db:
			record = db.sql(
				query=query,
				values=[]
			)

		super(Document, self).__init__()
	
	@classmethod
	def get_list(cls, doctype: str, fields: list, filters: list, order_by: str, start: int, page_length: int, group_by: str, with_comment_count: str, save_user_settings: bool, strict,  **args):

		query = f'SELECT TOP {page_length} {cls.build_select_clause(fields)} FROM {cls.TABLE_NAME}'
		values = []
		if cls.JOIN_CONFIG is not None:
			query += f' {cls.build_join_clause()}'
		query += f' {cls.build_where_clause(filters, values)}' # Values are appended to the list inside this method.
		# TODO: Implement order by
		

		with MSSQLDatabase(get_default_ascend_database()) as db:
			records = db.sql(
				query=query,
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