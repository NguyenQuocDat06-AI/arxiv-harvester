"""Build an explicitly partial dataset from verified Drive backup archives."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile

import pyarrow.parquet as pq

from src.crawler.drive_backup import CheckpointBackup, safe_name
from src.crawler.observations import save_observations
from src.crawler.records import base_id, merge_publications, merge_references
from src.crawler.storage import save_publications_parquet, save_references_parquet, export_to_course_spec
from src.crawler.validate_sources import audit_sources, validate_course_tables


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(downloads: Path, output: Path, inventory: Path) -> dict:
    if output.exists():
        raise FileExistsError('Use a new snapshot directory')
    listing = {row['name']: row for row in json.loads(inventory.read_text(encoding='utf-8'))}
    archives = []
    for path in downloads.glob('*.tar.gz'):
        record_bytes = path.with_name(path.name.removesuffix('.tar.gz') + '.json').read_bytes()
        record = json.loads(record_bytes)
        if digest(path.read_bytes()) != record['archive_sha256']:
            raise ValueError('Archive checksum mismatch: ' + path.name)
        CheckpointBackup._verify_archive(path)
        archives.append((record['created_at'], path, record))
    archives.sort()
    output.mkdir(parents=True)
    raw = output / 'raw'
    raw.mkdir()
    tables = output / 'm1'
    tables.mkdir()
    parts, source_records = {}, []
    state = {}
    for _, path, record in archives:
        with tarfile.open(path, 'r:gz') as archive:
            manifest = json.load(archive.extractfile('backup_manifest.json'))
            state_bytes = archive.extractfile('shard/_checkpoint/state.json').read()
            if digest(state_bytes) != record['checkpoint_sha256']:
                raise ValueError('Checkpoint checksum mismatch: ' + path.name)
            state = json.loads(state_bytes)
            for identifier in manifest['replace_raw_ids']:
                if not re.fullmatch(r'[A-Za-z0-9_.-]+',identifier) or identifier in {'.','..'}:
                    raise ValueError('Invalid paper ID in backup manifest')
                for folder in (raw / 'unzipped' / identifier,):
                    if not folder.resolve().is_relative_to(raw.resolve()) or folder.resolve() == raw.resolve():
                        raise ValueError('Invalid source replacement path')
                    if folder.exists():
                        shutil.rmtree(folder)
                manifests = raw / 'manifests'
                if manifests.exists():
                    for old in manifests.glob(identifier + 'v*.json'):
                        old.unlink()
            for member in archive.getmembers():
                if member.name == 'backup_manifest.json':
                    continue
                name = safe_name(member.name)
                if not member.isfile():
                    raise ValueError('Non-file archive member')
                payload = archive.extractfile(member).read()
                if member.name.startswith('raw/') and (name.suffix.lower() in {'.tex', '.bib', '.bbl'} or name.parts[1] == 'manifests'):
                    target = output.joinpath(*name.parts)
                    if not target.resolve().is_relative_to(raw.resolve()):
                        raise ValueError('Raw path escapes snapshot')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
                elif member.name.startswith('shard/_checkpoint/') and name.suffix == '.parquet':
                    parts[name.name] = payload
            source_records.append({'generation': record['generation'], 'created_at': record['created_at'],
                                   'archive_sha256': record['archive_sha256'],
                                   'manifest_sha256': digest(path.with_name(record['generation'] + '.json').read_bytes()),
                                   'drive_url': listing[path.name]['url'], 'bytes': path.stat().st_size})
    papers, references, statuses = {}, {}, {}
    for filename in sorted(parts, key=lambda x: (int(x.rsplit('_', 1)[1].split('.')[0]), x)):
        rows = pq.ParquetFile(io.BytesIO(parts[filename])).read().to_pylist()
        if filename.startswith('publications_'):
            for row in rows:
                key = base_id(row)
                papers[key] = merge_publications(papers.get(key), row)
        elif filename.startswith('statuses_'):
            for row in rows:
                statuses[row['arxiv_id']] = row
        elif filename.startswith('references_'):
            for row in rows:
                references.setdefault(base_id(row), []).append(row)
    # Replay reference replacement in checkpoint order, including empty replacements.
    references = {}
    batches = sorted({int(n.rsplit('_', 1)[1].split('.')[0]) for n in parts})
    for batch in batches:
        status_name = f'statuses_{batch:05d}.parquet'
        if status_name in parts:
            for row in pq.ParquetFile(io.BytesIO(parts[status_name])).read().to_pylist():
                if row.get('reference_update') == 'replace':
                    references[row['arxiv_id']] = []
        ref_name = f'references_{batch:05d}.parquet'
        if ref_name in parts:
            for row in pq.ParquetFile(io.BytesIO(parts[ref_name])).read().to_pylist():
                references.setdefault(base_id(row), []).append(row)
    ordered = [papers[key] for key in sorted(papers)]
    if not ordered:
        raise ValueError('Archives contain no publication records')
    save_publications_parquet(ordered, str(tables / 'publications.parquet'))
    save_references_parquet([row for key in sorted(papers) for row in merge_references(references.get(key, []))],
                            str(tables / 'references.parquet'))
    save_observations([statuses[key] for key in sorted(papers) if key in statuses], tables / 'crawl_status.parquet')
    export_to_course_spec(str(tables), str(output / 'course'))
    audit = audit_sources(str(tables / 'publications.parquet'), str(raw), str(output / 'source_audit.parquet'))
    shutil.copyfile(output / 'source_audit.parquet', tables / 'source_audit.parquet')
    validation = validate_course_tables(str(output / 'course'))
    report = {'snapshot_created_at_utc': datetime.now(timezone.utc).isoformat(), 'is_mock': False,
              'status': 'partial_snapshot', 'runtime_sec': None,
              'scope': f'Publication records from {len(archives)} selected incremental archives; not a full-chain restore.',
              'selection': f'{len(archives)} most recently modified archives under 8 MiB in the listed folder; selection by size/time, not parser success.',
              'member_id': '24120282', 'assigned_group_papers': 25000, 'assigned_member_papers': 5000,
              'papers': len(ordered), 'versions': sum(len(p.get('versions') or []) for p in ordered),
              'reference_status_counts': dict(Counter(statuses.get(p['id'], {}).get('reference_status', 'unknown') for p in ordered)),
              'source_audit': audit, 'course_validation': validation,
              'latest_checkpoint_counts': {key: deepcopy(value) for key, value in state.get('counts', {}).items() if key != 'failed_ids'},
              'latest_checkpoint_ids': len(state.get('done_ids', [])), 'archives': source_records,
              'limitations': ['Not all parent archives were downloaded; old reference edges absent from selected archives may be unavailable.',
                              'Snapshot preparation is not a crawler benchmark; saved Colab runs have separate scopes.',
                              'No API calls or source downloads were made to fill missing data.']}
    (output / 'snapshot.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    (tables / 'stats.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--downloads', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    result = prepare(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ('papers', 'versions', 'reference_status_counts', 'source_audit', 'course_validation')},ensure_ascii=True))
