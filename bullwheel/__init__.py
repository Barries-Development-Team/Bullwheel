__version__ = "0.0.1"

from bullwheel.overrides.virtual_link_title import apply as _apply_virtual_link_title_patch

# Make "Show Title in Link Fields" work for virtual DocTypes by routing link-title
# lookups through the controller instead of a non-existent database table. See
# bullwheel/overrides/virtual_link_title.py for details.
_apply_virtual_link_title_patch()
