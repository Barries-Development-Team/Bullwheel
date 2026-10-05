# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

from unittest.mock import MagicMock, patch

import requests
from frappe.tests import UnitTestCase

from bullwheel.integrations.api_client import BaseAPIClient
from bullwheel.integrations.exceptions import APIConnectionError, APIRateLimitError, APIResponseError


class AuthenticatedClient(BaseAPIClient):
	def get_authentication_headers(self) -> dict[str, str]:
		return {"Authorization": "Bearer test"}


def make_response(status_code: int = 200, body=None, headers=None) -> MagicMock:
	response = MagicMock()
	response.status_code = status_code
	response.ok = status_code < 400
	response.headers = headers or {}
	response.content = b"" if body is None else b"{}"
	response.text = "" if body is None else str(body)
	response.json.return_value = body
	return response


class UnitTestAPIClient(UnitTestCase):
	def setUp(self):
		session_patcher = patch("bullwheel.integrations.api_client.get_request_session")
		self.session = session_patcher.start().return_value
		self.addCleanup(session_patcher.stop)
		sleep_patcher = patch("bullwheel.integrations.api_client.time.sleep")
		self.sleep = sleep_patcher.start()
		self.addCleanup(sleep_patcher.stop)
		log_patcher = patch("bullwheel.integrations.api_client.frappe.log_error")
		log_patcher.start()
		self.addCleanup(log_patcher.stop)
		self.client = AuthenticatedClient(base_url="https://api.test/v1/")

	def test_authentication_hook_must_be_implemented(self):
		with self.assertRaises(NotImplementedError):
			BaseAPIClient(base_url="https://api.test").get("/x")

	def test_success_returns_json_and_sends_auth_headers(self):
		self.session.request.return_value = make_response(200, {"ok": True})
		self.assertEqual(self.client.get("/items", params={"page": 1}), {"ok": True})
		arguments, keyword_arguments = self.session.request.call_args
		self.assertEqual(arguments, ("GET", "https://api.test/v1/items"))
		self.assertEqual(keyword_arguments["headers"]["Authorization"], "Bearer test")
		self.assertEqual(keyword_arguments["timeout"], 30)

	def test_no_content_returns_none(self):
		self.session.request.return_value = make_response(204)
		self.assertIsNone(self.client.delete("/items/1"))

	def test_error_status_raises_response_error(self):
		self.session.request.return_value = make_response(404, "missing")
		with self.assertRaises(APIResponseError) as context:
			self.client.get("/items/1")
		self.assertEqual(context.exception.status_code, 404)

	def test_rate_limit_retries_then_succeeds(self):
		self.session.request.side_effect = [
			make_response(429, "slow down", {"Retry-After": "2"}),
			make_response(200, {"ok": True}),
		]
		self.assertEqual(self.client.get("/items"), {"ok": True})
		self.sleep.assert_called_once_with(2.0)

	def test_rate_limit_exhaustion_raises(self):
		self.session.request.return_value = make_response(429, "slow down")
		with self.assertRaises(APIRateLimitError):
			self.client.get("/items")
		self.assertEqual(self.session.request.call_count, 4)

	def test_connection_failure_raises_connection_error(self):
		self.session.request.side_effect = requests.exceptions.ConnectTimeout("timed out")
		with self.assertRaises(APIConnectionError):
			self.client.get("/items")
