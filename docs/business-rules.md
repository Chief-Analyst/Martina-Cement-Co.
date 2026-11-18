# Business rules

Every threshold lives in `martina/config.py` with a default and an environment
variable, so a planner can argue with a number by changing one line in `.env`.

## Order book

| Rule | Default | Variable | Where it shows |
| --- | --- | --- | --- |
| Critical order cover | under 1.25 days | `MC_COVER_CRITICAL_DAYS` | Analytics, Action List |
| Watch order cover | under 3.5 days | `MC_COVER_WATCH_DAYS` | Analytics, Action List |
| Poor lifting | under 45% of ordered | `MC_BEHAVIOUR_POOR` | Analytics, Action List |
| Fair lifting | under 75% of ordered | `MC_BEHAVIOUR_FAIR` | Analytics, Action List |
| Partial release alert | 5 days old | `MC_PARTIAL_ALERT_DAYS` | Operations, Partial Releases |
| FIFO wait | 2 days | `MC_FIFO_WAIT_DAYS` | Operations, FIFO Watch |
| Planning horizons | 1, 2, 3, 5, 7 days | code | Operations, Release Planning |
| Ageing buckets | 0-3, 4-7, 8-14, 15-30, 31-60, 60+ days | code | Analytics, Order Ageing |

**Order cover** is a customer's open tonnage (contracts and releases) divided by
its daily target: how many days of work it has booked. Project accounts are
planned by contract and carry no daily target, so they are listed separately.

**Release planning** applies to Delivered orders only. Collect customers send
their own trucks, so a run rate does not apply to them. For a horizon of H
days: to release = min(target x H minus what is already in the queue, what is
still on contract). Whatever no contract covers is shown as "still short".

**FIFO Watch** flags a customer's oldest open release once it has waited the
set number of days. It is HIGH when a newer release for the same customer has
already been lifted, which means the older one was skipped.

## Logistics

| Rule | Default | Variable |
| --- | --- | --- |
| Customer receiving window (fallback) | 07:00 to 18:00 | `MC_SITE_OPEN_HOUR`, `MC_SITE_CLOSE_HOUR` |
| Watch: line up alternatives | 5 h on site | `MC_SITE_WATCH_HOURS` |
| Reroute trigger | 8 h on site | `MC_SITE_REROUTE_HOURS` |
| Escalation | 16 h on site | `MC_SITE_ESCALATE_HOURS` |
| Idle alert | 4 h idle (dispatch hours only) | `MC_IDLE_ALERT_HOURS` |
| Tracking lost alert | 30 min without a position | `MC_GPS_LOST_MINUTES` |
| Shift changes | 07:00 and 19:00 | code |
| Reroute search radius | 15, 30, 60 km or the whole state | code |

**Time on site** counts only inside each customer's own receiving hours, so a
truck that arrives at 17:30 at a site closing at 18:00 has used 30 minutes,
not the whole night. Trucks drive between 05:00 and 22:00.

**Readiness** combines six checks for each customer: credit hold, funds against
one load, free offloading bays, receiving hours, the area sales rep's call for
the day, and the learned risk that a truck sent now stays past the reroute
trigger. Hold blocks new loads; Caution means call ahead.

## Alerts

| Trigger | Who hears about it |
| --- | --- |
| Truck past the reroute trigger | Dispatch Desk, the region's sales rep, the loading point's supervisor |
| Escalation | Customer Service, the region's sales rep, Dispatch Desk |
| Tracking lost 30 min | Fleet Compliance |
| Idle 4 h | Dispatch Desk, the point's supervisor |
| Load dispatched to a customer on credit hold | Credit Control, Dispatch Desk |

Recipients come from the `recipients` table. With SMTP settings the alerts are
emailed; without them they stay in the outbox on the Control Tower and in
`data/outbox.jsonl`. Each trip raises each alert once.
