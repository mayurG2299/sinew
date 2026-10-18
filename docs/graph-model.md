# Graph data model (Northwind graph)

Generated from the live graph by reading every node label, relationship pattern and property (counts below are from a running instance, so they include access records, findings and agent runs written by use; the seeded snapshot has 6,642 nodes and 13,193 relationships). One graph per company (`northwind`, `larkspur`); every label is indexed on `id`, with range indexes on `Order.placed_at`, `Scan.at`, `Ticket.at`, `Shipment.last_hub`, `Shipment.status`, `Promise.due_at`, `Campaign.starts`, and full-text indexes on `Ticket.summary_clean` and `Passage.text_clean` (see `sinew/schema.py`).

Customers carry no names, emails or phones: personal data stays in the store and is fetched live for roles allowed to see it (`PersonalRef` is only a pointer). `Promise` nodes are the agreed refund or delivery dates.

## Node labels

| Label | Count | Properties |
|---|---|---|
| `Access` | 354 | `at`, `id`, `purpose`, `tool` |
| `Area` | 5 | `id` |
| `Assumption` | 5 | `broken_at`, `checked_at`, `id`, `metric`, `op`, `scope_courier`, `scope_hub`, `statement`, `status`, `threshold`, `window_days` |
| `Batch` | 58 | `id`, `made_at`, `recorded_at`, `source`, `source_updated_at` |
| `Campaign` | 2 | `category`, `ends`, `id`, `name`, `recorded_at`, `source`, `source_updated_at`, `starts`, `status` |
| `Category` | 5 | `id` |
| `CostLine` | 5 | `amount`, `currency`, `id`, `kind`, `per`, `period_end`, `period_start`, `recorded_at`, `source`, `source_updated_at` |
| `Coupon` | 2 | `id` |
| `Courier` | 3 | `id`, `name`, `recorded_at`, `source`, `source_updated_at` |
| `Customer` | 200 | `id`, `profiles`, `region`, `since`, `tier` |
| `Decision` | 5 | `chose_kind`, `id`, `made_at`, `recorded_at`, `source`, `source_updated_at`, `status`, `title` |
| `Doc` | 10 | `id`, `kind`, `recorded_at`, `source`, `source_updated_at`, `title`, `written_at` |
| `Evidence` | 5 | `holds`, `id`, `metric`, `sample`, `value`, `window_end`, `window_start` |
| `Hub` | 8 | `capacity`, `id`, `recorded_at`, `source`, `source_updated_at` |
| `Identifier` | 456 | `id`, `type` |
| `IssueType` | 5 | `id` |
| `LineItem` | 748 | `id`, `price`, `qty` |
| `Meta` | 2 | `id`, `now`, `version` |
| `Order` | 600 | `currency`, `id`, `placed_at`, `recorded_at`, `source`, `source_updated_at`, `status`, `total` |
| `Passage` | 16 | `heading`, `id`, `order`, `recorded_at`, `source`, `source_updated_at`, `text_clean` |
| `Payment` | 600 | `amount`, `at`, `id`, `method`, `recorded_at`, `source`, `source_updated_at` |
| `PersonalRef` | 813 | `id`, `source` |
| `Product` | 40 | `category`, `id`, `recorded_at`, `source`, `source_updated_at`, `title` |
| `Profile` | 354 | `channel`, `id`, `recorded_at`, `region`, `since`, `source`, `source_updated_at`, `tier` |
| `Promise` | 72 | `amount`, `broken_at`, `confirmed_by`, `due_at`, `id`, `kind`, `made_at`, `recorded_at`, `settled_at`, `source`, `source_updated_at`, `status` |
| `Purpose` | 1 | `id` |
| `Queue` | 4 | `id` |
| `Refund` | 60 | `amount`, `at`, `id`, `recorded_at`, `source`, `source_updated_at`, `status` |
| `Region` | 3 | `id` |
| `Return` | 60 | `at`, `id`, `reason`, `recorded_at`, `source`, `source_updated_at`, `status` |
| `Role` | 9 | `id` |
| `Scan` | 1,712 | `at`, `id`, `late_hours`, `recorded_at`, `source`, `source_updated_at`, `status` |
| `Shipment` | 600 | `id`, `last_hub`, `last_scan_at`, `late_hours`, `promised_at`, `recorded_at`, `source`, `source_updated_at`, `status` |
| `Source` | 13 | `id`, `last_event_at`, `last_received_at` |
| `Supplier` | 4 | `id`, `recorded_at`, `source`, `source_updated_at` |
| `Team` | 7 | `id`, `name`, `recorded_at`, `source`, `source_updated_at` |
| `Ticket` | 133 | `at`, `channel`, `id`, `issue_type`, `recorded_at`, `source`, `source_updated_at`, `status`, `summary_clean` |
| `User` | 13 | `id`, `recorded_at`, `refund_limit`, `role`, `source`, `source_updated_at` |
| `Warehouse` | 3 | `id`, `recorded_at`, `source`, `source_updated_at` |

## Relationships

| From | Relationship | To | Count |
|---|---|---|---|
| `Access` | `BY` | `User` | 354 |
| `Access` | `OF` | `Customer` | 354 |
| `Assumption` | `ABOUT` | `Courier` | 2 |
| `Assumption` | `ABOUT` | `Hub` | 5 |
| `Batch` | `MADE_BY` | `Supplier` | 58 |
| `Batch` | `OF` | `Product` | 58 |
| `Campaign` | `FOR` | `Category` | 2 |
| `Campaign` | `OWNED_BY` | `User` | 2 |
| `Campaign` | `TARGETS` | `Region` | 2 |
| `CostLine` | `FOR` | `Campaign` | 2 |
| `CostLine` | `FOR` | `Courier` | 3 |
| `CostLine` | `IN_AREA` | `Area` | 5 |
| `Coupon` | `OF` | `Campaign` | 2 |
| `Customer` | `IN` | `Region` | 200 |
| `Decision` | `AFFECTS` | `Hub` | 9 |
| `Decision` | `BREAKS` | `Assumption` | 4 |
| `Decision` | `BUILDS_ON` | `Decision` | 2 |
| `Decision` | `CHOSE` | `Campaign` | 2 |
| `Decision` | `CHOSE` | `Courier` | 1 |
| `Decision` | `CHOSE` | `Hub` | 2 |
| `Decision` | `FOR` | `Region` | 5 |
| `Decision` | `OWNED_BY` | `User` | 5 |
| `Decision` | `RECORDED_IN` | `Doc` | 2 |
| `Decision` | `RESTS_ON` | `Assumption` | 5 |
| `Doc` | `IN_AREA` | `Area` | 8 |
| `Evidence` | `CONTRADICTS` | `Assumption` | 5 |
| `Evidence` | `TESTS` | `Assumption` | 5 |
| `Hub` | `IN` | `Region` | 8 |
| `Hub` | `ROUTES_TO` | `Hub` | 14 |
| `Hub` | `RUN_BY` | `Courier` | 8 |
| `LineItem` | `FROM` | `Batch` | 748 |
| `LineItem` | `OF` | `Product` | 748 |
| `Order` | `FROM` | `Warehouse` | 600 |
| `Order` | `HAS` | `LineItem` | 748 |
| `Order` | `PAID_BY` | `Payment` | 600 |
| `Order` | `SHIPPED_AS` | `Shipment` | 600 |
| `Order` | `STORED_AT` | `PersonalRef` | 600 |
| `Order` | `USED` | `Coupon` | 100 |
| `Passage` | `MENTIONS` | `Campaign` | 6 |
| `Passage` | `MENTIONS` | `Courier` | 8 |
| `Passage` | `MENTIONS` | `Decision` | 15 |
| `Passage` | `MENTIONS` | `Hub` | 8 |
| `Passage` | `PART_OF` | `Doc` | 16 |
| `Product` | `IN` | `Category` | 40 |
| `Profile` | `CONSENTED` | `Purpose` | 7 |
| `Profile` | `HAS` | `Identifier` | 610 |
| `Profile` | `IN` | `Region` | 354 |
| `Profile` | `OF` | `Customer` | 354 |
| `Profile` | `PLACED` | `Order` | 600 |
| `Profile` | `STORED_AT` | `PersonalRef` | 200 |
| `Promise` | `CONCERNS` | `Order` | 72 |
| `Promise` | `KEPT_BY` | `Refund` | 25 |
| `Promise` | `KEPT_BY` | `Scan` | 26 |
| `Promise` | `MADE_BY` | `User` | 72 |
| `Promise` | `MADE_IN` | `Ticket` | 72 |
| `Refund` | `APPROVED_BY` | `User` | 60 |
| `Refund` | `FOR` | `Order` | 60 |
| `Return` | `OF` | `LineItem` | 60 |
| `Role` | `CAN_READ` | `Area` | 30 |
| `Scan` | `AT` | `Hub` | 1,712 |
| `Scan` | `FOR` | `Shipment` | 1,712 |
| `Shipment` | `VIA` | `Courier` | 600 |
| `Team` | `COVERS` | `Region` | 13 |
| `Team` | `OWNS` | `Category` | 2 |
| `Team` | `WORKS` | `Queue` | 4 |
| `Ticket` | `ABOUT` | `Order` | 133 |
| `Ticket` | `FROM` | `Profile` | 133 |
| `Ticket` | `HANDLED_BY` | `User` | 133 |
| `Ticket` | `IN` | `Queue` | 133 |
| `Ticket` | `IS` | `IssueType` | 133 |
| `Ticket` | `TOUCHES` | `Batch` | 161 |
| `Ticket` | `TOUCHES` | `Campaign` | 26 |
| `Ticket` | `TOUCHES` | `Courier` | 133 |
| `Ticket` | `TOUCHES` | `Hub` | 246 |
| `User` | `HAS_ROLE` | `Role` | 13 |
| `User` | `MEMBER_OF` | `Team` | 13 |
| `User` | `REPORTS_TO` | `User` | 12 |
| `User` | `STORED_AT` | `PersonalRef` | 13 |
| `Warehouse` | `IN` | `Region` | 3 |
