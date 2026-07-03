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
	Handler for a Zebra label printer. Sends ZPL over a raw TCP socket to one of
	two targets, chosen by the printer's connection method:

	  * Network — a direct socket to the printer's own ZPL listener (default port 9100).
	  * USB     — a socket to the Bullwheel USB Print Service running on the connected
	              computer, which forwards the ZPL on to the local USB printer.

	Either way the transport is a fire-and-forget TCP send, so — like MSSQLDatabase —
	this handler uses a context-manager lifecycle but has no transaction semantics.
	"""

	# ─── Class-Level Constants ────────────────────────────────────────

	DEFAULT_PORT = 9100  # Zebra's raw ZPL listener port
	# The Bullwheel USB Print Service listens here on the connected computer and
	# forwards received ZPL to the local USB printer. Must match the service's port.
	USB_PRINT_SERVICE_PORT = 9100
	HOST_STATUS_COMMAND = "~HS"
	READ_BUFFER_SIZE = 1024

	# ─── Initialization ───────────────────────────────────────────────

	def __init__(
		self,
		printer_document,
		timeout: int = None,
	):
		self.printer_name = printer_document.printer_name
		self.connection_method = printer_document.connection_method
		self.connected_computer_address = printer_document.connected_computer_address
		self.ip = printer_document.ip
		self.port = printer_document.port or self.DEFAULT_PORT
		# Fall back to the printer's configured timeout when the caller does not
		# override it, so each device keeps its own reachability budget.
		self.timeout = timeout if timeout is not None else printer_document.timeout
		self.connection = None

		# Resolve the socket endpoint from the connection method. A USB printer is
		# reached indirectly through the Bullwheel USB Print Service on the connected
		# computer; from this handler's perspective both methods are just a TCP socket.
		if self.connection_method == "USB":
			self.target_host = self.connected_computer_address
			self.target_port = self.USB_PRINT_SERVICE_PORT
		else:
			self.target_host = self.ip
			self.target_port = self.port

		self.logger = frappe.logger("zebra")

	def _describe_target(self) -> str:
		"""Return a human-readable description of the socket endpoint for error
		messages, distinguishing a direct network printer from a USB printer reached
		through the Bullwheel USB Print Service."""
		if self.connection_method == "USB":
			return (
				f"USB print service for printer '{self.printer_name}' "
				f"at {self.target_host}:{self.target_port}"
			)
		return f"printer '{self.printer_name}' at {self.target_host}:{self.target_port}"

	# ─── Connection Lifecycle ─────────────────────────────────────────

	def connect(self) -> None:
		"""Open a TCP socket to the resolved print target — the printer's raw ZPL
		listener (Network) or the Bullwheel USB Print Service on the connected computer
		(USB) — raising PrinterConnectionError if it cannot be reached within the timeout."""
		try:
			self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			self.connection.settimeout(self.timeout)
			self.connection.connect((self.target_host, self.target_port))
		except OSError as error:
			self.connection = None
			raise PrinterConnectionError(
				f"Failed to connect to {self._describe_target()}: {error}"
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
				f"Failed to send data to {self._describe_target()}: {error}"
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
