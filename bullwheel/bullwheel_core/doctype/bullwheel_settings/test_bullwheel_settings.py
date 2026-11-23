# Copyright (c) 2026, Barrie's Ski and Sports and Contributors
# See license.txt

# import frappe
from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestBullwheelSettings(IntegrationTestCase):
	"""
	Integration tests for BullwheelSettings.
	Use this class for testing interactions between multiple components.
	"""

	pass


from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from bullwheel.bullwheel_core import DEFAULT_ASCEND_DATABASE_CACHE_KEY
from bullwheel.bullwheel_core.doctype.bullwheel_settings.bullwheel_settings import BullwheelSettings


class UnitTestBullwheelSettingsCache(UnitTestCase):

	def test_saving_settings_clears_the_cached_default_database(self):
		cache = MagicMock()
		with patch.object(frappe, "cache", cache):
			BullwheelSettings.on_update(MagicMock())
		cache.delete_value.assert_called_once_with(DEFAULT_ASCEND_DATABASE_CACHE_KEY)
