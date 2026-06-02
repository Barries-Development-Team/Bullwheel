# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document
from bullwheel.database.SQLServer import MSSQLDatabase
from bullwheel.ascend.ascend_utilities import get_default_ascend_database


class AscendProduct(Document):
	
	def db_insert(self, *args, **kwargs):
		raise NotImplementedError

	def load_from_db(self, *args, **kwargs):
		raise NotImplementedError

	def db_update(self, *args, **kwargs):
		raise NotImplementedError

	def delete(self, *args, **kwargs):
		raise NotImplementedError

	@staticmethod
	def get_list(filters=None, page_length=20, **kwargs):
		
		with MSSQLDatabase(server_document=get_default_ascend_database()) as database:
			products = database.get_all(table='Products',limit=page_length)

		product_list = [product for product in products]


	@staticmethod
	def get_count(filters=None, **kwargs):
		pass

	@staticmethod
	def get_stats(**kwargs):
		pass