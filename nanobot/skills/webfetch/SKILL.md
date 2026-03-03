---
name: webfetch
description: Fetch and extract readable content from any URL using the web_fetch tool. Handles static pages, JS/SPA sites (auto browser upgrade), paginated lists (discovery mode), and X/Twitter profiles. Use when the user asks to read a webpage, extract article content, scrape paginated data, check X/Twitter posts, or needs content from a URL.
---

# Web Fetch

`web_fetch` fetches a URL and returns extracted text content as **JSON string**. Always parse the JSON response and present the `text` field to the user — do not dump raw JSON.

## Call Examples

Basic fetch (articles, docs, blogs):
```
web_fetch(url="https://example.com/article")
```

Known JS/SPA site — skip HTTP, go straight to browser:
```
web_fetch(url="https://dashboard.example.com", forceBrowser=true)
```

Paginated list — auto-click "Load More"/"Next" and scroll:
```
web_fetch(url="https://airank.dev", mode="discovery")
```

Long document — increase max chars (default 50000):
```
web_fetch(url="https://example.com/long-doc", maxChars=100000)
```

X/Twitter profile (auto-routed to X adapter):
```
web_fetch(url="https://x.com/elonmusk")
```

X/Twitter single tweet:
```
web_fetch(url="https://x.com/user/status/123456")
```

## Quick Reference

| Scenario | Parameters |
|----------|-----------|
| Read an article or docs page | `web_fetch(url="...")` |
| Page shows blank or nav-only text | `web_fetch(url="...", forceBrowser=true)` |
| Page has "Load More" / "Next" / pagination | `web_fetch(url="...", mode="discovery")` |
| Content is truncated / too long | `web_fetch(url="...", maxChars=100000)` |
| X/Twitter profile posts | `web_fetch(url="https://x.com/username")` — auto-routes to X adapter |
| X/Twitter single tweet | `web_fetch(url="https://x.com/user/status/123")` |

## Mode Details

### Default (snapshot)
- Tries fast HTTP first; auto-upgrades to browser if content is JS-rendered
- Good for: articles, docs, blogs, API responses
- No extra parameters needed — just pass `url`

### discovery mode
- Use when you need **all items** from a paginated list or table
- Automatically clicks "See More", "Load More", "Next" buttons and scrolls
- Example: leaderboards, product listings, search results with pagination
- Check `discovered_items` in the response to verify how many items were collected

### forceBrowser
- Skip HTTP attempt, go straight to browser rendering
- Use when you already know the site needs JavaScript
- Slightly slower but avoids the failed HTTP → retry delay

## Response Handling

The response is a **JSON string** with these key fields:

| Field | Use for |
|-------|---------|
| `ok` | Check success before presenting content |
| `text` | **Main content** — present this to the user |
| `error` | If `ok=false`, show this to explain the failure |
| `source_tier` | `"http"`, `"browser"`, or `"adapter:x_com"` — explains which path was used |
| `needs_browser_reason` | Why browser was needed (e.g. `low_content_quality`, `discovery_mode`) — useful for debugging |
| `discovered_items` | Number of items found in discovery mode — report to user for verification |
| `discovery_actions` | List of click/scroll actions taken (discovery mode) |
| `truncated` | `true` if content was cut at `maxChars` limit |

**Pattern**: Always check `ok` first. If `true`, extract and present `text`. If `false`, report `error`.

## X/Twitter Content

X URLs (`x.com/*` or `twitter.com/*`) auto-route to a dedicated adapter:
- **Profile pages** (`x.com/username`): scrolls and collects posts. Each post includes text, date, engagement (likes/retweets/replies), media URLs. Output is plain text with `--- Post N ---` separators.
- **Single tweets** (`x.com/user/status/123`): fetches the individual tweet content.
- Auth from `~/.nanobot/auth/x_auth.json`. Without auth, may only get ~10-15 posts.

### Setting up X login

Run once to generate your own auth file:

```bash
uv run python -m nanobot.webfetch.adapters.x_login
```

This opens a browser window. Log into X manually; the script auto-detects successful login and saves auth to `~/.nanobot/auth/x_auth.json`.

## Troubleshooting

- **Empty content**: retry with `forceBrowser=true`
- **Partial list**: use `mode="discovery"`
- **Content too long / truncated**: increase `maxChars`
- **X login wall**: re-run `x_login` to refresh auth
- **Timeout**: the site may be slow; try again or check the URL
