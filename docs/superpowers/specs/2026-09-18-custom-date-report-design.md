# Custom Date Report Design

**Goal:** Add a v2.6 `custom` report type for an inclusive, arbitrary continuous date range without changing complete-month archives or existing report types.

## Scope and invariants

- `monthly`, `quarterly`, `yearly`, and month-based `period` retain their current inputs, archive layout, labels, and validation.
- `custom` receives `--start-date YYYY-MM-DD --end-date YYYY-MM-DD`; start must not be after end. Its public and SMB label is `YYYY-MM-DD_to_YYYY-MM-DD`.
- Existing complete-month archives under `ga4-gsc/<domain>/YYYY-MM.json` are immutable and are never used as a substitute for a partial-date source.
- No credential-file format, RAM policy, Bucket setting, SMB setting, or existing report is changed. Real Google, third-party, SMB, and OSS operations occur only when a later report task explicitly authorizes them.

## First-party archives and comparison

The collector will store a custom GA4/GSC response only at:

```text
ga4-gsc/<canonical-domain>/custom/<start>_to_<end>.json
ga4-gsc/<canonical-domain>/custom/<start>_to_<end>.json.ready
```

The JSON must declare the same canonical domain and exact inclusive `[start, end]` date pair, include non-empty GA4 and GSC sections, and have a matching ready-marker SHA-256. It is written with the existing no-overwrite archive discipline.

For an actual authorized custom-report run, the generator first reuses a verified exact current-range archive. It then computes the immediately preceding equal-day range and reuses its verified archive or automatically collects that range from GA4/GSC. A missing, unavailable, or failed prior range produces `comparison_mode: unavailable`; it never blocks an otherwise complete current report and never fabricates, partially joins, or estimates a comparison. A missing or invalid current range remains blocking.

For example, `2026-09-01` through `2026-09-15` compares with `2026-08-17` through `2026-08-31`. Both endpoints are inclusive.

## Report model and customer copy

The custom payload records exact `startDate`, `endDate`, `dayCount`, and the custom archive identities. It renders the exact date range as the report title and does not represent the result as a complete month or offer a misleading month selector.

If comparison data is complete, the report may show the equal-day comparison. If it is unavailable, the comparison panels are omitted and the internal diagnostic plus operator result state why. `summary.md` and the final customer “文字总结” contain only verified current-period facts; they do not mention unavailable comparison data.

The existing customer-delivery rule remains unchanged: the final “文字总结” is copied verbatim from the reviewed `summary.md` section.

## Third-party snapshots

`custom` retains the v2.5 third-party gate. An exact-date snapshot is reusable only when domain, inclusive start/end dates, query scope, and recorded approval all match.

If a provider cannot produce an exact-date snapshot, the tool stops before any paid request and presents these explicit choices:

1. use an identified covered calendar month (or, for a cross-month range, a user-selected month or selected months) as clearly labeled background context;
2. request an exact-date snapshot if the provider supports it; or
3. generate with `--without-third-party`.

Monthly proxy data is recorded as `month_proxy`, never as an exact-date result. Customer-facing report content labels it as month-level market or strategy context and does not attribute it to the custom date range. The tool never chooses a month, makes a paid request, or retries a paid request without explicit user approval.

## Publication and provenance

The publisher accepts `custom` and the date-range label, while retaining its three-file, local-to-SMB-to-OSS SHA-256 gate. It uses:

```text
<archive-root>/<client-slug>/custom/<start>_to_<end>/
oss://<bucket>/reports/<client-slug>/custom/<start>_to_<end>/
https://reports.jzyseo.com/reports/<client-slug>/custom/<start>_to_<end>/
```

`source-archive-usage.json` records the custom archive relative paths and hashes, rather than assuming each source filename is a `YYYY-MM` month. Publication verifies every recorded custom archive and ready marker before copying or uploading.

## Implementation and validation

The release updates shared period validation, custom archive read/write helpers, collector argument handling, generator and summary/rendering logic, provenance validation, artifact validation, publisher path validation, provider-schema examples, and teammate documentation.

Tests cover exact 15-day and 20-day labels, inclusive prior-range calculation, current-range blocking, prior-range-unavailable generation without customer-summary disclosure, exact custom archive identity and no-overwrite behavior, exact-date snapshot reuse, user-approved month-proxy labeling, third-party waiver, report/usage/publisher path validation, and regressions for the four existing report types. No live provider, Google, SMB, or OSS call is part of this test suite.
