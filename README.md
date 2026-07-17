# NYC Permitting Visibility

A demonstration dashboard measuring NYC construction-permitting timelines entirely from
[NYC Open Data](https://opendata.cityofnewyork.us/), and documenting where the public data
needed for citywide visibility does not exist.

**[View the dashboard](https://htownley.github.io/nyc-permitting-visibility/)**

## What it shows

- **DOB data example** — review queues, filing-to-occupancy spans, and quarterly time-to-approval
  for Department of Buildings filings, by project type (new houses through towers). Buildable
  because DOB publishes filing and decision dates.
- **Unified permitting data schema** — the minimum two outputs every permitting agency would
  need to publish for the same visibility citywide: an append-only status **events feed** and a
  **crosswalk** from each agency's native statuses to a canonical event vocabulary. Checked
  against what six permit datasets publish today.

## Method

- All figures come from logged public Socrata queries (open the Methodology drawer at the bottom
  of the page for every query).
- Data access via the open-source [civic-ai-tools](https://github.com/npstorey/civic-ai-tools)
  MCP server.
- Time series are cohorted by decision date; quarterly grain; the current partial quarter is
  excluded.
- Rebuild the embedded data snapshot with `python3 dashboard/build_dashboard.py` (requires the
  civic-ai-tools socrata server and a free Socrata app token).

Public data and public documents only. Prepared as a demonstration for charter-revision
discussion.
