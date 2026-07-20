__version__ = "1.0.0"

from bullwheel.overrides.virtual_link_title import apply as _apply_virtual_link_title_patch
from bullwheel.overrides.google_oauth_patch import apply as _apply_google_oauth_patch

# Make "Show Title in Link Fields" work for virtual DocTypes by routing link-title
# lookups through the controller instead of a non-existent database table. See
# bullwheel/overrides/virtual_link_title.py for details.
_apply_virtual_link_title_patch()

# Register the offsite_backups Google Drive OAuth callback with Frappe's domain
# dispatch table. See bullwheel/overrides/google_oauth_patch.py for details.
_apply_google_oauth_patch()
