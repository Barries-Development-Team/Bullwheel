# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
import json
from frappe.model.document import Document

from bullwheel.database.SQLServer import MSSQLDatabase


class SQLServer(Document):
	pass


@frappe.whitelist()
def test_connection(**kwargs):
	document = json.loads(kwargs.get('doc'))
	server_document = frappe.get_doc("SQL Server", document.get('name'))
	try:
		with MSSQLDatabase(server_document) as database:
			if database.test_connection():
				frappe.msgprint(msg="Connection test succeeded!", title="Success", indicator="green")
			else:
				raise ConnectionError
	except:
		frappe.msgprint(
					msg="Please check your database and authentication information and try again.",
					title="Connection Test Failed",
					indicator="red",
				)

