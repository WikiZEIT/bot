# Copyright (C) 2026 Jakub T. Jankiewicz <https://jakub.jankiewicz.org/>
#
# This file is part of WikiZEIT Bot.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import re


def build_template_start_regex(names):
    """Regex that matches the OPENING of any of the given template names —
    `{{TemplateName` plus trailing whitespace. The closing `}}` is found via
    brace-counting (see `find_template_in_text`) so nested `{{...}}` inside
    params survive intact."""
    pattern = '|'.join(re.escape(n) for n in names)
    return re.compile(rf"\{{\{{\s*({pattern})\s*", flags=re.I)


def find_template_in_text(start_re, text, start_pos=0):
    """Find the next known-template invocation at or after `start_pos`,
    using brace-counting so nested `{{...}}` inside parameters survive.

    Returns `(template_name, params_text, start, end)` or `None`. The leading
    `|` (if any) is stripped from `params_text` so the result is exactly what
    sits between the first `|` and the closing `}}`."""
    m = start_re.search(text, start_pos)
    if not m:
        return None

    name = m.group(1)
    start = m.start()
    pos = m.end()
    depth = 1
    while pos < len(text):
        two = text[pos:pos + 2]
        if two == '{{':
            depth += 1
            pos += 2
        elif two == '}}':
            depth -= 1
            if depth == 0:
                end = pos + 2
                params_text = text[m.end():pos]
                if params_text.startswith('|'):
                    params_text = params_text[1:]
                return name, params_text, start, end
            pos += 2
        else:
            pos += 1
    return None  # unterminated invocation


_PLACEHOLDER_EQ = '\x00EQ\x00'
_PLACEHOLDER_PIPE = '\x00PIPE\x00'


def _mask_escapes(text):
    """Swap MediaWiki-style escapes for NUL-bracketed placeholders so the
    parser doesn't trip on the literal `=` / `|` they represent."""
    return (text
            .replace('{{=}}', _PLACEHOLDER_EQ)
            .replace('{{!}}', _PLACEHOLDER_PIPE))


def _unmask_escapes(text):
    return (text
            .replace(_PLACEHOLDER_EQ, '=')
            .replace(_PLACEHOLDER_PIPE, '|'))


def parse_params(params_str):
    """Split a template's params string on top-level `|`, then split each
    chunk on its first `=`. `|` and `=` are NOT treated as separators when
    they appear inside `{{...}}` or `[[...]]` — so an etykieta value like
    `<center>[[:commons:File:{{plik}}|{{data}}]]</center>` survives intact.

    Two MediaWiki-style escapes are recognized anywhere in the params string
    and replaced with their literal characters in the final key/value:
      `{{=}}` → `=`
      `{{!}}` → `|`
    So `attrybuty=mode{{=}}packed` yields `{"attrybuty": "mode=packed"}` and
    the `=` inside `{{=}}` is NOT mistaken for the key/value separator."""
    params = {}
    if not params_str:
        return params

    # Mask escapes first so {{=}} and {{!}} can't act as separators below.
    text = _mask_escapes(params_str)

    parts = []
    current = []
    depth_brace = 0
    depth_link = 0
    i = 0
    while i < len(text):
        two = text[i:i + 2]
        ch = text[i]
        if two == '{{':
            depth_brace += 1
            current.append(two)
            i += 2
        elif two == '}}':
            depth_brace = max(0, depth_brace - 1)
            current.append(two)
            i += 2
        elif two == '[[':
            depth_link += 1
            current.append(two)
            i += 2
        elif two == ']]':
            depth_link = max(0, depth_link - 1)
            current.append(two)
            i += 2
        elif ch == '|' and depth_brace == 0 and depth_link == 0:
            parts.append(''.join(current))
            current = []
            i += 1
        else:
            current.append(ch)
            i += 1
    if current:
        parts.append(''.join(current))

    for part in parts:
        if '=' not in part:
            continue
        key, value = part.split('=', 1)
        params[_unmask_escapes(key).strip()] = _unmask_escapes(value).strip()
    return params
