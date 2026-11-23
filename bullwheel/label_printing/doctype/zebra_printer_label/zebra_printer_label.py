# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

import re

import frappe
from frappe.model.document import Document

# ZPL commands every label template must contain, as (description, pattern). The pattern runs
# against the template with its Jinja comments removed, so a command that only appears inside
# a {# ... #} comment does not count.
REQUIRED_ZPL_COMMANDS = (
	("^XA (start of label)", re.compile(r"\^XA")),
	("^XZ (end of label)", re.compile(r"\^XZ")),
	("^PQ{{ quantity }} (print quantity)", re.compile(r"\^PQ\s*\{\{\s*quantity\s*\}\}")),
)

JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)


def missing_zpl_commands(zpl: str | None) -> list[str]:
	"""Return the description of each required ZPL command absent from the `zpl` template,
	ignoring anything inside Jinja comments. An empty list means the template is complete."""
	template = JINJA_COMMENT.sub("", zpl or "")
	return [description for description, pattern in REQUIRED_ZPL_COMMANDS if not pattern.search(template)]


class ZebraPrinterLabel(Document):
	def validate(self):
		"""Refuse to save a template missing a required ZPL command: without ^XA/^XZ the
		printer receives no complete label, and without ^PQ{{ quantity }} it ignores the
		requested print quantity and prints one copy."""
		missing_commands = missing_zpl_commands(self.zpl)
		if missing_commands:
			frappe.throw(
				"The ZPL template is missing these required commands:<br>" + "<br>".join(missing_commands),
				title="Incomplete Label Template",
			)

	def render(self, doc, printer, quantity: int = 1):
		"""Render this label's stored ZPL template into final ZPL, injecting the source
		document, the target printer (for dpi), and this label as Jinja context so the
		template can size and lay out the label from real values."""

		return frappe.render_template(self.zpl, {"doc": doc, "printer": printer, "label": self, "quantity": quantity})
