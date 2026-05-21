# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from bullwheel.database.SQLServer import MSSQLDatabase


class SQLServer(Document):
	pass


@frappe.whitelist()
def test_connection(docname: str):
	document = frappe.get_doc("SQL Server", docname)
	with MSSQLDatabase(
		server=document.server_name,
		username=document.username,
		password=document.password,
		database=document.database_name,
	) as database:
		if database.test_connection():
			frappe.msgprint(msg="Connection test succeeded!", title="Success", indicator="green")
		else:
			frappe.msgprint(
				msg="Connection test failed. Please check your database and authentication information and try again.",
				title="Failure",
				indicator="red",
			)
