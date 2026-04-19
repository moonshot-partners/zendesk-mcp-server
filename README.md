# Zendesk MCP Server

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A Model Context Protocol server for Zendesk. Fork of [reminia/zendesk-mcp-server](https://github.com/reminia/zendesk-mcp-server) with additional tools for complete support management.

This server provides a comprehensive integration with Zendesk:

- 17 tools for searching, managing, and responding to tickets
- Macro preview for drafting responses from canned templates
- User, view, group, and ticket field lookups
- Specialized prompts for ticket analysis and response drafting
- Full access to the Zendesk Help Center articles as knowledge base

## Setup

- Build: `uv venv && uv pip install -e .`
- Setup Zendesk credentials in `.env` file, refer to [.env.example](.env.example).
- Configure in Claude Desktop:

```json
{
  "mcpServers": {
      "zendesk": {
          "command": "uv",
          "args": [
              "--directory",
              "/path/to/zendesk-mcp-server",
              "run",
              "zendesk"
          ]
      }
  }
}
```

### Docker

You can containerize the server if you prefer an isolated runtime:

1. Copy `.env.example` to `.env` and fill in your Zendesk credentials. Keep this file outside version control.
2. Build the image:

   ```bash
   docker build -t zendesk-mcp-server .
   ```

3. Run the server, providing the environment file:

   ```bash
   docker run --rm --env-file /path/to/.env zendesk-mcp-server
   ```

   Add `-i` when wiring the container to MCP clients over STDIN/STDOUT (Claude Code uses this mode). For daemonized runs, add `-d --name zendesk-mcp`.

#### Claude MCP Integration

To use the Dockerized server from Claude Code/Desktop:

```json
{
  "mcpServers": {
    "zendesk": {
      "command": "/usr/local/bin/docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--env-file",
        "/path/to/zendesk-mcp-server/.env",
        "zendesk-mcp-server"
      ]
    }
  }
}
```

## Tools

### Tickets

| Tool | Description |
|---|---|
| `get_ticket` | Retrieve a single ticket by ID |
| `get_tickets` | List tickets with pagination and sorting |
| `search_tickets` | Search tickets by status, priority, assignee, tags, date ranges, or free-text query (Zendesk Query Language) |
| `create_ticket` | Create a new ticket with subject, description, priority, tags, custom fields |
| `update_ticket` | Update ticket fields (status, priority, assignee, tags, etc.) |
| `get_ticket_comments` | Get all comments on a ticket with attachment metadata |
| `create_ticket_comment` | Add a public reply or internal note to a ticket |
| `get_ticket_attachment` | Fetch an attachment as base64 (images, PDFs, CSVs, etc.) |
| `get_ticket_metrics` | Get performance metrics: reply time, resolution time, reopens |
| `get_ticket_fields` | List all system and custom ticket fields with types and options |
| `manage_tags` | Add or remove tags on a ticket without replacing existing ones |

### Views & Users

| Tool | Description |
|---|---|
| `list_views` | List all Zendesk views accessible to the current agent |
| `get_view_tickets` | Get tickets matching a specific view |
| `get_user` | Look up a user by ID, or search by name/email |
| `list_groups` | List all agent groups for routing and assignment |

### Macros

| Tool | Description |
|---|---|
| `get_macros` | List macros (canned response templates) with their actions |
| `preview_macro` | Preview what a macro would do to a ticket WITHOUT applying it |

## Resources

- `zendesk://knowledge-base` — full access to Help Center articles, cached for 1 hour.

## Prompts

### analyze-ticket

Analyze a Zendesk ticket and provide a summary, status timeline, and key interaction points.

### draft-ticket-response

Draft a professional response to a Zendesk ticket using ticket context and knowledge base.
