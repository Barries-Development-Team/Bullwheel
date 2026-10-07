# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import frappe
from frappe.model.document import Document

from bullwheel.api_integrations.example_client import ExampleAPIClient


class APIIntegrationSettings(Document):
	def get_client(self) -> ExampleAPIClient:
		"""Build an API client from these settings. Swap in your provider's client class."""
		if not self.enabled:
			frappe.throw("The API integration is not enabled")
		return ExampleAPIClient(base_url=self.base_url, timeout=self.timeout)
