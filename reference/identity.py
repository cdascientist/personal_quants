#!/usr/bin/env python3
"""
Tachikoma Identity Injection System — v2

Live-loads identity from canonical reference files at:
  personal_quants/reference/agents/tachikoma.md
  personal_quants/reference/agents/liltachikoma.md

Both agents load their identity, iMessage config, and system settings
from here at startup. This is the single source of truth.

Usage:
  python3 identity.py tachikoma      → JSON for Tachikoma
  python3 identity.py liltachikoma   → JSON for LilTachikoma
  python3 identity.py all            → Full system config
  python3 identity.py shell          → Bash export statements
"""
import json, sys, os, re

REPO_DIR = os.path.expanduser('/root/.openclaw/workspace/personal_quants')
REF_TACHIKOMA = os.path.join(REPO_DIR, 'reference/agents/tachikoma.md')
REF_LILTACHIKOMA = os.path.join(REPO_DIR, 'reference/agents/liltachikoma.md')
REF_MASTER = os.path.join(REPO_DIR, 'reference/README.md')

# Required fields that MUST be present for each agent
REQUIRED_TACHIKOMA = ['from_number', 'c_number']
REQUIRED_LILTACHIKOMA = ['from_number', 'c_number']


def parse_imessage_table(content):
    """Parse markdown table cells under ### iMessage section."""
    start = content.find('### iMessage')
    if start == -1:
        return {}
    end = content.find('### ', start + 1)
    if end == -1:
        end = len(content)
    section = content[start:end]

    fields = {}
    for line in section.split('\n'):
        line = line.strip()
        if not line.startswith('|') or '---' in line:
            continue
        cells = [c.strip() for c in line.split('|') if c.strip()]
        if len(cells) >= 2:
            field = cells[0].replace('**', '').replace('*', '').strip()
            value = cells[1].replace('**', '').replace('`', '').strip()
            # Normalize field names to keys
            key_map = {
                'Account': 'account',
                'From number': 'from_number',
                "C's number": 'c_number',
                'API Key ID': 'api_key_id',
                'API Secret': 'api_secret',
                'Send script': 'send_script',
                'Balance check': 'balance_check',
                'Balance format': 'balance_format',
            }
            norm_key = key_map.get(field, field.lower().replace(' ', '_'))
            fields[norm_key] = value
    return fields


def get_agent_identity(agent='tachikoma'):
    """Return identity dict for specified agent, sourced from reference files."""
    ref_file = REF_TACHIKOMA if agent == 'tachikoma' else REF_LILTACHIKOMA
    try:
        with open(ref_file) as f:
            content = f.read()
    except FileNotFoundError:
        return {'error': f'Reference file not found: {ref_file}', 'ok': False}

    # Parse identity info from markdown
    identity = {
        'name': 'Tachikoma' if agent == 'tachikoma' else 'LilTachikoma',
        'emoji': '🕷️',
        'ref_file': ref_file,
        'ok': True,
    }

    # Extract iMessage config from the markdown table
    imessage = parse_imessage_table(content)
    # Only keep the config fields
    for key in ['from_number', 'c_number', 'api_key_id', 'api_secret', 'account']:
        if key in imessage:
            identity[key] = imessage[key]

    # Validate required fields
    required = REQUIRED_TACHIKOMA if agent == 'tachikoma' else REQUIRED_LILTACHIKOMA
    missing = [f for f in required if f not in identity]
    if missing:
        identity['ok'] = False
        identity['error'] = f'Missing required fields: {missing}'

    return identity


def get_all_config():
    """Return full system configuration from all reference files."""
    config = {
        'tachikoma': get_agent_identity('tachikoma'),
        'liltachikoma': get_agent_identity('liltachikoma'),
        'references': {
            'master': REF_MASTER,
            'tachikoma': REF_TACHIKOMA,
            'liltachikoma': REF_LILTACHIKOMA,
            'directory': os.path.dirname(REF_TACHIKOMA),
        }
    }
    return config


def shell_format():
    """Output shell-compatible export statements."""
    t = get_agent_identity('tachikoma')
    l = get_agent_identity('liltachikoma')
    ref_dir = os.path.dirname(REF_TACHIKOMA)
    print(f'export TACHIKOMA_FROM="{t.get("from_number", "+17862847802")}"')
    print(f'export TACHIKOMA_C="{t.get("c_number", "+13035132698")}"')
    print(f'export LILTACHIKOMA_FROM="{l.get("from_number", "+17862847802")}"')
    print(f'export LILTACHIKOMA_C="{l.get("c_number", "+13035132698")}"')
    print(f'export AGENT_REF_DIR="{ref_dir}"')
    print(f'export AGENT_SOURCE="personal_quants/reference/identity.py"')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    commands = {
        'tachikoma': lambda: print(json.dumps(get_agent_identity('tachikoma'), indent=2)),
        'liltachikoma': lambda: print(json.dumps(get_agent_identity('liltachikoma'), indent=2)),
        'all': lambda: print(json.dumps(get_all_config(), indent=2)),
        'shell': shell_format,
    }
    fn = commands.get(cmd, lambda: print(f'Usage: {sys.argv[0]} [tachikoma|liltachikoma|all|shell]'))
    fn()
