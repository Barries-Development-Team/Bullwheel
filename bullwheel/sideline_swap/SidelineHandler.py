# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

from typing import Any

from bullwheel.api_integrations.api_client import BaseAPIClient


class SidelineAPIClient(BaseAPIClient):
	"""Sample provider client. Copy and rename it, then add one method per endpoint."""

	def get_authentication_headers(self) -> dict[str, str]:
		# TODO: Authentication is left to the integrator. Typical options:
		#   - API key: frappe.get_single("API Integration Settings").get_password("api_key")
		#   - OAuth2: frappe.get_doc("Connected App", ...).get_active_token(user)
		raise NotImplementedError("Authentication has not been implemented")

    


