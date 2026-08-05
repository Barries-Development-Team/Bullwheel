# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

# import frappe

from bullwheel.ascend.virtual_doctype_base import AbstractVirtualDocType


class AscendUser(AbstractVirtualDocType):
    TABLE_NAME = "Users"              # Ascend SQL table name
    ALLOW_WRITE = False               # False by default. If true, the Virtual Doctype Framework can edit the Ascend SQL table. Requires INSERT, UPDATE permissions.
    JOIN_CONFIG: list = None          # Optional config for joining multiple tables. See Step 3b
    SHOW_FIELD_WARNINGS: bool = True  # Display a warning to the console when a lookup on an unmapped field is skipped.
    EXCLUDE_NULL_NAME = True          # 'name' maps to EmployeeId, which is not populated for every Ascend User (e.g.
                                       # non-employee/system accounts). A null EmployeeId crashes Link search's
                                       # relevance sort and can't identify a Frappe document anyway, so those records
                                       # are excluded from every query rather than surfaced with a broken name.
    SCHEMA_CONFIG = {
        'name':                  {'column': 'EmployeeId', 'cache': True},
        'id':                    {'column': 'ID', 'cache': True},
        'first_name':            {'column': 'FirstName'},
        'last_name':             {'column': 'LastName'},
        'initials':              {'column': 'Initials'},
        'title':                 {'column': 'Title'},
        'address':               {'column': 'Address'},
        'address2':              {'column': 'Address2'},
        'city':                  {'column': 'City'},
        'state':                 {'column': 'State'},
        'zip':                   {'column': 'ZIP'},
        'phone':                 {'column': 'Phone'},
        'alt_phone':             {'column': 'AltPhone'},
        'email':                 {'column': 'EMail'},
        'max_discount':          {'column': 'MaxDiscount'},
        'creator_id':            {'column': 'CreatorID', 'cache': True},
        'modified_by':           {'column': 'ModifierID'},
        'date_created':          {'column': 'DateCreated', 'cache': True},
        'modified':              {'column': 'DateModified'},
        'hide':                  {'column': 'Hide'},
        'loc_from_id':           {'column': 'LocFromID'},
        'profile_id':            {'column': 'ProfileID'},
        'reg_no':                {'column': 'RegNo'},
        'row_version':           {'column': 'Row_Version'},
        'country':               {'column': 'Country'},
        'gender':                {'column': 'Gender'},
        'is_service_technician': {'column': 'IsServiceTechnician'},
        'stratus_id':            {'column': 'StratusId'},
        'active':                {'column': 'Active'},
        'security_level_id':     {'column': 'SecurityLevelId'},
        'employee_id':           {'column': 'EmployeeId'}
}