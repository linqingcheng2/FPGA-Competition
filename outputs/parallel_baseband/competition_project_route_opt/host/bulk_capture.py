"""Validate tagged ILA chunks before publishing compatibility spectrum/scope files."""
from pathlib import Path
import csv, hashlib, json, re, sys

NAMES = ('transfer_valid', 'transfer_data', 'transfer_tag', 'transfer_scope_kind')

def read_chunk(path, base, kind):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream)
        headers = next(reader)
        columns = []
        metadata=Path(path).parent/'transfer_ports.json'
        names=json.loads(metadata.read_text()) if metadata.exists() else {}
        for role, fallback in enumerate(NAMES):
            name=names.get(str(role), fallback)
            matches = [i for i, h in enumerate(headers) if re.search(rf'{re.escape(name)}(?:\[|$)', h)]
            if len(matches) != 1:
                raise ValueError(f'Missing or ambiguous transfer port: {name}; {headers}')
            columns.append(matches[0])
        values = []
        for row in reader:
            if not row:
                continue
            try:
                valid, data, tag, source = [int(row[c].strip().removeprefix('0x'), 16) for c in columns]
            except (ValueError, IndexError):
                continue  # Vivado's radix row; completeness checked below.
            if valid != 1 or source != kind or tag != base + len(values):
                raise ValueError(f'Incomplete, reordered or mixed transfer at {path}: {tag}')
            if not 0 <= data < (1 << (24 if kind else 30)):
                raise ValueError('Invalid transfer data width')
            values.append(data)
        if len(values) != 2048:
            raise ValueError(f'Incomplete chunk: {len(values)}/2048 samples')
        return values

def convert(folder, n, frame, exponent, scope):
    folder = Path(folder)
    powers = []
    chunks = []
    for base in range(0, n, 2048):
        path = folder / f'transfer_spectrum_{base:05d}.csv'
        powers.extend(read_chunk(path, base, 0))
        chunks.append(dict(base=base, count=2048, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    snapshots = None
    if scope:
        snapshots = read_chunk(folder/'transfer_scope.csv', 0, 1)
        if snapshots[:1024] != snapshots[1024:]:
            raise ValueError('Frozen I/Q snapshot changed between duplicate reads')
    pending = folder/'spectrum.pending.csv'
    with pending.open('w', encoding='ascii', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow([f'cp_ila{i}' for i in range(7)])
        writer.writerows((1, f'{powers[i]:x}', f'{powers[i+1]:x}', f'{i:x}', '0', f'{frame:x}', f'{exponent:x}') for i in range(0, n, 2))
    if snapshots is not None:
        scope_pending = folder/'scope.csv.pending'
        with scope_pending.open('w', encoding='ascii', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(('index', 'iq_hex'))
            writer.writerows((i, f'{value:06x}') for i, value in enumerate(snapshots[:1024]))
        scope_pending.replace(folder/'scope.csv')
    pending.replace(folder/'ila.csv')
    (folder/'spectrum_transport.json').write_text(json.dumps(dict(source='tagged_chunked_ila_frozen_ram', samples=n,
        words_per_transaction=2048, frame=frame, block_exponent=exponent, chunks=chunks,
        all_tags_checked=True, scope_duplicate_checked=bool(scope)), indent=2), encoding='utf-8')

if __name__ == '__main__':
    convert(sys.argv[1], *map(int, sys.argv[2:]))
