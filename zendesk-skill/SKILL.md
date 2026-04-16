---
name: zendesk-skill
description: "Install and use the Zendesk MCP server for managing support tickets, comments, attachments, and knowledge base articles. Use this skill whenever the user wants to set up Zendesk integration, manage Zendesk tickets, draft support responses, analyze ticket history, look up help center articles, or do anything related to Zendesk support operations — even if they don't mention 'MCP' explicitly."
---

# Zendesk MCP Server — Install & Use

This skill covers two things: how to install the Zendesk MCP server (via Docker), and how to use the tools it provides once installed.

## Part 1: Installation

The Zendesk MCP server is a fork at https://github.com/moonshot-partners/zendesk-mcp-server (originally from reminia/zendesk-mcp-server). It runs as a Docker container that communicates with Claude over stdin/stdout.

### Prerequisites

- Docker installed and running
- A Zendesk account with API token access

### Step-by-step

1. **Clone the repo:**
   ```bash
   git clone https://github.com/moonshot-partners/zendesk-mcp-server.git
   cd zendesk-mcp-server
   ```

2. **Create the `.env` file** from the example:
   ```bash
   cp .env.example .env
   ```
   Then fill in these three values:
   - `ZENDESK_SUBDOMAIN` — the subdomain from `<subdomain>.zendesk.com`
   - `ZENDESK_EMAIL` — the email address of the Zendesk user
   - `ZENDESK_API_KEY` — generate at Admin Center > Apps and integrations > APIs > Zendesk API > Add API token

   Note: the env var is `ZENDESK_API_KEY`, not `ZENDESK_API_TOKEN`.

3. **Build the Docker image:**
   ```bash
   docker build -t zendesk-mcp-server .
   ```

4. **Register with Claude Code:**
   ```bash
   claude mcp add zendesk -- docker run --rm -i --env-file /absolute/path/to/zendesk-mcp-server/.env zendesk-mcp-server
   ```
   Replace `/absolute/path/to/` with the actual path where you cloned the repo. The `-i` flag is critical — MCP uses stdin/stdout, and without it Docker closes the pipe.

5. **Restart** the Claude Code session so the new tools appear.

### For Claude Desktop instead

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):
```json
{
  "mcpServers": {
    "zendesk": {
      "command": "/usr/local/bin/docker",
      "args": [
        "run", "--rm", "-i",
        "--env-file", "/absolute/path/to/zendesk-mcp-server/.env",
        "zendesk-mcp-server"
      ]
    }
  }
}
```
Check your Docker path with `which docker` — on Apple Silicon it may be `/opt/homebrew/bin/docker`. Use the full path since Claude Desktop doesn't inherit your shell's PATH.

### Security note

The API token has your Zendesk user's full permissions. For production instances, consider creating a dedicated Zendesk user with a scoped role rather than using your admin account.

---

## Part 2: Usage

Once installed, the following tools become available. All tools interact with the Zendesk instance configured in `.env`.

### Tools

#### `get_tickets` — List tickets
Fetches recent tickets with pagination.
- `page` (int, default 1) — page number
- `per_page` (int, default 25, max 100) — tickets per page
- `sort_by` (string, default "created_at") — sort field: `created_at`, `updated_at`, `priority`, `status`
- `sort_order` (string, default "desc") — `asc` or `desc`

Returns tickets with id, subject, status, priority, description, timestamps, requester/assignee IDs, plus pagination metadata (has_more, next_page, previous_page).

#### `get_ticket` — Get a single ticket
- `ticket_id` (int, required)

Returns id, subject, description, status, priority, timestamps, requester_id, assignee_id, organization_id.

#### `get_ticket_comments` — Get all comments on a ticket
- `ticket_id` (int, required)

Returns all comments with id, author_id, body, html_body, public flag, created_at, and attachment metadata (file_name, content_url, content_type, size).

#### `get_ticket_attachment` — Fetch an image attachment
- `content_url` (string, required) — the `content_url` from a comment's attachment metadata

Returns base64-encoded image data. Only supports JPEG, PNG, GIF, and WebP (no SVG). Has a 10 MB size cap. Use the `content_url` values returned by `get_ticket_comments`.

#### `create_ticket` — Create a new ticket
- `subject` (string, required)
- `description` (string, required)
- `requester_id` (int, optional)
- `assignee_id` (int, optional)
- `priority` (string, optional) — `low`, `normal`, `high`, `urgent`
- `type` (string, optional) — `problem`, `incident`, `question`, `task`
- `tags` (array of strings, optional)
- `custom_fields` (array of objects, optional)

#### `create_ticket_comment` — Add a comment to a ticket
- `ticket_id` (int, required)
- `comment` (string, required) — supports HTML
- `public` (boolean, default true) — set to false for internal notes

Always confirm with the user before posting public comments, since they're visible to the customer.

#### `get_macros` — List macros (canned response templates)
- `page` (int, default 1) — page number
- `per_page` (int, default 25, max 100) — macros per page
- `active_only` (boolean, default true) — when true, returns only active macros

Returns macros with id, title, description, active flag, actions (canned response text, status/priority/tag changes), restriction, and timestamps. Includes pagination metadata.

The `actions` array contains the template content — look for `comment_value` (plain text) or `comment_value_html` (HTML) fields for the canned response body. Actions may also include field changes like status, priority, tags, and assignee that the macro applies.

#### `update_ticket` — Update ticket fields
- `ticket_id` (int, required)
- `subject`, `status`, `priority`, `type`, `assignee_id`, `requester_id`, `tags`, `custom_fields`, `due_at` — all optional

Status values: `new`, `open`, `pending`, `on-hold`, `solved`, `closed`.
Priority values: `low`, `normal`, `high`, `urgent`.

### Resource

#### `zendesk://knowledge-base`
Returns all Help Center articles organized by section. Results are cached for 1 hour. Useful for drafting responses grounded in official documentation.

### Prompts

#### `analyze-ticket`
Takes a `ticket_id` and generates an analysis prompt that fetches ticket info and comments, then provides a summary, status timeline, and key interaction points.

#### `draft-ticket-response`
Takes a `ticket_id` and generates a prompt to draft a professional response that acknowledges the customer's concern, addresses issues, provides next steps, and asks for confirmation before posting.

### Common workflows

**Triage recent tickets:**
1. Use `get_tickets` to list recent tickets sorted by `updated_at`
2. Review statuses and priorities
3. Use `update_ticket` to adjust priority or assignment as needed

**Respond to a ticket:**
1. Use `get_ticket` + `get_ticket_comments` to understand the full context
2. Check `get_macros` for an existing canned response that fits, and `zendesk://knowledge-base` for relevant articles
3. Draft a response (adapt the macro template if one matches, or write from scratch)
4. Confirm with the user, then use `create_ticket_comment` to post

**Investigate a ticket with attachments:**
1. Use `get_ticket_comments` to see all comments and their attachments
2. Use `get_ticket_attachment` with the `content_url` to view images
