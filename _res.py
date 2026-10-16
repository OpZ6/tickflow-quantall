import re, sys
MARK = re.compile(r'<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n', re.S)
def resolve(path, choices):
    s = open(path, encoding='utf-8').read()
    matches = list(MARK.finditer(s))
    if len(matches) != len(choices):
        print(f'!! {path}: 冲突数 {len(matches)} != 选择数 {len(choices)}'); return False
    out, last = [], 0
    for m, c in zip(matches, choices):
        out.append(s[last:m.start()])
        out.append({'O': m.group(1), 'T': m.group(2), 'B': m.group(1) + m.group(2)}[c])
        last = m.end()
    out.append(s[last:])
    open(path, 'w', encoding='utf-8').write(''.join(out))
    return True
if __name__ == '__main__':
    p = sys.argv[1]; c = sys.argv[2].split(',')
    ok = resolve(p, c)
    print(('OK ' if ok else 'FAIL ') + f'{p} <- {c}')
