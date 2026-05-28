# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
import json
from frappe.model.document import Document
from frappe.utils.password import get_decrypted_password

from bullwheel.database.SQLServer import MSSQLDatabase


class SQLServer(Document):
	pass


@frappe.whitelist()
def test_connection(**kwargs):
	document = json.loads(kwargs.get('doc'))
	try:
		with MSSQLDatabase(
			server=document.get('server_name'),
			username=document.get('username'),
			password=get_decrypted_password("SQL Server", document.get('name'), fieldname="password"),
			database=document.get('database_name')
		) as database:
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

