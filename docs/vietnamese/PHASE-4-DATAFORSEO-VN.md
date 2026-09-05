# Phase 4 - DataForSEO: Vietnam defaults and the missing wrapper

**Priority:** P1 · **Repos:** `claude-blog` **and** `claude-seo` · **Estimate:** 1 day
**Depends on:** Phase 0

## Goal

Keyword and SERP data comes back for the Vietnamese market instead of the United States,
and `blog-cannibalization --api` actually runs.

## Two defects

### 4.A - Every default is the United States

`location_code=2840` (US) and `language_code=en` are the documented defaults in 29 places
across both repositories:

| File | Lines |
|---|---|
| `claude-seo/agents/seo-dataforseo.md` | 13 |
| `claude-seo/skills/seo-dataforseo/SKILL.md` | 108, 139, 163, 235 |
| `claude-seo/extensions/dataforseo/skills/seo-dataforseo/SKILL.md` | 108, 139, 163, 235 |
| `claude-seo/extensions/dataforseo/agents/seo-dataforseo.md` | 11 |
| `claude-seo/skills/seo-cluster/references/serp-overlap-methodology.md` | 100 |
| `claude-seo/skills/seo-ecommerce/references/marketplace-endpoints.md` | 18, 66 |
| `claude-seo/skills/seo-google/references/keyword-planner-api.md` | 65 |
| `claude-seo/scripts/keyword_planner.py` | 113, 190, 258 |
| `claude-seo/scripts/dataforseo_merchant.py` | 9, 10, 11, 466 |
| `claude-blog/skills/blog-cannibalization/SKILL.md` | 100, 112 |
| `claude-blog/skills/blog-google/scripts/keyword_planner.py` | 115, 192, 260 |

This is the worst kind of defect: it **does not error**. The agent returns US search volumes
for Vietnamese keywords, and the numbers look entirely plausible until someone checks them
against reality.

### 4.B - `claude-blog` calls a wrapper that does not exist

`skills/blog-cannibalization/SKILL.md:81-86`:

> Requires the `--api` flag and a dedicated local CLI wrapper that reads `DATAFORSEO_LOGIN`
> and `DATAFORSEO_PASSWORD` from the environment and emits JSON. […] If no wrapper exists in
> the project, report `SKIPPED: DataForSEO wrapper unavailable` and run local mode.

```bash
grep -rn "DATAFORSEO" --include=*.py claude-blog/
# -> no matches
```

The `--api` path has never executed. And the two repositories disagree on the variable names:
`claude-seo` uses `DATAFORSEO_USERNAME`, `claude-blog` documents `DATAFORSEO_LOGIN`.

## Vietnam market facts (verified)

From DataForSEO's own published location files:

```csv
# locations_and_languages_dataforseo_labs_*.csv
2704,Vietnam,,VN,Country,google,Vietnamese,vi,41271976,1564638
2704,Vietnam,,VN,Country,google,English,en,20477026,570712
```

- `location_code` **2704**, `language_code` **"vi"**
- 41,271,976 keywords and 1,564,638 SERPs in the Vietnamese Labs database
- **Labs supports Vietnam at `location_type=Country` only.** There are no province rows.
- SERP API has 3,552 Vietnamese locations: Hanoi `1028580`, Ho Chi Minh City `1028581`,
  Da Nang `1028809`

> **Consequence.** `seo-local` and `seo-maps` must use the SERP API for city-level work.
> Passing `location_code=1028581` to a Labs endpoint errors or returns empty.

## Implementation

### 4.1 - Flip the defaults

```bash
cd /home/bachx/workspace/Hien/ai

grep -rl "location_code=2840" claude-seo/skills claude-seo/agents \
    claude-seo/extensions/dataforseo | while read -r f; do
  sed -i 's/location_code=2840 (US), language_code=en/location_code=2704 (Vietnam), language_code=vi/g;
          s/location_code=2840 (US)/location_code=2704 (Vietnam)/g;
          s/location_code=2840/location_code=2704/g' "$f"
done

sed -i 's/"location_code": 2840/"location_code": 2704/g;
        s/"language_code": "en"/"language_code": "vi"/g' \
    claude-blog/skills/blog-cannibalization/SKILL.md

sed -i 's/default="2840"/default="2704"/;
        s/location_id: str = "2840"/location_id: str = "2704"/;
        s/(2840 = United States)/(2704 = Vietnam)/' \
    claude-seo/scripts/keyword_planner.py \
    claude-blog/skills/blog-google/scripts/keyword_planner.py

sed -i 's/default=2840, help="Location code (default: 2840 = US)"/default=2704, help="Location code (default: 2704 = Vietnam)"/' \
    claude-seo/scripts/dataforseo_merchant.py
```

Verify nothing was missed and nothing unintended was hit:

```bash
grep -rn "2840" claude-seo claude-blog --include=*.md --include=*.py --include=*.json | grep -v brain/
```

`claude-seo/skills/seo-google/references/keyword-planner-api.md:65` lists `2840` and `2826`
as **examples of location IDs**. That line is documentation of the parameter, not a default -
leave it, or add `2704 = Vietnam` alongside. Read each remaining hit before editing it.

### 4.2 - Make the default explicit in `CLAUDE.md`

`sed` fixes the files that exist today. A written rule fixes the ones written tomorrow. Add
to both `claude-blog/CLAUDE.md` and `claude-seo/CLAUDE.md`:

```markdown
## Default market

All DataForSEO and Keyword Planner calls default to `location_code=2704` (Vietnam) and
`language_code="vi"`. Change only when the user names a different country.

- Province/city level: use the SERP API, not Labs. Hanoi 1028580, Ho Chi Minh City
  1028581, Da Nang 1028809. DataForSEO Labs covers Vietnam at country level only.
- `search_volume` bills **per task, not per keyword** (up to ~1000 keywords per task).
  Always batch into one call. Calling it once per keyword costs 1000x more for the
  same data.
- Prefer the standard queue over live mode unless the user says it is urgent:
  SERP $0.0006 vs $0.002, Keywords Data $0.06 vs $0.09.
- Never re-request a keyword already fetched in the current session.
```

The batching rule is the one that matters most in practice. An agent left to itself will
loop over a keyword list one call at a time.

### 4.3 - Write the missing wrapper

Create `claude-blog/scripts/dataforseo_labs.py`. Copy the structure from
`claude-seo/scripts/dataforseo_merchant.py` (508 lines) - it already has Basic auth, the
task/poll pattern for the standard queue, and error handling. Do not invent a new shape.

Required behavior:

```python
#!/usr/bin/env python3
"""DataForSEO Labs wrapper for blog-cannibalization.

Endpoints:
    page_intersection  keywords where two or more URLs both rank
    ranked_keywords    all keywords one URL ranks for

Environment: DATAFORSEO_USERNAME (or DATAFORSEO_LOGIN), DATAFORSEO_PASSWORD
Output: JSON on stdout. Credentials are never printed, logged, or echoed.

Usage:
    python3 dataforseo_labs.py ranked-keywords <url> [--location 2704] [--language vi]
    python3 dataforseo_labs.py page-intersection <url1> <url2> [...] [--location 2704]
"""
```

Points that are not optional:

1. **Accept both credential variable names.** This is what unblocks the two repositories
   using one export:

   ```python
   username = os.environ.get("DATAFORSEO_USERNAME") or os.environ.get("DATAFORSEO_LOGIN", "")
   password = os.environ.get("DATAFORSEO_PASSWORD", "")
   ```

2. **Vietnam defaults:** `--location 2704`, `--language vi`.

3. **Never print credentials.** Not in error messages, not in debug output, not in the
   `--verbose` path. The SKILL.md is explicit about this: *"never expose Basic auth headers,
   login, password, or encoded credentials in prompts or reports."* Build the header inside
   the request function and do not return it.

4. **Missing credentials is a structured exit, not a traceback:**

   ```json
   {"error": "missing_credentials",
    "message": "Set DATAFORSEO_USERNAME (or DATAFORSEO_LOGIN) and DATAFORSEO_PASSWORD."}
   ```

   Exit 1. `dataforseo_merchant.py:_get_credentials()` does exactly this - copy it.

5. **`requests` is optional here.** `claude-blog/scripts/` is stdlib-only for the analysis
   path, but this script is a network client and `requests` is already in
   `requirements.txt`. Guard the import and emit the same structured error the other
   scripts do rather than crashing on `ImportError`.

6. **Cost check before calling.** `claude-seo/scripts/dataforseo_costs.py` already
   implements budget gating. If it is reachable, call it; if not, print the estimated cost
   to stderr and proceed. Do not silently spend.

Then update `blog-cannibalization/SKILL.md` to name the wrapper explicitly
(`claude-blog/scripts/dataforseo_labs.py`) instead of describing a hypothetical one.

### 4.4 - Correct the cost table

`claude-seo/scripts/dataforseo_costs.py:46` claims `"verified as of 2026-07-10"` but carries
pre-increase prices, and the Labs pricing **model** has changed from flat to per-item:

| Endpoint | Table says | Actual | Effect |
|---|---|---|---|
| `dataforseo_labs_*` | $0.05 flat | **$0.012/task + $0.00012/item** | 200 items = $0.036 (over-estimated); 1000 items = $0.132 (**under-estimated 2.6x**, so the budget gate is bypassed without anyone noticing) |
| `kw_data_google_ads_search_volume` | $0.05 | $0.06 standard / $0.09 live | minor |
| `on_page_instant_pages` | $0.01 | ~$0.012 | minor |
| `backlinks_*` | $0.02 | ~$0.024 | minor |
| `serp_organic_live_advanced` | $0.002 | $0.002 | correct - SERP was not in the increase |

Prices rose ~20% on 2026-07-01 for Labs, Keywords Data, Backlinks, Domain Analytics,
On-Page and Content Analysis; +50% for Merchant Amazon.

The structural fix is to support a per-item model rather than only patching numbers:

```python
COST_MODEL = {
    "dataforseo_labs_google_keyword_ideas": {"per_task": 0.012, "per_item": 0.00012},
    "kw_data_google_ads_search_volume":     {"per_task": 0.06,  "per_item": 0.0},
    "serp_organic_live_advanced":           {"per_task": 0.002, "per_item": 0.0},
    # ...
}

def estimate(endpoint: str, item_count: int = 1) -> float:
    model = COST_MODEL.get(endpoint)
    if model is None:
        return DEFAULT_COST
    return model["per_task"] + model["per_item"] * item_count
```

Keep `COST_TABLE` as a fallback for endpoints not yet migrated, and update the
`verified as of` date to the day you check it.

### 4.5 - Trim `ENABLED_MODULES`

`extensions/dataforseo/install.sh:134` enables all nine MCP modules. Three of them -
`AI_OPTIMIZATION`, `BUSINESS_DATA`, `MERCHANT` - are the most expensive ($0.05-0.06 per
call) and are not used by content work. Every enabled module also loads its tool definitions
into context.

```json
"ENABLED_MODULES": "SERP,KEYWORDS_DATA,DATAFORSEO_LABS,ONPAGE"
```

Change the installer default and note in `DATAFORSEO-SETUP.md` how to re-enable
`BACKLINKS` when a backlink audit is actually needed.

### 4.6 - The account probe

`tools/dfs_vn_probe.py` already exists in this workspace and is verified. It calls only
free endpoints (`appendix/user_data`, `*/locations`, `*/languages`), so it costs $0.00 and
can be run repeatedly. Move it to `claude-seo/scripts/dfs_vn_probe.py` so it ships with the
tooling rather than living beside it, and reference it from `DATAFORSEO-SETUP.md`.

## Pitfalls

1. **Do not `sed` blindly across the whole tree.** `2840` appears as an ordinary number in
   places that have nothing to do with location codes. Restrict to the file list above and
   read each remaining `grep` hit before editing it.
2. **`brain/` is vendored.** `claude-blog/brain/` is a self-contained vendored Obsidian
   vault, not plugin payload. Exclude it from every `grep` and `sed`.
3. **Both repositories have a `keyword_planner.py`.** `claude-seo/scripts/` and
   `claude-blog/skills/blog-google/scripts/` - near-identical, both need the change.
4. **`extensions/dataforseo/skills/` duplicates `skills/`.** The installer copies from the
   extension into the skills directory. Fix both, or the next `install.sh` run silently
   reverts your change.
5. **Never put the DataForSEO password in a tracked file.** `~/.claude/settings.json` holds
   it in plain text; `chmod 600` it. `blog-image/scripts/setup_image_mcp.py` already refuses
   to write a literal key into a tracked file - follow that pattern for anything new.
6. **Do not make live API calls in tests.** Mock at the HTTP boundary. A test suite that
   spends money is a test suite people stop running.
7. **Vietnamese keywords must be sent NFC-normalized.** A keyword in NFD may not match the
   provider's index. Route through `vi_text.normalize()` from Phase 1.

## Acceptance criteria

- [ ] `grep -rn "2840" claude-seo claude-blog --include=*.md --include=*.py | grep -v brain/`
      returns only the documentation-of-parameter lines, each reviewed and deliberately kept
- [ ] `claude-blog/scripts/dataforseo_labs.py` exists and runs
- [ ] It accepts both `DATAFORSEO_USERNAME` and `DATAFORSEO_LOGIN`
- [ ] Missing credentials → structured JSON error, exit 1, no traceback
- [ ] No code path can print a credential - verified by reading, not assumed
- [ ] `blog-cannibalization/SKILL.md` names the real wrapper path
- [ ] "Default market" block present in both `CLAUDE.md` files
- [ ] `dataforseo_costs.py` supports a per-item cost model; Labs estimate for 1000 items
      returns 0.132, not 0.05
- [ ] `ENABLED_MODULES` default trimmed to four
- [ ] `tests/test_dataforseo_labs.py` covers: credential fallback, Vietnam defaults,
      structured error, **no live network calls**
- [ ] Full suite still green

## Verification

```bash
# from the ai/ workspace root (both repos as subdirectories)
env -u DATAFORSEO_USERNAME -u DATAFORSEO_LOGIN -u DATAFORSEO_PASSWORD \
    .venv/bin/python claude-blog/scripts/dataforseo_labs.py ranked-keywords https://example.vn
# -> {"error": "missing_credentials", ...}; exit 1

grep -rn "DATAFORSEO_LOGIN\|DATAFORSEO_USERNAME" claude-blog/scripts/ claude-blog/skills/
.venv/bin/python -m pytest claude-blog/tests/test_dataforseo_labs.py -v

.venv/bin/python -c "
import sys; sys.path.insert(0,'claude-seo/scripts'); import dataforseo_costs as c
print(c.estimate('dataforseo_labs_google_keyword_ideas', 1000))   # expect 0.132
"
```

With real credentials available:

```bash
export DATAFORSEO_USERNAME='...' DATAFORSEO_PASSWORD='...'
export DATAFORSEO_LOGIN="$DATAFORSEO_USERNAME"
python3 tools/dfs_vn_probe.py          # free endpoints only, $0.00
```

## Commit

Two commits, one per repository.

`claude-blog`:

```
feat(vi): add DataForSEO Labs wrapper and Vietnam market defaults

blog-cannibalization documented an --api mode requiring a local
DataForSEO wrapper, but no such wrapper existed anywhere in the
repository, so the path always fell back to local mode. The two sibling
repositories also disagreed on the credential variable names
(DATAFORSEO_LOGIN here, DATAFORSEO_USERNAME in claude-seo), so a single
export could not serve both.

- claude-blog/scripts/dataforseo_labs.py: page_intersection and ranked_keywords,
  accepting either credential variable name, structured error on missing
  credentials, credentials never printed
- Vietnam defaults: location_code 2704, language_code vi
- CLAUDE.md: default-market rules, including that search_volume bills per
  task rather than per keyword, so keywords must be batched
```

`claude-seo`:

```
fix(vi): default to the Vietnam market and correct DataForSEO cost model

- location_code 2840 -> 2704 and language_code en -> vi across skills,
  agents and scripts
- dataforseo_costs.py: Labs moved from a flat $0.05 to $0.012 per task
  plus $0.00012 per item, so a 1000-item call is $0.132 and was being
  under-estimated 2.6x, silently bypassing the budget gate. Other
  endpoints reflect the 2026-07-01 increase.
- ENABLED_MODULES trimmed to SERP, KEYWORDS_DATA, DATAFORSEO_LABS, ONPAGE
- scripts/dfs_vn_probe.py: free-endpoint account and market readiness
  check

Note: DataForSEO Labs covers Vietnam at country level only. City-level
work must use the SERP API, which has 3,552 Vietnamese locations.
```
