# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from bullwheel.bullwheel_core import clear_bullwheel_settings_cache


class BullwheelSettings(Document):
	def on_update(self):
		"""Drop Bullwheel's own cached copies of these settings so a change applies right away,
		instead of after the cache expires."""
		clear_bullwheel_settings_cache()
