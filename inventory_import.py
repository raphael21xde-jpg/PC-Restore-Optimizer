"""Read-only, version-aware discovery JSON import with helpful diagnostics.

No filesystem scan, preference merge, or destructive operation is performed.
The caller owns cache merging; older results must be labeled historical.
"""
from __future__ import annotations
import json
from pathlib import Path
from scan_sessions import cache_from_saved

MAX_REPORT_BYTES = 75 * 1024 * 1024


def explain_document(data):
    if not isinstance(data, dict):
        return 'JSON de outro tipo (esperado objeto).'
    schema = data.get('schema')
    if schema == 'pcro-discovery-v1':
        return 'Inventário de varredura PCRO'
    if schema == 'pcro-preservation-dry-run-v1':
        return 'Plano de preservação (não contém inventário para importar)'
    if 'choices' in data and 'catalog_choices' in data:
        return 'Preferências e decisões de preservação (preferencias-v05.json)'
    if schema:
        return 'Relatório de tipo ' + str(schema)[:70]
    return 'JSON não reconhecido como inventário PCRO'


def read_inventory(path):
    source = Path(path)
    if source.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError('Inventário maior que 75 MB; não foi carregado. Escolha o arquivo de detecção original.')
    try:
        data = json.loads(source.read_text(encoding='utf-8-sig'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('O arquivo não é um JSON de inventário válido: ' + str(exc)) from exc
    if not isinstance(data, dict) or data.get('schema') != 'pcro-discovery-v1':
        raise ValueError('Arquivo selecionado: ' + explain_document(data) + '\n\n'
            'Para inventários, use deteccao-detalhada-v063.json ou '
            'deteccao-detalhada-v064.json da pasta antiga.\n'
            'Para preferencias-v05.json, use Preservação > Importar escolhas.')
    records = data.get('records')
    if not isinstance(records, list) or any(
        not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in
            ('path', 'app_id', 'app', 'kind', 'evidence')) for row in records):
        raise ValueError('Inventário incompatível: registros sem identificação/caminho. Nada foi importado.')
    if not isinstance(data.get('roots'), list):
        raise ValueError('Inventário sem lista de unidades examinadas. Nada foi importado.')
    imported = cache_from_saved(data)
    if not imported:
        raise ValueError('Inventário sem unidades identificáveis. Nenhuma seleção foi alterada.')
    return imported
