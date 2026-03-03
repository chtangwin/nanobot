---
name: webfetch-guide
description: Guidance for using web_fetch tool effectively — when to use discovery mode, forceBrowser, and how to handle X/Twitter content.
---

# Web Fetch Usage Guide

The `web_fetch` tool supports three modes. Choose the right one for your task:

## Quick Reference

| Scenario | Parameters |
|----------|-----------|
| Read an article or docs page | `web_fetch(url="...")` |
| Page shows blank or nav-only text | `web_fetch(url="...", forceBrowser=true)` |
| Page has "Load More" / "Next" / pagination | `web_fetch(url="...", mode="discovery")` |
| X/Twitter profile posts | `web_fetch(url="https://x.com/username")` — auto-routes to X adapter |
| X/Twitter single tweet | `web_fetch(url="https://x.com/user/status/123")` |

## Mode Details

### Default (snapshot)
- Tries fast HTTP first; auto-upgrades to browser if content is JS-rendered
- Good for: articles, docs, blogs, API responses
- Response includes `source_tier` showing which path was used ("http" or "browser")

### discovery mode
- Use when you need **all items** from a paginated list or table
- Automatically clicks "See More", "Load More", "Next" buttons and scrolls
- Example: leaderboards, product listings, search results with pagination
- `discovery_actions` in response shows what buttons were clicked

### forceBrowser
- Skip HTTP attempt, go straight to browser rendering
- Use when you already know the site needs JavaScript
- Slightly slower but avoids the failed HTTP → retry delay

## X/Twitter

X URLs are automatically handled by a dedicated adapter:
- Profile URLs (`x.com/username`): scrolls and collects posts with text, dates, engagement, media
- Tweet URLs (`x.com/user/status/123`): fetches individual tweet content
- Uses auth from `~/.nanobot/auth/x_auth.json` (preferred) or built-in placeholder
- Default placeholder auth may only return ~10-15 posts; generate your own for full access

### Setting up X login

Run once to generate your own auth file:

```bash
uv run python -m nanobot.webfetch.adapters.x_login
```

This opens a browser window. Log into X manually; the script auto-detects successful login and saves auth to `~/.nanobot/auth/x_auth.json`.

## Response Fields

Key fields in the JSON response:

| Field | Description |
|-------|-------------|
| `ok` | true if content was successfully extracted |
| `text` | The extracted content |
| `source_tier` | "http", "browser", or "adapter:x_com" |
| `needs_browser_reason` | Why browser was needed (if applicable) |
| `discovery_actions` | List of click/scroll actions taken (discovery mode) |
| `discovered_items` | Number of items found during discovery |
| `error` | Error message if something went wrong |

## Troubleshooting

- **Empty content**: Try `forceBrowser=true`
- **Partial list**: Use `mode="discovery"`
- **X returns login wall**: Re-run `x_login` to refresh auth
- **Timeout**: The site may be slow; try again or check the URL
