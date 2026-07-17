#!/usr/bin/env python3
"""Build data.json for permitting_dashboard.html.

All numbers come from NYC Open Data via the socrata-mcp-server (civic-ai-tools stack),
driven over stdio by mcp_call.py in this directory. Re-run any time to refresh:

    python3 build_dashboard.py

Requires SOCRATA_APP_TOKEN (read from ~/projects/civic-ai-tools/.mcp.json if not in env).
"""
import datetime
import json
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, "mcp_call.py")
SERVER_JS = os.path.expanduser(
    "~/projects/civic-ai-tools/.mcp-servers/socrata-mcp-server/dist/index.js"
)
TODAY = datetime.date.today().isoformat()

# Review completed / filing closed — everything else counts as "in the queue".
TERMINAL_STATUSES = [
    "LOC Issued", "Approved", "Permit Entire", "CO Issued",
    "TA Certificate of Operation Issued", "PA Certificate of Operation Issued",
    "Filing Withdrawn", "Full Demolition Signed-off", "Permit Issued",
    "PAA Approved", "LL 158-2017-Denied",
]

QUERIES_LOG = []

# Derived project-type segment (documented in the dashboard methodology).
# Cut points: 25 units = CA AB 2234 statutory threshold; 100 units / 10 stories =
# "tower" (10 stories aligns with DOB major-building site-safety regime);
# 1-3 family = NYC's own building_type track.
SEGMENT_CASE = (
    'case('
    'job_type = "New Building" AND (proposed_dwelling_units::number > 99 OR proposed_no_of_stories::number >= 10), "new_tower", '
    'job_type = "New Building" AND proposed_dwelling_units::number > 25, "new_large_mf", '
    'job_type = "New Building" AND proposed_dwelling_units::number > 3, "new_small_mf", '
    'job_type = "New Building", "new_house", '
    'job_type = "Alteration" AND building_type IN ("1 Family", "2 Family", "3 Family"), "home_reno", '
    'TRUE, "other_work") AS segment'
)


def _token():
    if os.environ.get("SOCRATA_APP_TOKEN"):
        return os.environ["SOCRATA_APP_TOKEN"]
    try:
        with open(os.path.expanduser("~/projects/civic-ai-tools/.mcp.json")) as f:
            m = re.search(r'"SOCRATA_APP_TOKEN":\s*"([^"]+)"', f.read())
        return m.group(1) if m else ""
    except FileNotFoundError:
        return ""


def soql(dataset_id, query, purpose):
    env = dict(os.environ, SOCRATA_SERVER_JS=SERVER_JS, SOCRATA_APP_TOKEN=_token())
    args = json.dumps({
        "type": "query", "domain": "data.cityofnewyork.us",
        "dataset_id": dataset_id, "query": query,
    })
    out = subprocess.run(
        [sys.executable, DRIVER, "tools/call", "get_data", args],
        capture_output=True, text=True, timeout=180, env=env,
    )
    resp = json.loads(out.stdout)
    if resp.get("error") or resp["result"].get("isError"):
        raise RuntimeError(f"{purpose}: {json.dumps(resp)[:400]}")
    payload = json.loads(resp["result"]["content"][0]["text"])
    QUERIES_LOG.append({"dataset": dataset_id, "purpose": purpose, "soql": query,
                        "rows": payload.get("returned_rows")})
    print(f"  ok [{dataset_id}] {purpose} ({payload.get('returned_rows')} rows)", file=sys.stderr)
    return payload["data"]


def parse_mdY(s):
    try:
        return datetime.datetime.strptime(s, "%m/%d/%Y").date()
    except (ValueError, TypeError):
        return None


def main():
    data = {"built_at": TODAY, "terminal_statuses": TERMINAL_STATUSES}
    q_terminal = ", ".join(f'"{s}"' for s in TERMINAL_STATUSES)

    # ---- Panel 1: the clock (DOB NOW, initial filings, monthly, by review type) ----
    data["dobnow_quarterly"] = soql("w9ak-ipjd", (
        'SELECT date_extract_y(approved_date) AS yy, case(date_extract_m(approved_date) <= 3, "Q1", date_extract_m(approved_date) <= 6, "Q2", date_extract_m(approved_date) <= 9, "Q3", TRUE, "Q4") AS qq, filing_review_type, COUNT(*) AS n, '
        'median(date_diff_d(approved_date, filing_date)) AS med_days, '
        'sum(case(date_diff_d(approved_date, filing_date) <= 42, 1, TRUE, 0)) AS within_6wk, '
        'sum(proposed_dwelling_units::number) AS units '
        'WHERE approved_date >= "2021-01-01" '
        'AND job_filing_number LIKE "%-I1" '
        'GROUP BY yy, qq, filing_review_type ORDER BY yy, qq LIMIT 200'
    ), "quarterly clock, all filings (approvals per quarter, days measured back to filing)")

    data["dobnow_by_jobtype"] = soql("w9ak-ipjd", (
        'SELECT job_type, filing_review_type, COUNT(*) AS n, '
        'median(date_diff_d(approved_date, filing_date)) AS med_days '
        'WHERE approved_date >= "2025-07-01" '
        'AND job_filing_number LIKE "%-I1" '
        'GROUP BY job_type, filing_review_type ORDER BY n DESC LIMIT 30'
    ), "DOB NOW clock by job type (12mo)")

    data["dobnow_by_borough"] = soql("w9ak-ipjd", (
        'SELECT borough, COUNT(*) AS n, '
        'median(date_diff_d(approved_date, filing_date)) AS med_days '
        'WHERE approved_date >= "2025-07-01" '
        'AND job_filing_number LIKE "%-I1" '
        'AND filing_review_type = "Standard Plan Examination" '
        'GROUP BY borough ORDER BY n DESC LIMIT 8'
    ), "DOB NOW standard-review clock by borough (12mo)")

    # ---- Segmented series (project-type toggle) ----
    data["seg_quarterly"] = soql("w9ak-ipjd", (
        f'SELECT {SEGMENT_CASE}, date_extract_y(approved_date) AS yy, case(date_extract_m(approved_date) <= 3, "Q1", date_extract_m(approved_date) <= 6, "Q2", date_extract_m(approved_date) <= 9, "Q3", TRUE, "Q4") AS qq, filing_review_type, '
        'COUNT(*) AS n, median(date_diff_d(approved_date, filing_date)) AS med_days, '
        'sum(case(date_diff_d(approved_date, filing_date) <= 42, 1, TRUE, 0)) AS within_6wk, '
        'sum(proposed_dwelling_units::number) AS units '
        'WHERE approved_date >= "2021-01-01" '
        'AND job_filing_number LIKE "%-I1" '
        'GROUP BY segment, yy, qq, filing_review_type ORDER BY yy, qq LIMIT 2000'
    ), "segmented quarterly clock")

    data["seg_borough"] = soql("w9ak-ipjd", (
        f'SELECT borough, {SEGMENT_CASE}, COUNT(*) AS n, '
        'median(date_diff_d(approved_date, filing_date)) AS med_days '
        'WHERE approved_date >= "2025-07-01" '
        'AND job_filing_number LIKE "%-I1" '
        'AND filing_review_type = "Standard Plan Examination" '
        'GROUP BY borough, segment ORDER BY n DESC LIMIT 60'
    ), "segmented borough clock (standard review, 12mo)")

    data["seg_queue"] = soql("w9ak-ipjd", (
        f'SELECT filing_status, {SEGMENT_CASE}, COUNT(*) AS n, '
        f'median(date_diff_d("{TODAY}", filing_date)) AS med_age_days '
        f'WHERE filing_status NOT IN ({q_terminal}) '
        f'AND job_filing_number LIKE "%-I1" '
        f'GROUP BY filing_status, segment ORDER BY n DESC LIMIT 250'
    ), "segmented open queue by status")

    data["seg_queue_aging"] = soql("w9ak-ipjd", (
        f'SELECT {SEGMENT_CASE}, COUNT(*) AS n, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) <= 30, 1, TRUE, 0)) AS age_0_30, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) > 30 AND date_diff_d("{TODAY}", filing_date) <= 90, 1, TRUE, 0)) AS age_31_90, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) > 90 AND date_diff_d("{TODAY}", filing_date) <= 365, 1, TRUE, 0)) AS age_91_365, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) > 365, 1, TRUE, 0)) AS age_over_1yr '
        f'WHERE filing_status NOT IN ({q_terminal}) AND job_filing_number LIKE "%-I1" '
        f'GROUP BY segment LIMIT 20'
    ), "segmented queue aging buckets")

    data["seg_hero"] = soql("w9ak-ipjd", (
        f'SELECT {SEGMENT_CASE}, filing_review_type, COUNT(*) AS n, '
        'median(date_diff_d(approved_date, filing_date)) AS med_days, '
        'sum(case(date_diff_d(approved_date, filing_date) <= 42, 1, TRUE, 0)) AS within_6wk '
        'WHERE approved_date >= "2025-07-01" AND job_filing_number LIKE "%-I1" '
        'AND approved_date IS NOT NULL '
        'GROUP BY segment, filing_review_type LIMIT 40'
    ), "segmented hero stats (12mo)")

    # ---- Panel 2: the queue (open filings by status, with age) ----
    data["dobnow_queue"] = soql("w9ak-ipjd", (
        f'SELECT filing_status, COUNT(*) AS n, '
        f'median(date_diff_d("{TODAY}", filing_date)) AS med_age_days '
        f'WHERE filing_status NOT IN ({q_terminal}) '
        f'AND job_filing_number LIKE "%-I1" '
        f'GROUP BY filing_status ORDER BY n DESC LIMIT 30'
    ), "DOB NOW open queue by status with median age")

    data["dobnow_queue_aging"] = soql("w9ak-ipjd", (
        f'SELECT COUNT(*) AS n, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) <= 30, 1, TRUE, 0)) AS age_0_30, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) > 30 AND date_diff_d("{TODAY}", filing_date) <= 90, 1, TRUE, 0)) AS age_31_90, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) > 90 AND date_diff_d("{TODAY}", filing_date) <= 365, 1, TRUE, 0)) AS age_91_365, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) > 365, 1, TRUE, 0)) AS age_over_1yr '
        f'WHERE filing_status NOT IN ({q_terminal}) AND job_filing_number LIKE "%-I1"'
    ), "DOB NOW open queue aging buckets")

    # ---- Panel 3: BIS stage chain (sampled, client-side date math on text columns) ----
    stage_rows = []
    for yr in ("2022", "2023", "2024", "2025"):
        stage_rows += soql("ic3t-wcy2", (
            'SELECT pre__filing_date, assigned, approved, fully_permitted, signoff_date '
            f'WHERE signoff_date LIKE "%/{yr}" AND pre__filing_date IS NOT NULL LIMIT 8000'
        ), f"BIS milestone sample, signoffs {yr}")
    stages = {"prefile_to_assigned": [], "assigned_to_approved": [],
              "approved_to_permitted": [], "permitted_to_signoff": [],
              "prefile_to_signoff": []}
    for r in stage_rows:
        d = {k: parse_mdY(r.get(k)) for k in
             ("pre__filing_date", "assigned", "approved", "fully_permitted", "signoff_date")}
        pairs = [("prefile_to_assigned", "pre__filing_date", "assigned"),
                 ("assigned_to_approved", "assigned", "approved"),
                 ("approved_to_permitted", "approved", "fully_permitted"),
                 ("permitted_to_signoff", "fully_permitted", "signoff_date"),
                 ("prefile_to_signoff", "pre__filing_date", "signoff_date")]
        for key, a, b in pairs:
            if d[a] and d[b] and d[b] >= d[a]:
                stages[key].append((d[b] - d[a]).days)
    data["bis_stages"] = {
        k: {"n": len(v), "median_days": statistics.median(v) if v else None,
            "p75_days": statistics.quantiles(v, n=4)[2] if len(v) > 3 else None}
        for k, v in stages.items()
    }
    data["bis_stages"]["sample_note"] = (
        f"Sample of {len(stage_rows)} BIS jobs signed off 2022-2025 (up to 8,000/yr); "
        "milestone dates are text-typed in the source, parsed client-side.")

    # ---- Panel 4: the wall — LPC works, DOT partial, DEP/FDNY dark ----
    data["lpc_12mo"] = soql("dpm2-m9mq", (
        'SELECT COUNT(*) AS n, '
        'median(date_diff_d(issue_date, received_date)) AS med_days '
        'WHERE issue_date >= "2025-07-01" AND received_date IS NOT NULL'
    ), "LPC received->issued clock, permits issued past 12mo")

    data["dot_yearly_volume"] = soql("tqtj-sjs8", (
        'SELECT date_trunc_y(permitissuedate) AS yr, COUNT(*) AS n '
        'WHERE permitissuedate >= "2022-01-01" GROUP BY yr ORDER BY yr'
    ), "DOT street construction permit volume (no application date -> no clock)")

    data["dep_yearly_volume"] = soql("hphy-6g7m", (
        'SELECT date_trunc_y(issuancedate) AS yr, COUNT(*) AS n '
        'WHERE issuancedate >= "2021-01-01" GROUP BY yr ORDER BY yr'
    ), "DEP water/sewer permit volume (no application date -> no clock)")

    data["dep_statuses"] = soql("hphy-6g7m", (
        'SELECT requeststatus, COUNT(*) AS n GROUP BY requeststatus ORDER BY n DESC LIMIT 12'
    ), "DEP status vocabulary (all end-states)")

    # ---- "New housing (all sizes)" segment: NB-filtered variants, tagged client-side ----
    NB_WHERE = 'job_type = "New Building" AND job_filing_number LIKE "%-I1" '
    def tag(rows, segment="new_housing"):
        for r in rows:
            r["segment"] = segment
        return rows

    data["seg_quarterly"] += tag(soql("w9ak-ipjd", (
        'SELECT date_extract_y(approved_date) AS yy, case(date_extract_m(approved_date) <= 3, "Q1", date_extract_m(approved_date) <= 6, "Q2", date_extract_m(approved_date) <= 9, "Q3", TRUE, "Q4") AS qq, filing_review_type, '
        'COUNT(*) AS n, median(date_diff_d(approved_date, filing_date)) AS med_days, '
        'sum(case(date_diff_d(approved_date, filing_date) <= 42, 1, TRUE, 0)) AS within_6wk, '
        'sum(proposed_dwelling_units::number) AS units '
        f'WHERE approved_date >= "2021-01-01" AND {NB_WHERE}'
        'GROUP BY yy, qq, filing_review_type ORDER BY yy, qq LIMIT 100'
    ), "new-housing quarterly clock (all New Building)"))

    data["seg_borough"] += tag(soql("w9ak-ipjd", (
        'SELECT borough, COUNT(*) AS n, '
        'median(date_diff_d(approved_date, filing_date)) AS med_days '
        f'WHERE approved_date >= "2025-07-01" AND {NB_WHERE}'
        'AND filing_review_type = "Standard Plan Examination" '
        'GROUP BY borough ORDER BY n DESC LIMIT 8'
    ), "new-housing borough clock (standard review, 12mo)"))

    data["seg_queue"] += tag(soql("w9ak-ipjd", (
        f'SELECT filing_status, COUNT(*) AS n, '
        f'median(date_diff_d("{TODAY}", filing_date)) AS med_age_days '
        f'WHERE filing_status NOT IN ({q_terminal}) AND {NB_WHERE}'
        f'GROUP BY filing_status ORDER BY n DESC LIMIT 30'
    ), "new-housing open queue by status"))

    data["seg_queue_aging"] += tag(soql("w9ak-ipjd", (
        f'SELECT COUNT(*) AS n, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) <= 30, 1, TRUE, 0)) AS age_0_30, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) > 30 AND date_diff_d("{TODAY}", filing_date) <= 90, 1, TRUE, 0)) AS age_31_90, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) > 90 AND date_diff_d("{TODAY}", filing_date) <= 365, 1, TRUE, 0)) AS age_91_365, '
        f'sum(case(date_diff_d("{TODAY}", filing_date) > 365, 1, TRUE, 0)) AS age_over_1yr '
        f'WHERE filing_status NOT IN ({q_terminal}) AND {NB_WHERE}'
    ), "new-housing queue aging buckets"))

    data["seg_hero"] += tag(soql("w9ak-ipjd", (
        'SELECT filing_review_type, COUNT(*) AS n, '
        'median(date_diff_d(approved_date, filing_date)) AS med_days, '
        'sum(case(date_diff_d(approved_date, filing_date) <= 42, 1, TRUE, 0)) AS within_6wk '
        f'WHERE approved_date >= "2025-07-01" AND {NB_WHERE}'
        'GROUP BY filing_review_type LIMIT 6'
    ), "new-housing hero stats (12mo)"))

    # ---- Three clocks: permission clock (server-side) ----
    data["clocks_permit_seg"] = soql("w9ak-ipjd", (
        f'SELECT {SEGMENT_CASE}, COUNT(*) AS n, '
        'median(date_diff_d(approved_date, filing_date)) AS med_approval, '
        'median(date_diff_d(first_permit_date, filing_date)) AS med_first_permit '
        'WHERE first_permit_date IS NOT NULL AND approved_date IS NOT NULL '
        'AND first_permit_date >= "2023-01-01" AND job_filing_number LIKE "%-I1" '
        'GROUP BY segment LIMIT 20'
    ), "permission clock by segment (permits issued since 2023, measured back to filing)")
    data["clocks_permit_seg"] += tag(soql("w9ak-ipjd", (
        'SELECT COUNT(*) AS n, '
        'median(date_diff_d(approved_date, filing_date)) AS med_approval, '
        'median(date_diff_d(first_permit_date, filing_date)) AS med_first_permit '
        'WHERE first_permit_date IS NOT NULL AND approved_date IS NOT NULL '
        f'AND first_permit_date >= "2023-01-01" AND {NB_WHERE}'
    ), "permission clock, new housing (NB permits issued since 2023, measured back to filing)"))

    data["clocks_permit_all"] = soql("w9ak-ipjd", (
        'SELECT COUNT(*) AS n, '
        'median(date_diff_d(approved_date, filing_date)) AS med_approval, '
        'median(date_diff_d(first_permit_date, filing_date)) AS med_first_permit '
        'WHERE first_permit_date IS NOT NULL AND approved_date IS NOT NULL '
        'AND first_permit_date >= "2023-01-01" AND job_filing_number LIKE "%-I1"'
    ), "permission clock, all projects (permits issued since 2023, measured back to filing)")

    # ---- Three clocks: delivery clock (client-side join filings <-> COs) ----
    cos = []
    for off in (0, 5000):
        cos += soql("pkdm-hqz6", (
            'SELECT job_filing_name, c_of_o_filing_type, c_of_o_issuance_date '
            'WHERE job_type = "New Building" AND c_of_o_status = "CO Issued" '
            'AND c_of_o_filing_type IN ("Initial", "Final") '
            f'ORDER BY job_filing_name LIMIT 5000 OFFSET {off}'
        ), f"NB certificates of occupancy (Initial/Final), page {off // 5000 + 1}")
    filings = []
    for off in (0, 8000, 16000):
        page = soql("w9ak-ipjd", (
            'SELECT job_filing_number, filing_date, proposed_dwelling_units '
            'WHERE job_type = "New Building" AND job_filing_number LIKE "%-I1" '
            'AND filing_date IS NOT NULL '
            f'ORDER BY job_filing_number LIMIT 8000 OFFSET {off}'
        ), f"NB initial filings for CO join, page {off // 8000 + 1}")
        filings += page
        if len(page) < 8000:
            break

    def parse_co_dt(s):  # 'MM/DD/YY  H:MM:SS AM'
        try:
            return datetime.datetime.strptime(s.split()[0], "%m/%d/%y").date()
        except (ValueError, AttributeError, IndexError):
            return None

    first_co = {}
    for c in cos:
        d = parse_co_dt(c.get("c_of_o_issuance_date"))
        k = c.get("job_filing_name")
        if d and k and (k not in first_co or d < first_co[k]):
            first_co[k] = d
    def bucket(u):
        if u is None: return "unknown"
        if u <= 3: return "1-3"
        if u <= 25: return "4-25"
        if u <= 99: return "26-99"
        return "100+"
    joined = []
    for f in filings:
        k = f["job_filing_number"].rsplit("-", 1)[0]
        if k not in first_co:
            continue
        fd = datetime.date.fromisoformat(f["filing_date"][:10])
        dd = (first_co[k] - fd).days
        if dd <= 0:
            continue
        try:
            u = int(float(f.get("proposed_dwelling_units")))
        except (TypeError, ValueError):
            u = None
        joined.append({"days": dd, "co_year": first_co[k].year, "bucket": bucket(u)})
    def med_block(vals):
        return {"n": len(vals), "median_days": statistics.median(vals) if vals else None}
    recent = [j["days"] for j in joined if j["co_year"] >= 2023]
    data["clocks_delivery"] = {
        "overall_recent": med_block(recent),
        "by_bucket_recent": {b: med_block([j["days"] for j in joined
                                           if j["co_year"] >= 2023 and j["bucket"] == b])
                             for b in ("1-3", "4-25", "26-99", "100+")},
        "by_co_year": {y: med_block([j["days"] for j in joined if j["co_year"] == y])
                       for y in sorted({j["co_year"] for j in joined}) if y >= 2022},
        "note": (f"Client-side join of {len(filings)} NB initial filings to {len(first_co)} jobs "
                 "with an issued Initial/Final CO (earliest per job); cohort = COs issued 2023+. "
                 "Only completed buildings are measurable, so the cohort skews toward projects "
                 "that finished — a survivorship limit of published data."),
    }
    print(f"  delivery clock: joined {len(joined)} NB jobs "
          f"(median {data['clocks_delivery']['overall_recent']['median_days']}d, "
          f"n recent {len(recent)})", file=sys.stderr)

    # ---- Hero tiles ----
    data["hero"] = {
        "dobnow_totals": soql("w9ak-ipjd", (
            'SELECT COUNT(*) AS filings_12mo, '
            'median(date_diff_d(approved_date, filing_date)) AS med_days_all, '
            'sum(case(filing_review_type = "Standard Plan Examination", 1, TRUE, 0)) AS standard_review_n '
            'WHERE approved_date >= "2025-07-01" AND job_filing_number LIKE "%-I1" '
            'AND approved_date IS NOT NULL'
        ), "hero: DOB NOW 12mo totals"),
        "standard_12mo": soql("w9ak-ipjd", (
            'SELECT COUNT(*) AS n, '
            'median(date_diff_d(approved_date, filing_date)) AS med_days, '
            'sum(case(date_diff_d(approved_date, filing_date) <= 42, 1, TRUE, 0)) AS within_6wk '
            'WHERE approved_date >= "2025-07-01" AND job_filing_number LIKE "%-I1" '
            'AND approved_date IS NOT NULL '
            'AND filing_review_type = "Standard Plan Examination"'
        ), "hero: standard plan exam 12mo median + within-6wk"),
    }

    data["queries"] = QUERIES_LOG
    out_path = os.path.join(HERE, "data.json")
    with open(out_path, "w") as f:
        json.dump(data, f, indent=1)
    print(f"wrote {out_path} ({os.path.getsize(out_path)} bytes, {len(QUERIES_LOG)} queries)",
          file=sys.stderr)

    # Re-embed into the dashboard HTML so a pipeline run IS the refresh.
    html_path = os.path.join(HERE, "permitting_dashboard.html")
    if os.path.exists(html_path):
        blob = json.dumps(data, indent=1).replace("</", "<\\/")
        html = open(html_path).read()
        new_html, n = re.subn(
            r'(<script id="dash-data" type="application/json">).*?(</script>)',
            lambda m: m.group(1) + blob + m.group(2), html, count=1, flags=re.S)
        if n == 1:
            open(html_path, "w").write(new_html)
            print(f"refreshed {html_path}", file=sys.stderr)
        else:
            print("WARNING: dash-data block not found in HTML; not refreshed", file=sys.stderr)


if __name__ == "__main__":
    main()
