# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import frappe
from frappe.model.document import Document
from bullwheel.database.SQLServer import MSSQLDatabase


def get_default_ascend_database():
		default_database = frappe.db.get_single_value('Bullwheel Settings', 'default_database')
		return frappe.get_doc("SQL Server", default_database)


class VirtualDoctypeBase(Document):

	@classmethod
	def load_from_db(self):
		with MSSQLDatabase(get_default_ascend_database()) as ascend:
			result = ascend.sql()

			

		super(Document, self).__init__('''doc variable''')
			 
			 
		  
	
	# ─── Read-Only Guards ─────────────────────────────────────────────────────
	
	'''The following methods are required for Virtual Doctypes, however they are not implemented in order to maintain
	the read-only nature of the Ascend Virtual Doctypes.'''

	def db_insert(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")

	def db_update(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")

	def delete(self, *args, **kwargs):
		raise NotImplementedError(f"{self.doctype} is read-only.")