import frappe
from frappe.utils import get_system_timezone


def set_default_timezone(doc, method=None):
    """Default new User.time_zone to the system timezone if unset."""
    if not doc.time_zone:
        doc.time_zone = get_system_timezone()


def sync_timezone_default(doc, method=None):
    """Keep the per-user DefaultValue row for time_zone in sync with
    User.time_zone on every save, so frappe.sys_defaults never resolves
    to a stale personal override again."""
    if doc.time_zone:
        frappe.defaults.set_default("time_zone", doc.time_zone, doc.name)
    else:
        frappe.defaults.clear_default("time_zone", parent=doc.name)