# Copyright (c) 2025, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname


class RollerBooking(Document):
	def autoname(self):
		if not self.booking_reference:
			frappe.throw("Booking Reference is required to generate the name.")

		prefix = f"ROL-BOOK-{self.booking_reference}-"
		self.name = make_autoname(prefix + ".#####")
