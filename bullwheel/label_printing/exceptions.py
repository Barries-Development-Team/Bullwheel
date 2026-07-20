# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt


class PrinterException(Exception):
	"""Base exception for all Zebra printer errors."""

	pass


class PrinterConnectionError(PrinterException):
	"""Raised when a connection to the printer cannot be established."""

	pass


class PrinterSendError(PrinterException):
	"""Raised when sending data to the printer fails."""

	pass


class PrinterStatusError(PrinterException):
	"""Raised when the printer's host-status response cannot be read or parsed."""

	pass


class LabelResolutionError(Exception):
	"""Raised when an item cannot be resolved to a natively printable document.
	Deliberately not a PrinterException: it signals a data problem, not a
	transport problem."""

	pass
