# Copyright (c) 2026, Barrie's Ski and Sports and contributors
# For license information, please see license.txt

"""The VPN generator used to check only Ascend's VendorProducts, so a pending New Product could be
given a VPN another New Product of the same vendor already held. Each Pending New Product is now
re-checked and given a fresh VPN when its current one is missing, already in Ascend for its vendor,
or already held by an Exported/Imported New Product or an earlier Pending one of the same vendor.
The earliest record keeps a shared VPN, so only the later duplicates change.

A record whose vendor is not in Ascend, or whose VPN cannot be regenerated, is reported and left
as is so one bad record does not block the migration. If Ascend is unreachable this raises."""

import frappe

from bullwheel.ascend.doctype.vendor.vendor import Vendor
from bullwheel.ascend.doctype.vendor_product.vendor_product import _part_number_match_count, generate_vpn
from bullwheel.bullwheel_core import get_default_ascend_database
from bullwheel.database.SQLServer import MSSQLDatabase


def execute():
	pending_products = frappe.get_all(
		"New Product",
		filters={"status": "Pending"},
		fields=["name", "vendor", "vpn", "vpn_prefix", "brand", "style_name", "size", "color"],
		order_by="creation asc",
	)
	if not pending_products:
		return

	# (vendor, vpn) pairs already spoken for: records past Pending are on an import sheet or in
	# Ascend, so they keep their VPN. Pending records are added as they are confirmed below.
	claimed_vpns = {
		(record.vendor, record.vpn)
		for record in frappe.get_all(
			"New Product",
			filters={"status": ["not in", ["Pending", "Cancelled"]], "vpn": ["is", "set"]},
			fields=["vendor", "vpn"],
		)
	}
	vendor_ids = {}

	with MSSQLDatabase(get_default_ascend_database()) as ascend:
		for product in pending_products:
			if product.vendor not in vendor_ids:
				vendor_record = Vendor.get_values(product.vendor, ["id"])
				vendor_ids[product.vendor] = vendor_record["id"] if vendor_record else None
			vendor_id = vendor_ids[product.vendor]
			if not vendor_id:
				print(f'New Product {product.name}: vendor "{product.vendor}" was not found in Ascend; VPN left unchanged.')
				continue

			needs_new_vpn = (
				not product.vpn
				or (product.vendor, product.vpn) in claimed_vpns
				or _part_number_match_count(ascend, vendor_id, product.vpn)
			)
			if needs_new_vpn:
				try:
					new_vpn = generate_vpn(
						vendor_id=vendor_id,
						vpn_prefix=product.vpn_prefix,
						brand=product.brand,
						model=product.style_name,
						size=product.size,
						color=product.color,
						vendor=product.vendor,
						exclude_new_product=product.name,
					)
				except frappe.ValidationError as error:
					print(f"New Product {product.name}: could not regenerate VPN {product.vpn!r} ({error}); left unchanged.")
					continue

				frappe.db.set_value("New Product", product.name, "vpn", new_vpn)
				print(f"New Product {product.name}: VPN {product.vpn!r} -> {new_vpn!r}.")
				product.vpn = new_vpn

			claimed_vpns.add((product.vendor, product.vpn))
