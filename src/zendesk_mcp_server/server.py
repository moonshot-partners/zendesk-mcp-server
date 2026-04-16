import asyncio
import json
import logging
import os
from typing import Any, Dict

from cachetools.func import ttl_cache
from dotenv import load_dotenv
from mcp.server import InitializationOptions, NotificationOptions, Server
from mcp import types
from mcp.server.stdio import stdio_server
from pydantic import AnyUrl

from zendesk_mcp_server.zendesk_client import ZendeskClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("zendesk-mcp-server")
logger.info("zendesk mcp server started")

load_dotenv()
zendesk_client = ZendeskClient(
    subdomain=os.getenv("ZENDESK_SUBDOMAIN"),
    email=os.getenv("ZENDESK_EMAIL"),
    token=os.getenv("ZENDESK_API_KEY")
)

server = Server("Zendesk Server")

TICKET_ANALYSIS_TEMPLATE = """
You are a helpful Zendesk support analyst. You've been asked to analyze ticket #{ticket_id}.

Please fetch the ticket info and comments to analyze it and provide:
1. A summary of the issue
2. The current status and timeline
3. Key points of interaction

Remember to be professional and focus on actionable insights.
"""

COMMENT_DRAFT_TEMPLATE = """
You are a helpful Zendesk support agent. You need to draft a response to ticket #{ticket_id}.

Please fetch the ticket info, comments and knowledge base to draft a professional and helpful response that:
1. Acknowledges the customer's concern
2. Addresses the specific issues raised
3. Provides clear next steps or ask for specific details need to proceed
4. Maintains a friendly and professional tone
5. Ask for confirmation before commenting on the ticket

The response should be formatted well and ready to be posted as a comment.
"""


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """List available prompts"""
    return [
        types.Prompt(
            name="analyze-ticket",
            description="Analyze a Zendesk ticket and provide insights",
            arguments=[
                types.PromptArgument(
                    name="ticket_id",
                    description="The ID of the ticket to analyze",
                    required=True,
                )
            ],
        ),
        types.Prompt(
            name="draft-ticket-response",
            description="Draft a professional response to a Zendesk ticket",
            arguments=[
                types.PromptArgument(
                    name="ticket_id",
                    description="The ID of the ticket to respond to",
                    required=True,
                )
            ],
        )
    ]


@server.get_prompt()
async def handle_get_prompt(name: str, arguments: Dict[str, str] | None) -> types.GetPromptResult:
    """Handle prompt requests"""
    if not arguments or "ticket_id" not in arguments:
        raise ValueError("Missing required argument: ticket_id")

    ticket_id = int(arguments["ticket_id"])
    try:
        if name == "analyze-ticket":
            prompt = TICKET_ANALYSIS_TEMPLATE.format(
                ticket_id=ticket_id
            )
            description = f"Analysis prompt for ticket #{ticket_id}"

        elif name == "draft-ticket-response":
            prompt = COMMENT_DRAFT_TEMPLATE.format(
                ticket_id=ticket_id
            )
            description = f"Response draft prompt for ticket #{ticket_id}"

        else:
            raise ValueError(f"Unknown prompt: {name}")

        return types.GetPromptResult(
            description=description,
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=prompt.strip()),
                )
            ],
        )

    except Exception as e:
        logger.error(f"Error generating prompt: {e}")
        raise


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available Zendesk tools"""
    return [
        types.Tool(
            name="get_ticket",
            description="Retrieve a Zendesk ticket by its ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ID of the ticket to retrieve"
                    }
                },
                "required": ["ticket_id"]
            }
        ),
        types.Tool(
            name="create_ticket",
            description="Create a new Zendesk ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Ticket subject"},
                    "description": {"type": "string", "description": "Ticket description"},
                    "requester_id": {"type": "integer"},
                    "assignee_id": {"type": "integer"},
                    "priority": {"type": "string", "description": "low, normal, high, urgent"},
                    "type": {"type": "string", "description": "problem, incident, question, task"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "custom_fields": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["subject", "description"],
            }
        ),
        types.Tool(
            name="get_tickets",
            description="Fetch the latest tickets with pagination support",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "Page number",
                        "default": 1
                    },
                    "per_page": {
                        "type": "integer",
                        "description": "Number of tickets per page (max 100)",
                        "default": 25
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "Field to sort by (created_at, updated_at, priority, status)",
                        "default": "created_at"
                    },
                    "sort_order": {
                        "type": "string",
                        "description": "Sort order (asc or desc)",
                        "default": "desc"
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="get_ticket_comments",
            description="Retrieve all comments for a Zendesk ticket by its ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ID of the ticket to get comments for"
                    }
                },
                "required": ["ticket_id"]
            }
        ),
        types.Tool(
            name="create_ticket_comment",
            description="Create a new comment on an existing Zendesk ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ID of the ticket to comment on"
                    },
                    "comment": {
                        "type": "string",
                        "description": "The comment text/content to add"
                    },
                    "public": {
                        "type": "boolean",
                        "description": "Whether the comment should be public",
                        "default": True
                    }
                },
                "required": ["ticket_id", "comment"]
            }
        ),
        types.Tool(
            name="get_ticket_attachment",
            description="Fetch a Zendesk ticket attachment by its content_url and return the file as base64-encoded data. Supports images (JPEG, PNG, GIF, WebP), PDFs, CSVs, and other file types. Use the attachment URLs returned by get_ticket_comments.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content_url": {
                        "type": "string",
                        "description": "The content_url of the attachment from get_ticket_comments"
                    }
                },
                "required": ["content_url"]
            }
        ),
        types.Tool(
            name="get_macros",
            description="Fetch Zendesk macros (canned response templates). Returns macro titles, descriptions, and the actions they apply (e.g., setting status, adding a canned response).",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "Page number",
                        "default": 1
                    },
                    "per_page": {
                        "type": "integer",
                        "description": "Number of macros per page (max 100)",
                        "default": 25
                    },
                    "active_only": {
                        "type": "boolean",
                        "description": "If true, return only active macros",
                        "default": True
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="search_tickets",
            description="Search Zendesk tickets using query language. Supports filters for status, priority, assignee, tags, and date ranges. NOTE: Search API has a stricter rate limit (~5 requests/minute).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Raw Zendesk query (e.g. 'subject:billing refund'). Combined with convenience filters below."},
                    "status": {"type": "string", "description": "Filter by status: new, open, pending, hold, solved, closed"},
                    "priority": {"type": "string", "description": "Filter by priority: low, normal, high, urgent"},
                    "assignee": {"type": "string", "description": "Filter by assignee name or email"},
                    "tags": {"type": "string", "description": "Filter by tag name"},
                    "created_after": {"type": "string", "description": "ISO8601 date — tickets created after this date"},
                    "created_before": {"type": "string", "description": "ISO8601 date — tickets created before this date"},
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                    "per_page": {"type": "integer", "description": "Results per page (max 100)", "default": 25},
                },
                "required": []
            }
        ),
        types.Tool(
            name="get_user",
            description="Get a Zendesk user by ID, or search users by name/email. Provide either user_id or query, not both.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "User ID to look up directly"},
                    "query": {"type": "string", "description": "Search by name or email address"},
                },
                "required": []
            }
        ),
        types.Tool(
            name="list_views",
            description="List all Zendesk views accessible to the current agent. Views are saved ticket filters (e.g. 'My open tickets', 'Unassigned').",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        types.Tool(
            name="get_view_tickets",
            description="Get tickets matching a Zendesk view. Use list_views first to find view IDs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "view_id": {"type": "integer", "description": "The view ID"},
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                    "per_page": {"type": "integer", "description": "Tickets per page (max 100)", "default": 25},
                },
                "required": ["view_id"]
            }
        ),
        types.Tool(
            name="preview_macro",
            description="Preview what a macro would do to a specific ticket WITHOUT applying it. Returns the resulting ticket changes and comment text. Use this to draft responses before posting.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "The ticket to preview against"},
                    "macro_id": {"type": "integer", "description": "The macro to preview (use get_macros to find IDs)"},
                },
                "required": ["ticket_id", "macro_id"]
            }
        ),
        types.Tool(
            name="get_ticket_fields",
            description="List all system and custom ticket fields with their types, options, and required status.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        types.Tool(
            name="list_groups",
            description="List all agent groups. Groups are used for ticket routing and assignment.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        types.Tool(
            name="get_ticket_metrics",
            description="Get performance metrics for a ticket: reply time, resolution time, reopens, and assignment history.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "The ticket ID"},
                },
                "required": ["ticket_id"]
            }
        ),
        types.Tool(
            name="manage_tags",
            description="Add or remove tags on a ticket without replacing existing ones. Safer than update_ticket for tag changes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "The ticket ID"},
                    "action": {"type": "string", "description": "'add' or 'remove'", "enum": ["add", "remove"]},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags to add or remove"},
                },
                "required": ["ticket_id", "action", "tags"]
            }
        ),
        types.Tool(
            name="update_ticket",
            description="Update fields on an existing Zendesk ticket (e.g., status, priority, assignee_id)",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "The ID of the ticket to update"},
                    "subject": {"type": "string"},
                    "status": {"type": "string", "description": "new, open, pending, on-hold, solved, closed"},
                    "priority": {"type": "string", "description": "low, normal, high, urgent"},
                    "type": {"type": "string"},
                    "assignee_id": {"type": "integer"},
                    "requester_id": {"type": "integer"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "custom_fields": {"type": "array", "items": {"type": "object"}},
                    "due_at": {"type": "string", "description": "ISO8601 datetime"}
                },
                "required": ["ticket_id"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(
        name: str,
        arguments: dict[str, Any] | None
) -> list[types.TextContent]:
    """Handle Zendesk tool execution requests"""
    args = arguments or {}
    try:
        if name == "get_ticket":
            ticket = zendesk_client.get_ticket(args["ticket_id"])
            return [types.TextContent(type="text", text=json.dumps(ticket))]

        elif name == "create_ticket":
            created = zendesk_client.create_ticket(
                subject=args["subject"],
                description=args["description"],
                requester_id=args.get("requester_id"),
                assignee_id=args.get("assignee_id"),
                priority=args.get("priority"),
                type=args.get("type"),
                tags=args.get("tags"),
                custom_fields=args.get("custom_fields"),
            )
            return [types.TextContent(
                type="text",
                text=json.dumps({"message": "Ticket created successfully", "ticket": created}, indent=2)
            )]

        elif name == "get_tickets":
            tickets = zendesk_client.get_tickets(
                page=args.get("page", 1),
                per_page=args.get("per_page", 25),
                sort_by=args.get("sort_by", "created_at"),
                sort_order=args.get("sort_order", "desc"),
            )
            return [types.TextContent(type="text", text=json.dumps(tickets, indent=2))]

        elif name == "get_ticket_comments":
            comments = zendesk_client.get_ticket_comments(args["ticket_id"])
            return [types.TextContent(type="text", text=json.dumps(comments))]

        elif name == "create_ticket_comment":
            result = zendesk_client.post_comment(
                ticket_id=args["ticket_id"],
                comment=args["comment"],
                public=args.get("public", True),
            )
            return [types.TextContent(type="text", text=f"Comment created successfully: {result}")]

        elif name == "get_ticket_attachment":
            result = zendesk_client.get_ticket_attachment(args["content_url"])
            content_type = result["content_type"]
            if content_type.startswith("image/"):
                return [types.ImageContent(
                    type="image",
                    data=result["data"],
                    mimeType=content_type,
                )]
            else:
                return [types.TextContent(
                    type="text",
                    text=json.dumps({"content_type": content_type, "data_base64": result["data"]})
                )]

        elif name == "get_macros":
            macros = zendesk_client.get_macros(
                page=args.get("page", 1),
                per_page=args.get("per_page", 25),
                active_only=args.get("active_only", True),
            )
            return [types.TextContent(type="text", text=json.dumps(macros, indent=2))]

        elif name == "search_tickets":
            result = zendesk_client.search_tickets(
                query=args.get("query", ""),
                status=args.get("status"),
                priority=args.get("priority"),
                assignee=args.get("assignee"),
                tags=args.get("tags"),
                created_after=args.get("created_after"),
                created_before=args.get("created_before"),
                page=args.get("page", 1),
                per_page=args.get("per_page", 25),
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_user":
            result = zendesk_client.get_user(
                user_id=args.get("user_id"),
                query=args.get("query"),
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "list_views":
            result = zendesk_client.list_views()
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_view_tickets":
            result = zendesk_client.get_view_tickets(
                view_id=args["view_id"],
                page=args.get("page", 1),
                per_page=args.get("per_page", 25),
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "preview_macro":
            result = zendesk_client.preview_macro(
                ticket_id=args["ticket_id"],
                macro_id=args["macro_id"],
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_ticket_fields":
            result = zendesk_client.get_ticket_fields()
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "list_groups":
            result = zendesk_client.list_groups()
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_ticket_metrics":
            result = zendesk_client.get_ticket_metrics(args["ticket_id"])
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "manage_tags":
            result = zendesk_client.manage_tags(
                ticket_id=args["ticket_id"],
                action=args["action"],
                tags=args["tags"],
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "update_ticket":
            update_fields = {k: v for k, v in args.items() if k != "ticket_id"}
            updated = zendesk_client.update_ticket(ticket_id=int(args["ticket_id"]), **update_fields)
            return [types.TextContent(
                type="text",
                text=json.dumps({"message": "Ticket updated successfully", "ticket": updated}, indent=2)
            )]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Error: {str(e)}"
        )]


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    logger.debug("Handling list_resources request")
    return [
        types.Resource(
            uri=AnyUrl("zendesk://knowledge-base"),
            name="Zendesk Knowledge Base",
            description="Access to Zendesk Help Center articles and sections",
            mimeType="application/json",
        )
    ]


@ttl_cache(ttl=3600)
def get_cached_kb():
    return zendesk_client.get_all_articles()


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    logger.debug(f"Handling read_resource request for URI: {uri}")
    if uri.scheme != "zendesk":
        logger.error(f"Unsupported URI scheme: {uri.scheme}")
        raise ValueError(f"Unsupported URI scheme: {uri.scheme}")

    path = str(uri).replace("zendesk://", "")
    if path != "knowledge-base":
        logger.error(f"Unknown resource path: {path}")
        raise ValueError(f"Unknown resource path: {path}")

    try:
        kb_data = get_cached_kb()
        return json.dumps({
            "knowledge_base": kb_data,
            "metadata": {
                "sections": len(kb_data),
                "total_articles": sum(len(section['articles']) for section in kb_data.values()),
            }
        }, indent=2)
    except Exception as e:
        logger.error(f"Error fetching knowledge base: {e}")
        raise


async def main():
    # Run the server using stdin/stdout streams
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream=read_stream,
            write_stream=write_stream,
            initialization_options=InitializationOptions(
                server_name="Zendesk",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
