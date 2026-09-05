# Vietnam market support

This repository's share of a cross-repository plan for Vietnamese-language SEO content.
The full plan lives in the sibling `claude-blog` repository under `docs/vietnamese/`;
only the parts that touch `claude-seo` are duplicated here.

## Documents

| Document | Purpose |
|---|---|
| [`00-OVERVIEW.md`](00-OVERVIEW.md) | Problem statement and verified evidence across both repositories |
| [`PHASE-4-DATAFORSEO-VN.md`](PHASE-4-DATAFORSEO-VN.md) | The work in this repository: Vietnam market defaults, cost model, module trimming |

## What changes here

1. **`location_code` 2840 (United States) to 2704 (Vietnam)**, `language_code` `en` to `vi`,
   across skills, agents and scripts. This is the highest-priority item because it does not
   error: the agent returns US search volumes for Vietnamese keywords and the numbers look
   entirely plausible.
2. **`dataforseo_costs.py` cost model.** The table is marked verified as of 2026-07-10 but
   carries pre-increase prices, and the DataForSEO Labs pricing model has changed from a
   flat fee to per task plus per item. A 1000-item Labs call actually costs $0.132 and is
   estimated at $0.05, so the budget gate is bypassed 2.6x without anyone noticing.
3. **`ENABLED_MODULES`** trimmed from all nine MCP modules to the four that content work
   uses. The three dropped modules are the most expensive per call.
4. **`scripts/dfs_vn_probe.py`**, a free-endpoint readiness check for the Vietnamese market.

## Verified market facts

From DataForSEO's own published location files:

```csv
2704,Vietnam,,VN,Country,google,Vietnamese,vi,41271976,1564638
2704,Vietnam,,VN,Country,google,English,en,20477026,570712
```

- Vietnam is `location_code` 2704, `language_code` `vi`
- 41,271,976 keywords and 1,564,638 SERPs in the Vietnamese Labs database
- **Labs covers Vietnam at country level only.** There are no province rows, so `seo-local`
  and `seo-maps` must use the SERP API, which has 3,552 Vietnamese locations (Hanoi
  1028580, Ho Chi Minh City 1028581, Da Nang 1028809)
