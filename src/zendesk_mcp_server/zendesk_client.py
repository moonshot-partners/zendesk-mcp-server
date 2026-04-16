from typing import Dict, Any, List
import json
import urllib.request
import urllib.parse
import base64
import requests as _requests

from zenpy import Zenpy
from zenpy.lib.api_objects import Comment
from zenpy.lib.api_objects import Ticket as ZenpyTicket


class ZendeskClient:
    def __init__(self, subdomain: str, email: str, token: str):
        """
        Initialize the Zendesk client using zenpy lib and direct API.
        """
        self.client = Zenpy(
            subdomain=subdomain,
            email=email,
            token=token
        )

        # For direct API calls
        self.subdomain = subdomain
        self.email = email
        self.token = token
        self.base_url = f"https://{subdomain}.zendesk.com/api/v2"
        # Create basic auth header
        credentials = f"{email}/token:{token}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode('ascii')
        self.auth_header = f"Basic {encoded_credentials}"

    def _api_get(self, endpoint: str, params: Dict[str, str] | None = None) -> Dict[str, Any]:
        """Make an authenticated GET request to the Zendesk API."""
        url = f"{self.base_url}/{endpoint}"
        if params:
            url += f"?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)
        req.add_header('Authorization', self.auth_header)
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Zendesk API error: HTTP {e.code} - {e.reason}. {error_body}")

    def _api_modify(self, endpoint: str, method: str = 'PUT', data: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Make an authenticated PUT/POST/DELETE request to the Zendesk API."""
        url = f"{self.base_url}/{endpoint}"
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('Authorization', self.auth_header)
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req) as response:
                raw = response.read()
                return json.loads(raw.decode()) if raw else {}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No response body"
            raise Exception(f"Zendesk API error: HTTP {e.code} - {e.reason}. {error_body}")

    def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        """
        Query a ticket by its ID
        """
        try:
            ticket = self.client.tickets(id=ticket_id)
            return {
                'id': ticket.id,
                'subject': ticket.subject,
                'description': ticket.description,
                'status': ticket.status,
                'priority': ticket.priority,
                'created_at': str(ticket.created_at),
                'updated_at': str(ticket.updated_at),
                'requester_id': ticket.requester_id,
                'assignee_id': ticket.assignee_id,
                'organization_id': ticket.organization_id
            }
        except Exception as e:
            raise Exception(f"Failed to get ticket {ticket_id}: {str(e)}")

    def get_ticket_comments(self, ticket_id: int) -> List[Dict[str, Any]]:
        """
        Get all comments for a specific ticket, including attachment metadata.
        """
        try:
            comments = self.client.tickets.comments(ticket=ticket_id)
            result = []
            for comment in comments:
                attachments = []
                for a in getattr(comment, 'attachments', []) or []:
                    attachments.append({
                        'id': a.id,
                        'file_name': a.file_name,
                        'content_url': a.content_url,
                        'content_type': a.content_type,
                        'size': a.size,
                    })
                result.append({
                    'id': comment.id,
                    'author_id': comment.author_id,
                    'body': comment.body,
                    'html_body': comment.html_body,
                    'public': comment.public,
                    'created_at': str(comment.created_at),
                    'attachments': attachments,
                })
            return result
        except Exception as e:
            raise Exception(f"Failed to get comments for ticket {ticket_id}: {str(e)}")

    # Magic bytes for image types that get header validation.
    _MAGIC_BYTES: Dict[str, List[bytes]] = {
        'image/jpeg': [b'\xff\xd8\xff'],
        'image/png':  [b'\x89PNG\r\n\x1a\n'],
        'image/gif':  [b'GIF87a', b'GIF89a'],
        'image/webp': [b'RIFF'],  # RIFF....WEBP — checked further below
    }

    # Blocked types that should never be downloaded (executable/script content).
    _BLOCKED_TYPES = {'application/x-executable', 'application/x-msdos-program',
                      'application/x-sh', 'text/html', 'image/svg+xml'}

    # 10 MB hard cap to guard against large files and token budget blowout.
    _MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

    def get_ticket_attachment(self, content_url: str) -> Dict[str, Any]:
        """
        Fetch an attachment and return base64-encoded data.

        Supports images (JPEG, PNG, GIF, WebP) and other file types (PDF, CSV, etc.).
        Images get magic-byte validation. Executable/script types are blocked.
        10 MB size cap on all downloads.

        Zendesk attachment URLs redirect to zdusercontent.com (Zendesk's CDN).
        requests strips the Authorization header on cross-origin redirects,
        which is required — the CDN returns 403 if it receives an auth header.
        """
        try:
            response = _requests.get(
                content_url,
                headers={'Authorization': self.auth_header},
                timeout=30,
                stream=True,
            )
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()

            if content_type in self._BLOCKED_TYPES:
                raise ValueError(
                    f"Attachment type '{content_type}' is blocked for security reasons."
                )

            # Read with size cap — stops download as soon as limit is exceeded.
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > self._MAX_ATTACHMENT_BYTES:
                    raise ValueError(
                        f"Attachment exceeds the {self._MAX_ATTACHMENT_BYTES // (1024*1024)} MB size limit."
                    )
                chunks.append(chunk)
            content = b''.join(chunks)

            # Validate magic bytes for known image types.
            magic_signatures = self._MAGIC_BYTES.get(content_type, [])
            if magic_signatures and not any(content.startswith(sig) for sig in magic_signatures):
                raise ValueError(
                    f"File header does not match declared content type '{content_type}'. "
                    "The attachment may be spoofed."
                )
            if content_type == 'image/webp' and content[8:12] != b'WEBP':
                raise ValueError("File header does not match declared content type 'image/webp'.")

            return {
                'data': base64.b64encode(content).decode('ascii'),
                'content_type': content_type,
            }
        except (ValueError, _requests.HTTPError):
            raise
        except Exception as e:
            raise Exception(f"Failed to fetch attachment from {content_url}: {str(e)}")

    def post_comment(self, ticket_id: int, comment: str, public: bool = True) -> str:
        """
        Post a comment to an existing ticket.
        """
        try:
            ticket = self.client.tickets(id=ticket_id)
            ticket.comment = Comment(
                html_body=comment,
                public=public
            )
            self.client.tickets.update(ticket)
            return comment
        except Exception as e:
            raise Exception(f"Failed to post comment on ticket {ticket_id}: {str(e)}")

    def get_tickets(self, page: int = 1, per_page: int = 25, sort_by: str = 'created_at', sort_order: str = 'desc') -> Dict[str, Any]:
        """
        Get the latest tickets with pagination support.
        """
        try:
            per_page = min(per_page, 100)
            data = self._api_get('tickets.json', {
                'page': str(page),
                'per_page': str(per_page),
                'sort_by': sort_by,
                'sort_order': sort_order,
            })

            ticket_list = [self._format_ticket(t) for t in data.get('tickets', [])]

            return {
                'tickets': ticket_list,
                'page': page,
                'per_page': per_page,
                'count': len(ticket_list),
                'sort_by': sort_by,
                'sort_order': sort_order,
                'has_more': data.get('next_page') is not None,
                'next_page': page + 1 if data.get('next_page') else None,
                'previous_page': page - 1 if data.get('previous_page') and page > 1 else None,
            }
        except Exception as e:
            raise Exception(f"Failed to get latest tickets: {str(e)}")

    def get_all_articles(self) -> Dict[str, Any]:
        """
        Fetch help center articles as knowledge base.
        Returns a Dict of section -> [article].
        """
        try:
            # Get all sections
            sections = self.client.help_center.sections()

            # Get articles for each section
            kb = {}
            for section in sections:
                articles = self.client.help_center.sections.articles(section.id)
                kb[section.name] = {
                    'section_id': section.id,
                    'description': section.description,
                    'articles': [{
                        'id': article.id,
                        'title': article.title,
                        'body': article.body,
                        'updated_at': str(article.updated_at),
                        'url': article.html_url
                    } for article in articles]
                }

            return kb
        except Exception as e:
            raise Exception(f"Failed to fetch knowledge base: {str(e)}")

    def create_ticket(
        self,
        subject: str,
        description: str,
        requester_id: int | None = None,
        assignee_id: int | None = None,
        priority: str | None = None,
        type: str | None = None,
        tags: List[str] | None = None,
        custom_fields: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """
        Create a new Zendesk ticket using Zenpy and return essential fields.

        Args:
            subject: Ticket subject
            description: Ticket description (plain text). Will also be used as initial comment.
            requester_id: Optional requester user ID
            assignee_id: Optional assignee user ID
            priority: Optional priority (low, normal, high, urgent)
            type: Optional ticket type (problem, incident, question, task)
            tags: Optional list of tags
            custom_fields: Optional list of dicts: {id: int, value: Any}
        """
        try:
            ticket = ZenpyTicket(
                subject=subject,
                description=description,
                requester_id=requester_id,
                assignee_id=assignee_id,
                priority=priority,
                type=type,
                tags=tags,
                custom_fields=custom_fields,
            )
            created_audit = self.client.tickets.create(ticket)
            # Fetch created ticket id from audit
            created_ticket_id = getattr(getattr(created_audit, 'ticket', None), 'id', None)
            if created_ticket_id is None:
                # Fallback: try to read id from audit events
                created_ticket_id = getattr(created_audit, 'id', None)

            # Fetch full ticket to return consistent data
            created = self.client.tickets(id=created_ticket_id) if created_ticket_id else None

            return {
                'id': getattr(created, 'id', created_ticket_id),
                'subject': getattr(created, 'subject', subject),
                'description': getattr(created, 'description', description),
                'status': getattr(created, 'status', 'new'),
                'priority': getattr(created, 'priority', priority),
                'type': getattr(created, 'type', type),
                'created_at': str(getattr(created, 'created_at', '')),
                'updated_at': str(getattr(created, 'updated_at', '')),
                'requester_id': getattr(created, 'requester_id', requester_id),
                'assignee_id': getattr(created, 'assignee_id', assignee_id),
                'organization_id': getattr(created, 'organization_id', None),
                'tags': list(getattr(created, 'tags', tags or []) or []),
            }
        except Exception as e:
            raise Exception(f"Failed to create ticket: {str(e)}")

    def get_macros(self, page: int = 1, per_page: int = 25, active_only: bool = True) -> Dict[str, Any]:
        """
        Fetch Zendesk macros (canned response templates) with pagination.
        """
        try:
            per_page = min(per_page, 100)
            endpoint = "macros/active.json" if active_only else "macros.json"
            data = self._api_get(endpoint, {
                'page': str(page),
                'per_page': str(per_page),
            })

            macro_list = []
            for macro in data.get('macros', []):
                macro_list.append({
                    'id': macro.get('id'),
                    'title': macro.get('title'),
                    'description': macro.get('description'),
                    'active': macro.get('active'),
                    'actions': macro.get('actions'),
                    'restriction': macro.get('restriction'),
                    'created_at': macro.get('created_at'),
                    'updated_at': macro.get('updated_at'),
                })

            return {
                'macros': macro_list,
                'page': page,
                'per_page': per_page,
                'count': len(macro_list),
                'has_more': data.get('next_page') is not None,
                'next_page': page + 1 if data.get('next_page') else None,
                'previous_page': page - 1 if data.get('previous_page') and page > 1 else None,
            }
        except Exception as e:
            raise Exception(f"Failed to get macros: {str(e)}")

    def search_tickets(self, query: str = '', status: str | None = None,
                       priority: str | None = None, assignee: str | None = None,
                       tags: str | None = None, created_after: str | None = None,
                       created_before: str | None = None,
                       page: int = 1, per_page: int = 25) -> Dict[str, Any]:
        """
        Search tickets using Zendesk Query Language.
        Convenience params are appended to the raw query string.
        """
        try:
            per_page = min(per_page, 100)
            parts = ['type:ticket']
            if query:
                parts.append(query)
            if status:
                parts.append(f'status:{status}')
            if priority:
                parts.append(f'priority:{priority}')
            if assignee:
                parts.append(f'assignee:{assignee}')
            if tags:
                parts.append(f'tags:{tags}')
            if created_after:
                parts.append(f'created>{created_after}')
            if created_before:
                parts.append(f'created<{created_before}')

            full_query = ' '.join(parts)
            data = self._api_get('search.json', {
                'query': full_query,
                'page': str(page),
                'per_page': str(per_page),
            })

            ticket_list = [self._format_ticket(t) for t in data.get('results', [])]

            return {
                'tickets': ticket_list,
                'query': full_query,
                'page': page,
                'per_page': per_page,
                'count': data.get('count', len(ticket_list)),
                'has_more': data.get('next_page') is not None,
                'next_page': page + 1 if data.get('next_page') else None,
            }
        except Exception as e:
            raise Exception(f"Failed to search tickets: {str(e)}")

    def get_user(self, user_id: int | None = None, query: str | None = None) -> Dict[str, Any]:
        """
        Get a user by ID or search by name/email.
        """
        try:
            if user_id is not None:
                data = self._api_get(f'users/{user_id}.json')
                user = data['user']
                return self._format_user(user)
            elif query:
                data = self._api_get('users/search.json', {'query': query})
                return {
                    'users': [self._format_user(u) for u in data.get('users', [])],
                    'count': data.get('count', 0),
                }
            else:
                raise ValueError("Either user_id or query is required")
        except Exception as e:
            raise Exception(f"Failed to get user: {str(e)}")

    @staticmethod
    def _format_ticket(ticket: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'id': ticket.get('id'),
            'subject': ticket.get('subject'),
            'status': ticket.get('status'),
            'priority': ticket.get('priority'),
            'description': ticket.get('description'),
            'created_at': ticket.get('created_at'),
            'updated_at': ticket.get('updated_at'),
            'requester_id': ticket.get('requester_id'),
            'assignee_id': ticket.get('assignee_id'),
            'tags': ticket.get('tags', []),
        }

    @staticmethod
    def _format_user(user: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'id': user.get('id'),
            'name': user.get('name'),
            'email': user.get('email'),
            'role': user.get('role'),
            'phone': user.get('phone'),
            'organization_id': user.get('organization_id'),
            'tags': user.get('tags', []),
            'created_at': user.get('created_at'),
            'updated_at': user.get('updated_at'),
            'last_login_at': user.get('last_login_at'),
        }

    def list_views(self) -> Dict[str, Any]:
        """
        List all views accessible to the current agent.
        """
        try:
            data = self._api_get('views.json')
            view_list = []
            for view in data.get('views', []):
                view_list.append({
                    'id': view.get('id'),
                    'title': view.get('title'),
                    'active': view.get('active'),
                    'position': view.get('position'),
                })
            return {'views': view_list, 'count': len(view_list)}
        except Exception as e:
            raise Exception(f"Failed to list views: {str(e)}")

    def get_view_tickets(self, view_id: int, page: int = 1, per_page: int = 25) -> Dict[str, Any]:
        """
        Get tickets matching a view.
        """
        try:
            per_page = min(per_page, 100)
            data = self._api_get(f'views/{view_id}/tickets.json', {
                'page': str(page),
                'per_page': str(per_page),
            })

            ticket_list = [self._format_ticket(t) for t in data.get('tickets', [])]

            return {
                'tickets': ticket_list,
                'view_id': view_id,
                'page': page,
                'per_page': per_page,
                'count': len(ticket_list),
                'has_more': data.get('next_page') is not None,
                'next_page': page + 1 if data.get('next_page') else None,
            }
        except Exception as e:
            raise Exception(f"Failed to get view tickets: {str(e)}")

    def preview_macro(self, ticket_id: int, macro_id: int) -> Dict[str, Any]:
        """
        Preview what a macro would do to a ticket WITHOUT applying it.
        """
        try:
            data = self._api_get(f'tickets/{ticket_id}/macros/{macro_id}/apply.json')
            result = data.get('result', {})
            ticket = result.get('ticket', {})
            comment = ticket.get('comment', {})
            return {
                'ticket_changes': {
                    'status': ticket.get('status'),
                    'priority': ticket.get('priority'),
                    'type': ticket.get('type'),
                    'assignee_id': ticket.get('assignee_id'),
                    'group_id': ticket.get('group_id'),
                    'tags': ticket.get('tags', []),
                    'custom_fields': ticket.get('custom_fields', []),
                },
                'comment': {
                    'body': comment.get('body'),
                    'html_body': comment.get('html_body'),
                    'public': comment.get('public'),
                },
            }
        except Exception as e:
            raise Exception(f"Failed to preview macro {macro_id} on ticket {ticket_id}: {str(e)}")

    def get_ticket_fields(self) -> Dict[str, Any]:
        """
        List all system and custom ticket fields.
        """
        try:
            data = self._api_get('ticket_fields.json')
            field_list = []
            for field in data.get('ticket_fields', []):
                entry = {
                    'id': field.get('id'),
                    'title': field.get('title'),
                    'type': field.get('type'),
                    'active': field.get('active'),
                    'required': field.get('required'),
                    'removable': field.get('removable'),
                }
                if field.get('custom_field_options'):
                    entry['options'] = [
                        {'name': o.get('name'), 'value': o.get('value')}
                        for o in field['custom_field_options']
                    ]
                elif field.get('system_field_options'):
                    entry['options'] = [
                        {'name': o.get('name'), 'value': o.get('value')}
                        for o in field['system_field_options']
                    ]
                field_list.append(entry)
            return {'ticket_fields': field_list, 'count': len(field_list)}
        except Exception as e:
            raise Exception(f"Failed to get ticket fields: {str(e)}")

    def list_groups(self) -> Dict[str, Any]:
        """
        List all agent groups.
        """
        try:
            data = self._api_get('groups.json')
            group_list = []
            for group in data.get('groups', []):
                group_list.append({
                    'id': group.get('id'),
                    'name': group.get('name'),
                    'description': group.get('description'),
                    'default': group.get('default'),
                    'created_at': group.get('created_at'),
                    'updated_at': group.get('updated_at'),
                })
            return {'groups': group_list, 'count': len(group_list)}
        except Exception as e:
            raise Exception(f"Failed to list groups: {str(e)}")

    def get_ticket_metrics(self, ticket_id: int) -> Dict[str, Any]:
        """
        Get metrics for a ticket (reply time, resolution time, etc.).
        """
        try:
            data = self._api_get(f'tickets/{ticket_id}/metrics.json')
            m = data.get('ticket_metric', {})
            return {
                'ticket_id': ticket_id,
                'reply_time_in_minutes': m.get('reply_time_in_minutes', {}).get('calendar'),
                'first_resolution_time_in_minutes': m.get('first_resolution_time_in_minutes', {}).get('calendar'),
                'full_resolution_time_in_minutes': m.get('full_resolution_time_in_minutes', {}).get('calendar'),
                'agent_wait_time_in_minutes': m.get('agent_wait_time_in_minutes', {}).get('calendar'),
                'requester_wait_time_in_minutes': m.get('requester_wait_time_in_minutes', {}).get('calendar'),
                'reopens': m.get('reopens'),
                'replies': m.get('replies'),
                'assignee_stations': m.get('assignee_stations'),
                'group_stations': m.get('group_stations'),
                'created_at': m.get('created_at'),
                'updated_at': m.get('updated_at'),
            }
        except Exception as e:
            raise Exception(f"Failed to get ticket metrics for {ticket_id}: {str(e)}")

    def manage_tags(self, ticket_id: int, action: str, tags: List[str]) -> Dict[str, Any]:
        """
        Add or remove tags on a ticket without replacing existing ones.
        """
        try:
            if action not in ('add', 'remove'):
                raise ValueError("action must be 'add' or 'remove'")
            method = 'PUT' if action == 'add' else 'DELETE'
            result = self._api_modify(f'tickets/{ticket_id}/tags.json', method=method, data={'tags': tags})
            current_tags = result.get('tags', [])
            return {
                'ticket_id': ticket_id,
                'action': action,
                'tags_modified': tags,
                'current_tags': current_tags,
            }
        except Exception as e:
            raise Exception(f"Failed to {action} tags on ticket {ticket_id}: {str(e)}")

    def update_ticket(self, ticket_id: int, **fields: Any) -> Dict[str, Any]:
        """
        Update a Zendesk ticket with provided fields using Zenpy.

        Supported fields include common ticket attributes like:
        subject, status, priority, type, assignee_id, requester_id,
        tags (list[str]), custom_fields (list[dict]), due_at, etc.
        """
        try:
            # Load the ticket, mutate fields directly, and update
            ticket = self.client.tickets(id=ticket_id)
            for key, value in fields.items():
                if value is None:
                    continue
                setattr(ticket, key, value)

            # This call returns a TicketAudit (not a Ticket). Don't read attrs from it.
            self.client.tickets.update(ticket)

            # Fetch the fresh ticket to return consistent data
            refreshed = self.client.tickets(id=ticket_id)

            return {
                'id': refreshed.id,
                'subject': refreshed.subject,
                'description': refreshed.description,
                'status': refreshed.status,
                'priority': refreshed.priority,
                'type': getattr(refreshed, 'type', None),
                'created_at': str(refreshed.created_at),
                'updated_at': str(refreshed.updated_at),
                'requester_id': refreshed.requester_id,
                'assignee_id': refreshed.assignee_id,
                'organization_id': refreshed.organization_id,
                'tags': list(getattr(refreshed, 'tags', []) or []),
            }
        except Exception as e:
            raise Exception(f"Failed to update ticket {ticket_id}: {str(e)}")