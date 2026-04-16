# Zendesk MCP Gap Analysis

*Date: 2026-04-16*

## What we have today (8 tools)

| Tool | Coverage |
|---|---|
| `get_ticket` | Single ticket lookup |
| `get_tickets` | List with pagination (no filtering) |
| `get_ticket_comments` | All comments + attachment metadata |
| `get_ticket_attachment` | Images only (JPEG/PNG/GIF/WebP) |
| `create_ticket` | Basic creation |
| `create_ticket_comment` | Public reply or internal note |
| `update_ticket` | Field changes (status, priority, assignee, etc.) |
| `get_macros` | List macros with canned responses |

## What's missing — grouped by priority

### P0: Essential for managing support (MCP tools)

| Gap | API Support | Recommendation |
|---|---|---|
| **Search tickets** | `GET /search?query=type:ticket status:open...` | Add `search_tickets` tool. This is the biggest gap — can't filter by status, assignee, tags, dates, or keywords. Without it, the agent is blind. |
| **Get user info** | `GET /users/{id}` + `GET /users/search` | Add `get_user` tool. Every ticket has requester_id/assignee_id but no way to resolve them to names/emails. |
| **Views** | `GET /views/{id}/tickets` | Add `get_view` / `list_views` tools. Views are how agents actually work in Zendesk ("My open tickets", "Unassigned", etc.). |
| **Apply macro preview** | `GET /tickets/{id}/macros/{macro_id}/apply` | Add `preview_macro` tool. Returns what a macro *would* do to a ticket without saving. Critical for the draft workflow. |

### P1: Important for a capable agent (MCP tools)

| Gap | API Support | Recommendation |
|---|---|---|
| **Ticket fields metadata** | `GET /ticket_fields` | Add `get_ticket_fields`. The agent needs to know what custom fields exist and their options. |
| **Groups** | `GET /groups` | Add `list_groups`. Needed for routing/assigning tickets to teams. |
| **Ticket metrics** | `GET /tickets/{id}/metrics` | Add `get_ticket_metrics`. Reply time, resolution time — essential for SLA monitoring. |
| **Tags management** | `PUT /tickets/{id}/tags` | Currently `update_ticket` replaces all tags. Add `add_tags` / `remove_tags` for safe incremental changes. |
| **Non-image attachments** | Already supported by API | Extend `get_ticket_attachment` to handle PDFs/CSVs (return base64 with content_type). |

### P2: Nice-to-have (MCP tools)

| Gap | API Support | Recommendation |
|---|---|---|
| Suspended tickets | `GET /suspended_tickets` | For spam queue management |
| Ticket audits | `GET /tickets/{id}/audits` | Full change history |
| Satisfaction ratings | `GET /satisfaction_ratings` | CSAT monitoring |
| Organization lookup | `GET /organizations/{id}` | For B2B context |
| Help Center search | `GET /help_center/articles/search` | Better than loading entire KB |

## What the API does NOT support (skill/workflow layer)

These can't be solved with tools — they need process design in the skill:

| Gap | Reality | How to handle |
|---|---|---|
| **Draft replies** | No draft API exists. Comments are immutable once posted. | **Skill workflow**: Claude composes the draft in conversation, user reviews, then `create_ticket_comment` posts it. The skill should enforce "always confirm before posting." |
| **Macro application** | `preview_macro` is read-only. Applying requires a separate `update_ticket` call. | **Skill workflow**: preview -> Claude shows the result -> user confirms -> update ticket + post comment as two separate calls. |
| **Triage logic** | The API returns data but doesn't decide priority/assignment. | **Skill workflow**: Define Patternbank-specific triage rules (Buyer vs Seller, SLA timers, escalation criteria) in the skill. |
| **Template personalization** | Macros have `{{ticket.requester.first_name}}` but the API returns raw placeholders. | **Skill workflow**: Claude resolves placeholders by fetching user info via `get_user`, then adapting the template. |
| **Round-robin assignment** | No API for this. | **Skill workflow**: Encode the agent rotation logic (Neil/"Jason" and Andrew/"Paul") in the skill. |

## Dangerous operations to NEVER expose

| Operation | Why |
|---|---|
| Delete user | Permanent, GDPR-level data loss |
| Merge tickets/users | Irreversible |
| Bulk delete | Too easy to wipe tickets |
| Mark as spam | Suspends requester + deletes |
| Redact comments | Irreversible content removal |
| Delete ticket fields | Destroys data across all tickets |

## Rate limit considerations

- General API: 200 RPM on Team plan (Patternbank's plan)
- Search: ~5 RPM — the skill should warn about hammering search
- Batch approach preferred for scheduled triage (fetch once, analyze locally)

## Proposed architecture

```
+-------------------------------------+
|  MCP Server (this repo)             |
|  Pure API tools - no business logic  |
|                                     |
|  Existing: 8 tools                  |
|  Add: search_tickets, get_user,     |
|       list_views, get_view_tickets, |
|       preview_macro, get_ticket_    |
|       fields, list_groups,          |
|       get_ticket_metrics            |
|                                     |
|  Total: ~16 tools                   |
+------------------+------------------+
                   |
+------------------v------------------+
|  Skill (zendesk-skill/SKILL.md)     |
|  Patternbank-specific workflows     |
|                                     |
|  - Triage rules & SLA enforcement   |
|  - Draft-review-post workflow       |
|  - Macro selection & personalization |
|  - Agent assignment (round-robin)   |
|  - Ticket categorization (Buyer/    |
|    Seller/General)                  |
|  - Escalation criteria              |
|  - Cowork scheduled task templates  |
+-------------------------------------+
```

The MCP server stays generic (any Zendesk instance could use it). The skill encodes Patternbank's process.

## Zendesk API Reference (full)

### Authentication & Rate Limits

- **API Token**: `{email}/token:{api_token}` via HTTP Basic Auth
- **OAuth 2.0**: Bearer token flow with scopes
- **Rate Limits**: Team 200 RPM, Professional 400 RPM, Enterprise 700 RPM
- **Search limit**: ~5 RPM per agent (stricter)

### Tickets

- `GET /tickets` — list (paginated)
- `GET /tickets/{id}` — show single
- `POST /tickets` — create (can include comment, tags, custom fields)
- `PUT /tickets/{id}` — update (status, priority, assignee, add comment, tags)
- `DELETE /tickets/{id}` — soft delete (30 day retention)
- `POST /tickets/create_many` — bulk create (up to 100)
- `PUT /tickets/update_many` — bulk update (up to 100)
- `POST /tickets/{id}/merge` — merge (IRREVERSIBLE)

### Comments

- Added via `PUT /tickets/{id}` with `comment` in body
- `comment.public: true` = customer-visible reply; `false` = internal note
- `body` (plain text) or `html_body` (HTML)
- `GET /tickets/{id}/comments` — list all
- Comments are IMMUTABLE once created (can only redact)
- No draft API exists

### Macros

- `GET /macros` — list all
- `GET /macros/active` — active only
- `GET /macros/{id}` — single macro
- `GET /macros/{id}/apply` — preview what macro would change (no save)
- `GET /tickets/{id}/macros/{macro_id}/apply` — preview on specific ticket (no save)
- `GET /macros/search?query=...` — search by title
- Actions: set status, priority, type, assignee, group, tags, comment text, custom fields

### Views

- `GET /views` — list all views
- `GET /views/{id}` — view definition with conditions
- `GET /views/{id}/execute` — execute view (returns matching tickets)
- `GET /views/{id}/tickets` — tickets in view
- `GET /views/count_many?ids=1,2,3` — ticket counts per view
- `POST /views/preview` — execute arbitrary conditions without saving

### Search

- `GET /search?query=...` — unified search (tickets, users, orgs)
- Query syntax: `type:ticket status:open priority:high assignee:email`
- Filters: status, priority, assignee, group, requester, subject, description, tags, created/updated ranges, custom fields
- Negation with `-`, exact phrase with `""`, combine with spaces (AND) or `OR`
- Max 1000 results, paginated (100/page)

### Users & Organizations

- `GET /users/{id}` — full profile (name, email, role, org, tags)
- `GET /users/search?query=...` — search by name/email
- `GET /users/autocomplete?name=...` — prefix match
- `GET /organizations/{id}` — org details
- `GET /organizations/{id}/tickets` — org's tickets

### Tags

- `GET /tags` — all tags with counts
- `PUT /tickets/{id}/tags` — add tags (append)
- `DELETE /tickets/{id}/tags` — remove specific tags
- Tags on tickets set via update replaces ALL tags

### Triggers & Automations

- Full CRUD for both (`GET/POST/PUT/DELETE /triggers`, `/automations`)
- Triggers = event-based; Automations = time-based
- Searchable: `GET /triggers/search?query=...`

### SLA Policies (Professional+ only)

- `GET /slas/policies` — list
- SLA status on tickets via ticket metrics or audits
- No direct `/tickets/{id}/sla_status` endpoint

### Satisfaction Ratings

- `GET /satisfaction_ratings` — list (filterable by score, date range)
- Ticket object includes `satisfaction_rating.score` (good/bad/offered)

### Ticket Fields & Forms

- `GET /ticket_fields` — all system + custom fields with types/options
- `GET /ticket_forms` — (Professional+ only)
- Field types: text, textarea, checkbox, date, integer, decimal, regexp, tagger (dropdown), multiselect (Enterprise)

### Groups

- `GET /groups` — all agent groups
- `GET /groups/assignable` — groups tickets can be assigned to
- `GET /groups/{id}/memberships` — agents in group
- Assign ticket to group: `PUT /tickets/{id}` with `group_id`

### Ticket Metrics

- `GET /tickets/{id}/metrics` — reply time, resolution time, reopens, assignments
- `GET /ticket_metrics` — bulk metrics

### Ticket Audits

- `GET /tickets/{id}/audits` — complete change history (status changes, field updates, comments, assignments, SLA events)
- Read-only

### Attachments

- `POST /uploads?filename=...` — upload (returns token)
- Include `"uploads": ["token"]` in comment to attach
- `GET /attachments/{id}` — metadata + content_url

### Help Center

- `GET /help_center/articles` — list
- `GET /help_center/articles/search?query=...` — full-text search
- `GET /help_center/sections` — list sections
- `GET /help_center/categories` — list categories

### Side Conversations (Enterprise only)

- Not a draft mechanism
- Separate threads (email/Slack/child ticket) linked to parent ticket

### Suspended Tickets

- `GET /suspended_tickets` — spam queue
- `PUT /suspended_tickets/{id}/recover` — recover to active queue

### Pagination

- Offset: `?page=2&per_page=100` (max 10,000 records)
- Cursor-based: `?page[size]=100&page[after]=cursor` (recommended for large datasets)

### Plan-Tier Feature Matrix

| Feature | Team | Professional | Enterprise |
|---|---|---|---|
| Ticket CRUD, comments, search | Yes | Yes | Yes |
| Multiple ticket forms | No | Yes | Yes |
| SLA Policies | No | Yes | Yes |
| Side Conversations | No | No | Yes |
| Multiselect custom fields | No | No | Yes |
| Triggers & Automations | Yes | Yes | Yes |
| Views & Macros | Yes | Yes | Yes |
| Help Center (Guide) | Varies | Yes | Yes |
| Satisfaction Ratings | Yes | Yes | Yes |
