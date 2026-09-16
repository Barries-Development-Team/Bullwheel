# DocType Virtual Field Implementation

Virtual Fields are fields that are not stored on the DocType's database datable, and are instead computed when the document is loaded.

## Ascend Virtual Field Pattern Example


```
def _ascend_fields(self):
		"""Fetch and memoize the linked Vendor Product's mirrored description/upc fields for this
		document instance, sourced through VendorProduct's short-TTL cache rather than a live
		query. Returns None when no vpn is set or the linked Vendor Product doesn't resolve in
		Ascend (e.g. mid-creation during the vendor-link/new-product flow)."""
		if not hasattr(self, "_ascend_field_cache"):
			self._ascend_field_cache = (
				VendorProduct.get_bulk_short_cached_values([self.vpn], ["description", "upc"]).get(self.vpn)
				if self.vpn else None
			)
		return self._ascend_field_cache

	@property
	def description(self):
		fields = self._ascend_fields()
		return fields.get("description") if fields else None

	@property
	def upc(self):
		fields = self._ascend_fields()
		return fields.get("upc") if fields else None
```