# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

import time
from typing import Any

import frappe
import requests
from frappe.utils import get_request_session

from bullwheel.integrations.exceptions import (
	APIConnectionError,
	APIRateLimitError,
	APIResponseError,
)

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 1
MAXIMUM_RATE_LIMIT_WAIT_SECONDS = 60


class BaseAPIClient:
	"""
	Provider-agnostic REST client. Subclass it per provider and implement `get_authentication_headers`.

	Builds on Frappe's `get_request_session` (connection pooling, retry on HTTP 500) and adds a per-request
	timeout, `Retry-After` aware handling of HTTP 429, typed exceptions and error logging.

	Usage:
		with ExampleAPIClient(base_url="https://api.example.com/v1") as client:
			client.get("/products", params={"page": 1})
	"""

	def __init__(
		self,
		base_url: str,
		timeout: int = DEFAULT_TIMEOUT_SECONDS,
		maximum_rate_limit_retries: int = 3,
		log_requests: bool = False,
	):
		self.base_url = base_url.rstrip("/")
		self.timeout = timeout
		self.maximum_rate_limit_retries = maximum_rate_limit_retries
		self.log_requests = log_requests
		self.session = get_request_session()

	def __enter__(self) -> "BaseAPIClient":
		return self

	def __exit__(self, exception_type, exception_value, traceback) -> None:
		self.session.close()

	def get_authentication_headers(self) -> dict[str, str]:
		"""Return the headers that authenticate a request. Implement in the subclass."""
		raise NotImplementedError(f"{type(self).__name__} must implement get_authentication_headers")

	def request(
		self,
		method: str,
		path: str,
		params: dict | None = None,
		json: Any = None,
		headers: dict[str, str] | None = None,
	) -> Any:
		"""
		Send a request and return the parsed JSON body, or None when the response has no content.

		Raises APIConnectionError, APIRateLimitError or APIResponseError on failure.
		"""
		url = f"{self.base_url}/{path.lstrip('/')}"
		request_headers = {"Accept": "application/json", **self.get_authentication_headers(), **(headers or {})}

		attempt = 0
		while True:
			try:
				response = self.session.request(
					method, url, params=params, json=json, headers=request_headers, timeout=self.timeout
				)
			except requests.exceptions.RequestException as error:
				self._log_failure(method, url, str(error))
				raise APIConnectionError(f"{method} {url} failed: {error}") from error

			if response.status_code == 429:
				if attempt >= self.maximum_rate_limit_retries:
					self._log_failure(method, url, response.text, response.status_code)
					raise APIRateLimitError(
						f"{method} {url} was rate limited after {attempt} retries",
						status_code=response.status_code,
						response_body=response.text,
					)
				time.sleep(self._get_rate_limit_wait_seconds(response, attempt))
				attempt += 1
				continue

			break

		if not response.ok:
			self._log_failure(method, url, response.text, response.status_code)
			raise APIResponseError(
				f"{method} {url} returned HTTP {response.status_code}",
				status_code=response.status_code,
				response_body=response.text,
			)

		if self.log_requests:
			self._log_request(method, url, params, json, response)

		if response.status_code == 204 or not response.content:
			return None
		return response.json()

	def get(self, path: str, **kwargs) -> Any:
		return self.request("GET", path, **kwargs)

	def post(self, path: str, **kwargs) -> Any:
		return self.request("POST", path, **kwargs)

	def put(self, path: str, **kwargs) -> Any:
		return self.request("PUT", path, **kwargs)

	def patch(self, path: str, **kwargs) -> Any:
		return self.request("PATCH", path, **kwargs)

	def delete(self, path: str, **kwargs) -> Any:
		return self.request("DELETE", path, **kwargs)

	def _get_rate_limit_wait_seconds(self, response: requests.Response, attempt: int) -> float:
		"""Honour a numeric `Retry-After` header, otherwise back off exponentially."""
		try:
			wait_seconds = float(response.headers.get("Retry-After", ""))
		except ValueError:
			wait_seconds = DEFAULT_RATE_LIMIT_WAIT_SECONDS * 2**attempt
		return min(wait_seconds, MAXIMUM_RATE_LIMIT_WAIT_SECONDS)

	def _log_failure(self, method: str, url: str, detail: str, status_code: int | None = None) -> None:
		status = f" (HTTP {status_code})" if status_code else ""
		frappe.log_error(title=f"API request failed{status}", message=f"{method} {url}\n\n{detail}")

	def _log_request(self, method: str, url: str, params: dict | None, json: Any, response) -> None:
		"""Record the exchange as an Integration Request. Note: `create_request_log` commits."""
		from frappe.integrations.utils import create_request_log

		create_request_log(
			{"method": method, "url": url, "params": params, "body": json},
			integration_type="Remote",
			service_name=type(self).__name__,
			output=response.text,
		)
