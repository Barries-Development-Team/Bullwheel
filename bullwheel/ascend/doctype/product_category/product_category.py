# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

# bullwheel/ascend/doctype/ascend_<thing>/ascend_<thing>.py
from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class ProductCategory(AbstractVirtualDocType):
    TABLE_NAME = "Categories"        # Ascend SQL table name
    PRIMARY_KEY_COLUMN = "ID"    # SQL primary key column
    SCHEMA_CONFIG = { ... }       # from Step 2


# Link-field autocomplete hook (only if this DocType is a Link target)
ascend_category_search = ProductCategory.make_search_function(display_fields=["description"])