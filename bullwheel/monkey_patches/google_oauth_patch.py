# Copyright (c) 2026 Barrie's Ski and Sports
# All Rights Reserved
# Unauthorized copying or distribution of this file is prohibited.

"""Register the offsite_backups Google Drive authorize_access callback with Frappe's
Google OAuth domain dispatch table.

``frappe.integrations.google_oauth._DOMAIN_CALLBACK_METHODS`` is a module-level dict
that maps OAuth domain names to the dotted-path of the method that should be called
when the OAuth flow redirects back. It ships with entries for ``mail``, ``contacts``,
and ``indexing``. The ``offsite_backups`` app provides a ``drive`` integration, but
because that app is separate from Frappe itself its entry is not included by default.

This patch adds the missing entry at startup so the OAuth callback correctly routes to
``offsite_backups``. It is idempotent: if the entry is already present (e.g. in a
future version of Frappe that bundles it) the existing value is left untouched.

Applied once, from ``bullwheel/__init__.py``, via :func:`apply`.
"""

import frappe.integrations.google_oauth as _google_oauth

_DRIVE_CALLBACK = "offsite_backups.offsite_backups.doctype.google_drive.google_drive.authorize_access"
_PATCHED_FLAG = "_bullwheel_google_oauth_drive_patched"


def apply():
	"""Insert the ``drive`` entry into ``_DOMAIN_CALLBACK_METHODS`` if not already present.

	Idempotent: repeated calls (one per worker process is expected) are harmless.
	"""
	if getattr(_google_oauth, _PATCHED_FLAG, False):
		return

	_google_oauth._DOMAIN_CALLBACK_METHODS.setdefault("drive", _DRIVE_CALLBACK)
	setattr(_google_oauth, _PATCHED_FLAG, True)
