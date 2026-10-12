# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Helpers shared by unit tests."""

from contextlib import contextmanager

import frappe


@contextmanager
def patch_database(replacement):
	"""Stand in for frappe.db for the duration of a block, then put back whatever was there.

	unittest.mock.patch.object(frappe.local, 'db', ..., create=True) must not be used for this:
	frappe.local keeps its attributes outside __dict__, so mock cannot see the connected database,
	decides the attribute never existed, and deletes it on exit — leaving every later test in the
	run with an unbound frappe.db."""

	missing = object()
	original = getattr(frappe.local, 'db', missing)
	frappe.local.db = replacement
	try:
		yield
	finally:
		if original is missing:
			del frappe.local.db
		else:
			frappe.local.db = original
