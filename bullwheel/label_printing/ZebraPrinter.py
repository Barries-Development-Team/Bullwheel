# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import re
import socket

import frappe

from bullwheel.label_printing.exceptions import (
	PrinterConnectionError,
	PrinterSendError,
	PrinterStatusError,
)


class ZebraPrinter:
	"""
	Network handler for a Zebra label printer. Opens a raw TCP socket to the
	printer's ZPL listener (default port 9100) and sends ZPL bytes directly —
	there is no driver, spooler, or CUPS involved. Mirrors the connection and
	context-manager style of MSSQLDatabase without any transaction semantics,
	since printing over TCP is fire-and-forget.
	"""

	# ─── Class-Level Constants ────────────────────────────────────────

	DEFAULT_PORT = 9100  # Zebra's raw ZPL listener port
	HOST_STATUS_COMMAND = "~HS"
	READ_BUFFER_SIZE = 1024

	# ─── Initialization ───────────────────────────────────────────────

	def __init__(
		self,
		printer_document,
		timeout: int = None,
	):
		self.printer_name = printer_document.printer_name
		self.ip = printer_document.ip
		self.port = printer_document.port or self.DEFAULT_PORT
		# Fall back to the printer's configured timeout when the caller does not
		# override it, so each device keeps its own reachability budget.
		self.timeout = timeout if timeout is not None else printer_document.timeout
		self.connection = None

		self.logger = frappe.logger("zebra")

	# ─── Connection Lifecycle ─────────────────────────────────────────

	def connect(self) -> None:
		"""Open a TCP socket to the printer's raw ZPL listener, raising a
		PrinterConnectionError if the printer cannot be reached within the timeout."""
		try:
			self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			self.connection.settimeout(self.timeout)
			self.connection.connect((self.ip, self.port))
		except OSError as error:
			self.connection = None
			raise PrinterConnectionError(
				f"Failed to connect to printer '{self.printer_name}' at {self.ip}:{self.port}: {error}"
			) from error

	def close(self) -> None:
		"""Close the active socket connection and reset the connection attribute
		to None, mirroring MSSQLDatabase.close()."""
		if self.connection:
			self.connection.close()
			self.connection = None

	def __enter__(self):
		"""Open the connection when entering a `with` block, returning self
		so the handler is accessible via the `as` clause."""
		self.connect()
		return self

	def __exit__(self, exception_type, exception_value, traceback):
		"""Close the connection when exiting a `with` block. There is no commit or
		rollback because printing over TCP is fire-and-forget."""
		self.close()

	# ─── Sending ──────────────────────────────────────────────────────

	def send(self, zpl: str) -> None:
		"""Encode the given ZPL and write every byte to the printer over the socket,
		connecting first if no connection is open; raises PrinterSendError on failure."""
		if not self.connection:
			self.connect()
		try:
			self.connection.sendall(zpl.encode("utf-8"))
		except OSError as error:
			raise PrinterSendError(
				f"Failed to send data to printer '{self.printer_name}' at {self.ip}:{self.port}: {error}"
			) from error

	# ─── Health Check ─────────────────────────────────────────────────

	def get_host_status(self) -> dict:
		"""Query the printer with the ~HS (Host Status) command and return a dict of
		state flags — paper_out, paused, head_open, and a ready roll-up. Flags are
		None when the response is missing or unparseable, so a reachable printer with
		an unreadable status is reported as ready-unknown rather than failed."""
		self.send(self.HOST_STATUS_COMMAND)
		try:
			raw_response = self._read_host_status_response()
		except OSError as error:
			raise PrinterStatusError(
				f"Failed to read host status from printer '{self.printer_name}': {error}"
			) from error
		return self._parse_host_status(raw_response)

	def _read_host_status_response(self) -> bytes:
		"""Read the printer's reply to a ~HS query, accumulating bytes until three
		status strings (each ETX-terminated) have arrived or the socket times out.
		A timeout returns whatever was received so a silent printer is treated as
		reachable rather than an error."""
		response = b""
		while response.count(b"\x03") < 3:
			try:
				chunk = self.connection.recv(self.READ_BUFFER_SIZE)
			except socket.timeout:
				break
			if not chunk:
				break
			response += chunk
		return response

	def _parse_host_status(self, raw_response: bytes) -> dict:
		"""Parse the comma-delimited status strings returned by ~HS into a flag dict.
		The paper-out and pause flags are the second and third fields of the first
		status string; the head-open flag is the third field of the second status
		string (per the Zebra ZPL Programming Guide). Unknown flags stay None, and
		the `ready` roll-up is set only when at least one flag was parsed."""
		status = {"paper_out": None, "paused": None, "head_open": None, "ready": None}

		text = raw_response.decode("ascii", errors="ignore")
		# Each status string is wrapped in STX (0x02) ... ETX (0x03).
		segments = re.findall("\x02([^\x03]*)\x03", text)

		if segments:
			first_fields = segments[0].split(",")
			if len(first_fields) >= 3:
				status["paper_out"] = first_fields[1] == "1"
				status["paused"] = first_fields[2] == "1"

		if len(segments) >= 2:
			second_fields = segments[1].split(",")
			if len(second_fields) >= 3:
				status["head_open"] = second_fields[2] == "1"

		known_flags = [status["paper_out"], status["paused"], status["head_open"]]
		if any(flag is not None for flag in known_flags):
			status["ready"] = not any(flag is True for flag in known_flags)

		return status

	def test_connection(self):
		"""Open a connection and query host status to verify the printer is reachable,
		returning the status dict on success or the caught exception on failure.
		Always closes the connection before returning."""
		try:
			self.connect()
			return self.get_host_status()
		except (PrinterConnectionError, PrinterSendError, PrinterStatusError) as error:
			return error
		finally:
			self.close()
