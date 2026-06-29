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
	with MSSQLDatabase(server_document) as database:
		result = database.test_connection()
		if result == 'success':
			frappe.msgprint(msg="Connection test succeeded!", title="Success", indicator="green")
		else:
			frappe.msgprint(
				msg=f"Please check your database and authentication information and try again. The error is as follows:\n{result}",
				title="Connection Test Failed",
				indicator="red",
			)
		

