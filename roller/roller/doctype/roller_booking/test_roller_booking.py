# Copyright (c) 2025, Sowaan and Contributors
# See license.txt

from unittest import TestCase

from roller.api.booking import (
	_booking_payload_from_api_items,
	_booking_total,
	_removed_booking_items,
)


class TestRollerBooking(TestCase):
	def test_removed_booking_items_are_compared_by_booking_item_id(self):
		previous = {
			"items": [
				{"bookingItemId": 7509956, "productId": 1850077, "cost": 10},
				{"bookingItemId": 7509957, "productId": 1850078, "cost": 10},
			]
		}
		latest = {
			"items": [
				{"bookingItemId": 7509957, "productId": 1850078, "cost": 10},
			]
		}

		removed = _removed_booking_items(previous, latest)

		self.assertEqual([item["bookingItemId"] for item in removed], [7509956])

	def test_booking_total_prefers_roller_total(self):
		booking = {
			"total": 10,
			"items": [{"quantity": 1, "cost": 20}],
		}

		self.assertEqual(_booking_total(booking), 10)

	def test_fetch_snapshot_event_id_is_deterministic(self):
		items = [
			{
				"bookingReference": "5228735",
				"bookingUniqueId": "booking-unique-id",
				"bookingStatus": "Paid",
				"bookingTotal": 10,
				"createdDate": "2026-06-25T10:00:00",
				"bookingDate": "2026-06-25",
				"bookingEndDate": "2026-06-25",
				"bookingItemId": 7509956,
				"productId": 1850077,
				"cost": 10,
			}
		]

		first = _booking_payload_from_api_items("5228735", items)
		second = _booking_payload_from_api_items("5228735", items)

		self.assertEqual(first["id"], second["id"])
