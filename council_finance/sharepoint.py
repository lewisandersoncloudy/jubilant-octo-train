"""
SharePoint document storage via Microsoft Graph API.

Required environment variables:
  SHAREPOINT_TENANT_ID     — Azure AD tenant ID
  SHAREPOINT_CLIENT_ID     — App registration client ID
  SHAREPOINT_CLIENT_SECRET — App registration client secret
  SHAREPOINT_SITE_URL      — e.g. https://yourorg.sharepoint.com/sites/council

Optional:
  SHAREPOINT_LIBRARY       — Document library (default: Shared Documents)
  SHAREPOINT_FOLDER        — Base folder path (default: Council Finance/Documents)
"""
import os
import re
import requests
from functools import lru_cache

GRAPH_BASE = 'https://graph.microsoft.com/v1.0'
TOKEN_URL = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'tiff', 'docx', 'xlsx', 'msg'}
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB


def is_configured():
    return all([
        os.environ.get('SHAREPOINT_TENANT_ID'),
        os.environ.get('SHAREPOINT_CLIENT_ID'),
        os.environ.get('SHAREPOINT_CLIENT_SECRET'),
        os.environ.get('SHAREPOINT_SITE_URL'),
    ])


def _get_token():
    tenant = os.environ['SHAREPOINT_TENANT_ID']
    resp = requests.post(
        TOKEN_URL.format(tenant=tenant),
        data={
            'grant_type': 'client_credentials',
            'client_id': os.environ['SHAREPOINT_CLIENT_ID'],
            'client_secret': os.environ['SHAREPOINT_CLIENT_SECRET'],
            'scope': 'https://graph.microsoft.com/.default',
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()['access_token']


def _auth_headers(token):
    return {'Authorization': f'Bearer {token}'}


def _get_site_id(token):
    site_url = os.environ['SHAREPOINT_SITE_URL'].rstrip('/')
    # site_url: https://tenant.sharepoint.com/sites/sitename
    parts = site_url.split('/', 3)
    hostname = parts[2]
    site_path = '/' + parts[3] if len(parts) > 3 else '/'
    resp = requests.get(
        f'{GRAPH_BASE}/sites/{hostname}:{site_path}',
        headers=_auth_headers(token),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()['id']


def _sanitize(s, max_len=40):
    """Make a string safe for use in a filename."""
    s = re.sub(r'[^\w\s-]', '', str(s))
    s = re.sub(r'[\s_]+', '-', s.strip())
    return s[:max_len].strip('-')


def build_filename(transaction, original_filename):
    """
    Standardised naming convention:
    YYYY-MM-DD_REF_PAYEE_DESCRIPTION.ext
    e.g. 2025-06-15_BACS-001_AVDC_Annual-Precept-2025-26.pdf
    """
    ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else 'pdf'
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f'File type .{ext} is not allowed. Permitted: {", ".join(sorted(ALLOWED_EXTENSIONS))}')

    date_str = transaction.date.strftime('%Y-%m-%d')
    ref = _sanitize(transaction.reference, 20)
    payee = _sanitize(transaction.payee_payer, 30)
    desc = _sanitize(transaction.description, 35)
    return f'{date_str}_{ref}_{payee}_{desc}.{ext}'


def upload_document(transaction, file_bytes, original_filename):
    """
    Upload a document to SharePoint.
    Returns (web_url, stored_filename).
    Raises on any failure.
    """
    if not is_configured():
        raise RuntimeError(
            'SharePoint is not configured. Set SHAREPOINT_TENANT_ID, '
            'SHAREPOINT_CLIENT_ID, SHAREPOINT_CLIENT_SECRET, and SHAREPOINT_SITE_URL.'
        )

    if len(file_bytes) > MAX_FILE_BYTES:
        raise ValueError(f'File exceeds maximum size of {MAX_FILE_BYTES // (1024*1024)} MB.')

    filename = build_filename(transaction, original_filename)
    library = os.environ.get('SHAREPOINT_LIBRARY', 'Shared Documents')
    base_folder = os.environ.get('SHAREPOINT_FOLDER', 'Council Finance/Documents')
    fy_label = transaction.financial_year.label.replace('/', '-')
    upload_path = f'{library}/{base_folder}/{fy_label}/{filename}'

    token = _get_token()
    site_id = _get_site_id(token)

    url = f'{GRAPH_BASE}/sites/{site_id}/drive/root:/{upload_path}:/content'
    resp = requests.put(
        url,
        headers={**_auth_headers(token), 'Content-Type': 'application/octet-stream'},
        data=file_bytes,
        timeout=60,
    )
    resp.raise_for_status()
    web_url = resp.json().get('webUrl', '')
    return web_url, filename


def delete_document(transaction):
    """Delete the SharePoint document linked to a transaction (on void)."""
    if not transaction.document_url or not is_configured():
        return

    try:
        token = _get_token()
        site_id = _get_site_id(token)
        library = os.environ.get('SHAREPOINT_LIBRARY', 'Shared Documents')
        base_folder = os.environ.get('SHAREPOINT_FOLDER', 'Council Finance/Documents')
        fy_label = transaction.financial_year.label.replace('/', '-')
        filename = transaction.document_filename or ''
        item_path = f'{library}/{base_folder}/{fy_label}/{filename}'

        url = f'{GRAPH_BASE}/sites/{site_id}/drive/root:/{item_path}'
        requests.delete(url, headers=_auth_headers(token), timeout=15)
        # Don't raise — deletion failure should not block the void
    except Exception:
        pass
