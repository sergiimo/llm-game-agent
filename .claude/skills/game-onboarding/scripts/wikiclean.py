"""Convert MediaWiki wikitext (Wylde Flowers fandom dump) into compact plain text/markdown."""
import re
import sys

def _link(m):
    inner = m.group(1)
    if re.match(r'(?i)(file|image|category):', inner):
        return ''
    parts = inner.split('|')
    return parts[-1] if len(parts) > 1 and parts[-1] else parts[0]

def _template(body):
    """Render a template body (without braces) as compact text."""
    parts = [p.strip() for p in body.split('|')]
    name = parts[0].strip()
    lname = name.lower()
    if lname in ('stub', 'clear', '-', '!', 'reflist') or lname.startswith('#ev'):
        return ''
    if lname.startswith('needs') or lname.startswith('spoiler'):
        return ''
    kv = []
    pos = []
    for p in parts[1:]:
        if '=' in p:
            k, v = p.split('=', 1)
            v = v.strip()
            if v and not re.match(r'(?i).*\.(png|jpg|jpeg|gif|webp)$', v):
                kv.append(f'{k.strip()}: {v}')
        elif p:
            pos.append(p)
    if kv:
        return f'\n[{name}]\n' + '\n'.join('  ' + x for x in kv) + '\n'
    if pos:
        return ' '.join(pos)
    return name

def clean(text):
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    text = text.replace('{{!}}', '|')
    # unwrap parser-function wrappers such as {{#ifeq:{{{1}}}|Crops| ... }}
    text = re.sub(r'\{\{#if(?:eq)?:(?:\{\{\{[^}]*\}\}\}|[^|\n])*\|[^|\n]*\|', '', text)
    text = re.sub(r'<ref[^>]*/>', '', text)
    text = re.sub(r'<ref[^>]*>.*?</ref>', '', text, flags=re.S)
    text = re.sub(r'<gallery.*?</gallery>', '', text, flags=re.S | re.I)
    text = re.sub(r'<br\s*/?>', '; ', text)
    text = re.sub(r'</?(small|center|span|div|big|references|u|s|tabber|onlyinclude|includeonly|noinclude)[^>]*>', '', text, flags=re.I)
    text = re.sub(r'\[\[(?:File|Image):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]', '', text, flags=re.I)
    text = re.sub(r'\[\[([^\[\]]*)\]\]', _link, text)
    text = re.sub(r'\[https?://\S+ ([^\]]+)\]', r'\1', text)
    # templates, innermost first
    for _ in range(6):
        new = re.sub(r'\{\{([^{}]*)\}\}', lambda m: _template(m.group(1)), text)
        if new == text:
            break
        text = new
    text = re.sub(r"'''?", '', text)
    text = re.sub(r'^(=+)\s*(.*?)\s*\1\s*$', lambda m: '#' * len(m.group(1)) + ' ' + m.group(2), text, flags=re.M)
    # tables -> pipe rows
    out = []
    row = []
    for line in text.split('\n'):
        s = line.strip()
        if s.startswith('{|'):
            row = []
            continue
        if s.startswith('|}') or s.startswith('|-') or s.startswith('|+'):
            if row:
                out.append('| ' + ' | '.join(row) + ' |')
                row = []
            if s.startswith('|+'):
                out.append(s[2:].strip())
            continue
        if s.startswith('!') or (s.startswith('|') and not s.startswith('||')):
            cells = re.split(r'\s*(?:\|\||!!)\s*', s[1:])
            for c in cells:
                if '|' in c and not c.startswith('['):
                    attr, _, val = c.partition('|')
                    if '=' in attr or 'style' in attr:
                        c = val
                row.append(c.strip())
            continue
        if row:
            out.append('| ' + ' | '.join(row) + ' |')
            row = []
        out.append(line)
    if row:
        out.append('| ' + ' | '.join(row) + ' |')
    text = '\n'.join(out)
    text = re.sub(r'^\s*\}\}\s*$', '', text, flags=re.M)
    text = re.sub(r'__[A-Z]+__', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + '\n'

if __name__ == '__main__':
    for path in sys.argv[1:]:
        sys.stdout.write(clean(open(path, encoding='utf-8').read()))
