# Copyright (c) 2026 Bonneville Ridge LLC

import frappe
import frappe.database
import pymssql

# PROTOTYPE CODE


# TODO: Remove connection info before commiting changes.
def main():

	# pymssql example usage
	connection = pymssql.connect(server="192.168.10.43", user="...", password="...", database="Ascend")

	cursor = connection.cursor()
	cursor.execute(
		"""
        SELECT FirstName, LastName, Title, Phone, EMail, IsServiceTechnician, EmployeeId
        FROM Users
        WHERE Active = 1 AND Hide = 0
        """
	)
	for row in cursor.fetchall():
		print(row)


# TODO: Remove after prototyping
if __name__ == "__main__":
	main()
