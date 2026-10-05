# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

from typing import Any

from bullwheel.integrations.api_client import BaseAPIClient


class ExampleAPIClient(BaseAPIClient):
	"""Sample provider client. Copy and rename it, then add one method per endpoint."""

	def get_authentication_headers(self) -> dict[str, str]:
		# TODO: Authentication is left to the integrator. Typical options:
		#   - API key: frappe.get_single("API Integration Settings").get_password("api_key")
		#   - OAuth2: frappe.get_doc("Connected App", ...).get_active_token(user)
		raise NotImplementedError("Authentication has not been implemented")

	def list_products(self, page: int = 1) -> Any:
		return self.get("/products", params={"page": page})

	def get_product(self, product_id: str) -> Any:
		return self.get(f"/products/{product_id}")

	def create_product(self, payload: dict) -> Any:
		return self.post("/products", json=payload)
