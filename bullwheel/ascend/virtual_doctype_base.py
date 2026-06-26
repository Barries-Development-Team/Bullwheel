# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import re

import frappe
from frappe.model.document import Document

from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.bullwheel_core.doctype.bullwheel_settings.bullwheel_settings import get_default_ascend_database

# ─── Static Helper Functions ───────────────────────────────────────


class AbstractVirtualDocType(Document):

	# ─── Subclass Contract — override these ───────────────────────────────────
	TABLE_NAME: str = None        # Ascend SQL table name, e.g. "Products"
	JOIN_CONFIG: list = None      # List of JOIN descriptors — see _build_join_clause for the dict shape
	SCHEMA_CONFIG: dict = None    # Fieldname -> SQL Column
	                               # Must include a "name" entry whose sql_column is the primary key.

	# ─── Helper Methods  ──────────────────────────────────────────────────────

	def build_select_clause(self, fields: list = []) -> str:
		"""Generate an SQL Select clause to fetch the provided fields. If no fields are provided, all are selected."""
		if len(fields) <= 0:
			fields = self.SCHEMA_CONFIG.keys()
		select_statements = []
		for field in fields:
			select_statements.append(f'{self.SCHEMA_CONFIG.get(field)} AS {field}')
		return ", ".join(select_statements)
	
	# ─── Read Operations ──────────────────────────────────────────────────────

	def load_from_db(self):
		query = f'SELECT {self.build_select_clause()} FROM {self.TABLE_NAME}'

		with MSSQLDatabase(get_default_ascend_database()) as db:
			record = db.sql(
				query=query,
				values=[]
			)

		super(Document, self).__init__()

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