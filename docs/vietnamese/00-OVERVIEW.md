# Overview: Vietnamese Support

## 1. The problem in one paragraph

`claude-blog` scores every post through `scripts/analyze_blog.py`, and the 5-gate Blog
Delivery Contract blocks any draft scoring below 90/100. That scoring is **language-gated**
by a `LANGUAGE_PROFILES` dictionary containing exactly two entries: `en` and `tr`. A
Vietnamese post is silently classified as English, so five of its six profile-driven signals
misfire at once - and in **opposite directions**. Readability is inflated (Flesch on
Vietnamese is meaningless), while E-E-A-T Trust, Experience, methodology and AI Citation
Readiness are deflated, because the analyzer is searching Vietnamese prose for the English
strings `about us`, `contact`, `I tested`, `TL;DR`. The result is roughly 30 of 100 points
lost to language mismatch, which puts Gate 4's 90-point threshold **structurally out of
reach**. The iteration loop then dispatches `blog-writer` to "fix the lowest-scoring
category", which is not broken. Separately, `blog_render.py` generates the published URL
slug by deleting every non-ASCII character without normalizing, so *"Hướng dẫn đặt hàng
online"* ships as `hng-dn-t-hng-online`.

## 2. Verified evidence

Every claim below was checked against the working tree, not inferred.

### 2.1 Zero Vietnamese support anywhere

```bash
grep -ril "vietnam\|vi-VN\|tiếng việt" claude-seo claude-blog claude-ads codex-seo
# -> no matches
```

### 2.2 The language profile gate

`claude-blog/scripts/analyze_blog.py:156`

```python
LANGUAGE_PROFILES: dict[str, dict[str, Any]] = {
    'en': { 'summary_labels': (...), 'about_patterns': (...), 'contact_patterns': (...),
            'first_person_patterns': (...), 'methodology_patterns': (...),
            'readability_model': 'flesch' },
    'tr': { ..., 'readability_model': 'atesman' },
}
```

`analyze_blog.py:528-544` - `_detect_language()`:

```python
declared = str(frontmatter.get('lang') or frontmatter.get('language')
               or frontmatter.get('inLanguage') or '').strip().lower()
if declared:
    primary = re.split(r'[-_]', declared, maxsplit=1)[0]
    return primary if primary in LANGUAGE_PROFILES else 'en'   # <-- SILENT FALLBACK

strong_turkish_markers = len(re.findall(r'[ığşİĞŞ]', body))    # only Turkish gets a heuristic
letters = len(re.findall(r'[^\W\d_]', body, re.UNICODE))
if strong_turkish_markers >= 2 and strong_turkish_markers / max(letters, 1) >= 0.002:
    return 'tr'
return 'en'
```

Two independent failures compound here:

1. `blog-write/SKILL.md:224-234` - the frontmatter template it tells the writer to emit has
   **no `lang:` field at all** (only title, description, coverImage, coverImageAlt, ogImage,
   date, lastUpdated, author, tags). So `declared` is empty for every generated post.
2. Even when an author writes `lang: vi` by hand, line 538 returns `'en'` because `'vi'` is
   not a key. **No warning is emitted.**

### 2.3 What a wrong profile actually costs

| Site | Code | Vietnamese effect |
|---|---|---|
| `analyze_blog.py:864` | readability routing | falls to Flesch → **inflated** score. Flesch counts English syllables; Vietnamese is monosyllabic, so nearly every word scores as "easy". |
| `analyze_blog.py:1176` | `profile['first_person_patterns']` | `"chúng tôi đã thử nghiệm"` never matches `\bI\s+(?:found|tested…)\b` → `first_person_experience` marker **never fires** |
| `analyze_blog.py:1183` | `profile['methodology_patterns']` | `"phương pháp"`, `"cỡ mẫu"` never match → methodology count 0 |
| `analyze_blog.py:1295-1296` | `profile['summary_labels']` | `"Tóm tắt"`, `"Điểm chính"` never match → `has_tldr = False` → AI Citation Readiness penalized at lines 1539, 1921, 1942 |
| `analyze_blog.py:1746-1748` | `profile['about_patterns']` | `"Về chúng tôi"`, `"Giới thiệu"` never match → **Trust −2** |
| `analyze_blog.py:1749-1751` | `profile['contact_patterns']` | `"Liên hệ"` never matches → **Trust −1** |

Two further sites are **hardcoded English and not in the profile at all**, so adding a
`'vi'` key does *not* fix them:

| Site | Code | Problem |
|---|---|---|
| `analyze_blog.py:1291` | `re.findall(r'\*\*[^*]+\*\*\s*(?:is\|are\|refers to\|means)', content)` | Vietnamese definitions read `**X** là …`, `**X** nghĩa là …` |
| `analyze_blog.py:1751` | `re.search(r'(?i)\b(?:editorial\|reviewed by\|fact.?check\|editor)\b', body)` | Vietnamese: `biên tập`, `kiểm chứng`, `đã được duyệt bởi` |

### 2.4 Slug destruction - reproduced

`claude-blog/scripts/blog_render.py:161`, used at line 566 to name the published file:

```python
def _slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9\s\-]", "", s)     # deletes EVERY Vietnamese accented character
    ...
```

Actual output, run against the real function body:

| Title | Slug produced | Correct |
|---|---|---|
| `Hướng dẫn đặt hàng online` | `hng-dn-t-hng-online` | `huong-dan-dat-hang-online` |
| `Đánh giá sản phẩm 2026` | `nh-gi-sn-phm-2026` | `danh-gia-san-pham-2026` |
| `Cách viết nội dung chuẩn SEO` | `cch-vit-ni-dung-chun-seo` | `cach-viet-noi-dung-chuan-seo` |
| `Top 10 quán cà phê Hà Nội` | `top-10-qun-c-ph-h-ni` | `top-10-quan-ca-phe-ha-noi` |

`claude-blog/scripts/blog_hygiene.py:39-45` (used for heading anchors) is better but still
wrong:

```python
text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
```

NFKD decomposes `ư`→`u`+horn and `ớ`→`o`+horn+acute, which survives the ASCII filter as
`u`/`o`. But **`đ` (U+0111) has no decomposition** - the stroke is part of the glyph, not a
combining mark - so it is deleted outright:

| Heading | Anchor produced | Correct |
|---|---|---|
| `Hướng dẫn đặt hàng online` | `huong-dan-at-hang-online` | `huong-dan-dat-hang-online` |
| `Đánh giá sản phẩm 2026` | `anh-gia-san-pham-2026` | `danh-gia-san-pham-2026` |
| `Bí quyết để thành công` | `bi-quyet-e-thanh-cong` | `bi-quyet-de-thanh-cong` |

Anchors and file names therefore disagree with each other **and** both are wrong.

### 2.5 A DataForSEO wrapper that does not exist

`claude-blog/skills/blog-cannibalization/SKILL.md:81-86`:

> Requires the `--api` flag and a dedicated local CLI wrapper that reads `DATAFORSEO_LOGIN`
> and `DATAFORSEO_PASSWORD` from the environment and emits JSON. […] If no wrapper exists in
> the project, report `SKIPPED: DataForSEO wrapper unavailable` and run local mode.

```bash
grep -rn "DATAFORSEO" --include=*.py claude-blog/
# -> no matches
```

The `--api` path has never executed. Worse, the two repositories disagree on the variable
names:

| Repository | Variables |
|---|---|
| `claude-seo` (`scripts/dataforseo_merchant.py`, `extensions/dataforseo/install.sh`) | `DATAFORSEO_USERNAME` / `DATAFORSEO_PASSWORD` |
| `claude-blog` (`blog-cannibalization`) | `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` |

### 2.6 US market hardcoded in 29 places

`location_code=2840` (United States) and `language_code=en` are the documented defaults
across skills, agents and scripts in both repositories. Vietnam is `2704`. Verified against
DataForSEO's own published location CSV:

```csv
2704,Vietnam,,VN,Country,google,Vietnamese,vi,41271976,1564638
2704,Vietnam,,VN,Country,google,English,en,20477026,570712
```

Vietnam is supported with 41.2M keywords in the `vi` database - but **only at
`location_type=Country`**. There are no province-level rows for Vietnam in the Labs
database, while the SERP location file has 3,552 Vietnamese entries (Hanoi `1028580`,
Ho Chi Minh City `1028581`, Da Nang `1028809`).

## 3. Architectural principle

> **All Vietnamese logic lives in `scripts/vi_*.py`. Nothing else.**

The reasoning, carried over from `IMPROVE-VA-CONVERT-CODEX.md`:

- Python scripts port to Codex CLI **unchanged** - same file, same CLI, same JSON contract.
- `SKILL.md` files, agent definitions and hook configs **must be rewritten** for Codex.
- Therefore every rule expressed as Python is portable for free, and every rule expressed
  as prose in a SKILL.md costs a rewrite later.

Concretely:

| Do | Do not |
|---|---|
| `scripts/vi_text.py` - normalization, slug, syllable counting | Inline `unicodedata` calls scattered across three scripts |
| `scripts/vi_profile.py` - the `LANGUAGE_PROFILES['vi']` payload | A 60-line dict pasted into `analyze_blog.py` |
| `scripts/vi_prose.py` - AI-tell and register linting | A bullet list of "avoid these phrases" in a SKILL.md |
| A thin `SKILL.md` that says *"run `scripts/vi_prose.py`"* | A SKILL.md that restates the rules in prose |

This is not style preference. It cuts the eventual Codex port from an estimated 6-8 days to
1-2 days, and it is the difference between rules that are *enforced* and rules that are
*suggested to a model*.

## 4. Phase map

| Phase | Title | Priority | Repo | Est. | Blocking? |
|---|---|---|---|---|---|
| 0 | Test harness and Vietnamese fixtures | must-first | claude-blog | 0.5d | blocks all |
| 1 | Vietnamese-safe slugs | **P0** | claude-blog | 0.5d | no |
| 2 | Vietnamese language profile | **P0** | claude-blog | 1d | no |
| 3 | Vietnamese prose linter | P1 | claude-blog | 1d | no |
| 4 | DataForSEO Vietnam defaults + wrapper | P1 | both | 1d | no |
| 5 | Discourse platforms, skill docs, frontmatter | P2 | claude-blog | 0.5d | no |
| 6 | End-to-end Vietnamese post + self-review | verification | claude-blog | 0.5d | needs 0-5 |

Total: roughly 5 developer-days.

### Why slug is P0 alongside the scoring fix

The scoring defect blocks *publication*. The slug defect *ships*. A post that clears every
gate still goes live at `/blog/hng-dn-t-hng-online`, which is unreadable, unsearchable, and
expensive to change afterwards because the URL is the one artifact you cannot revise without
a redirect. Fix it before the first Vietnamese post is published, not after.

## 5. Out of scope

Explicitly **not** part of this work:

- Porting anything to Codex CLI. The `vi_*.py` structure makes that cheap later; doing it now
  costs 6-8 days for two unfixable risks (loss of subagent isolation, possible loss of
  parallel dispatch which destroys the fresh-context reviewer).
- `claude-ads` - advertising platform tooling, unrelated to content marketing.
- `codex-seo` - a port of `claude-seo` that trails it by three minor versions. Fixing
  `claude-seo` first and re-porting is cheaper than fixing both.
- Vietnamese CMS integrations (Haravan, Sapo, KiotViet). Real gap, separate project.
- The pre-existing `test_markdown_body_html_is_sanitized` failure. See `README.md` § Baseline.

## 6. Upstreamability

Both repositories are MIT-licensed and the `'tr'` profile is an existing precedent for
adding a non-English language. Phases 1, 2 and 5 are written to be acceptable as an upstream
pull request to `AgriciDaniel/claude-blog` - no Vietnam-specific hardcoding outside the
`vi` profile, no behavior change for `en` or `tr`, tests included. Phase 4 partly is
(the wrapper), partly is not (market defaults are a local preference and belong in
`CLAUDE.md`, not in the upstream repository).
