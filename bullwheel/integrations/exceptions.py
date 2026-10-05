# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import frappe


class APIClientError(frappe.ValidationError):
	"""Base exception for all third-party API client errors."""

	pass


class APIConnectionError(APIClientError):
	"""Raised when the API cannot be reached (network failure or timeout)."""

	pass


class APIResponseError(APIClientError):
	"""Raised when the API responds with an error status code."""

	def __init__(self, message: str, status_code: int | None = None, response_body: str | None = None):
		super().__init__(message)
		self.status_code = status_code
		self.response_body = response_body


class APIRateLimitError(APIResponseError):
	"""Raised when the API keeps answering 429 after every permitted retry."""

	pass
