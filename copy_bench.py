"""P2-10: medição de cópia com hardware real (sem Tk, sem imports do projeto).

O que faz: escolhe uma amostra de arquivos de uma pasta de origem, copia essa
amostra para uma pasta NOVA de medição e mede, para cada tamanho de bloco,
a velocidade de leitura, de escrita e de conferência (SHA-256). No fim,
sugere o tamanho de bloco mais rápido.

Regras de segurança (P2-10, escolhas mais seguras):
- a origem só é aberta com ``"rb"``; links simbólicos, junções e outros
  pontos de nova análise (reparse points) são pulados, nunca seguidos;
- só grava dentro de uma pasta nova ``PCRO-MEDICAO-AAAAMMDD-HHMMSS`` criada
  com ``os.mkdir`` (se o nome existir, tenta ``-2``, ``-3``...); cada cópia é
  aberta com ``"xb"`` (nunca grava por cima);
- recusa destino que é link, destino dentro da origem, origem dentro do
  destino e espaço livre menor que (amostra x tamanhos de bloco) + 2 GiB;
- NADA é apagado, nem a pasta de medição; o relatório diz o tamanho dela e
  que ela pode ser apagada à mão;
- os relatórios não têm caminhos: só a letra da unidade, quantidades,
  tamanhos e velocidades;
- nenhuma consulta de hardware nem PowerShell.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as _dt
import hashlib
import json
import ntpath
import os
import shutil
import stat as _stat
import time

MIB = 1024 * 1024
GIB = 1024 * MIB
DEFAULT_CHUNKS_MIB = (1, 4, 8)
DEFAULT_MAX_BYTES = GIB
DEFAULT_MAX_FILES = 5000
DEFAULT_MAX_SCAN = 200_000
SPACE_MARGIN = 2 * GIB
MAX_CHUNK_MIB = 256
FOLDER_PREFIX = 'PCRO-MEDICAO-'
MAX_FOLDER_TRIES = 50
REFERENCE_GIB = 120  # tamanho de referência para a estimativa (jogos grandes)
_REPARSE = getattr(_stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


class BenchRefused(ValueError):
    """A medição foi recusada antes de gravar qualquer coisa."""


@dataclass
class Sample:
    files: list = field(default_factory=list)  # [(caminho, tamanho)]
    total_bytes: int = 0
    skipped_links: int = 0
    unreadable: int = 0
    too_big: int = 0
    truncated: bool = False
    cancelled: bool = False


@dataclass
class RoundResult:
    chunk_mib: int
    files_ok: int = 0
    bytes: int = 0
    read_s: float = 0.0
    write_s: float = 0.0
    verify_s: float = 0.0
    mismatches: int = 0
    errors: int = 0
    complete: bool = False

    @property
    def read_mib_s(self):
        return mib_per_s(self.bytes, self.read_s)

    @property
    def write_mib_s(self):
        return mib_per_s(self.bytes, self.write_s)

    @property
    def verify_mib_s(self):
        return mib_per_s(self.bytes, self.verify_s)

    @property
    def copy_mib_s(self):
        return mib_per_s(self.bytes, self.read_s + self.write_s)

    @property
    def total_mib_s(self):
        return mib_per_s(self.bytes, self.read_s + self.write_s + self.verify_s)


@dataclass
class BenchResult:
    status: str  # 'concluída' ou 'interrompida'
    folder_name: str
    source_drive: str
    dest_drive: str
    sample: Sample
    chunks_mib: tuple
    rounds: list = field(default_factory=list)
    written_bytes: int = 0
    suggestion: dict = field(default_factory=dict)
    date: str = ''


def mib_per_s(nbytes, seconds):
    """MiB por segundo; ``None`` quando não houve tempo medido."""
    if not seconds or seconds <= 0:
        return None
    return nbytes / MIB / seconds


def drive_label(path):
    """Só a letra da unidade (``C:``), ``rede`` ou ``sem letra``; nunca o caminho."""
    drive, _ = ntpath.splitdrive(str(path))
    if len(drive) == 2 and drive[1] == ':' and drive[0].isalpha():
        return drive.upper()
    if drive.startswith(('\\\\', '//')):
        return 'rede'
    return 'sem letra'


def _is_cancelled(cancelled):
    if cancelled is None:
        return False
    is_set = getattr(cancelled, 'is_set', None)
    if callable(is_set):
        return bool(is_set())
    return bool(cancelled())


def _is_link_entry(entry):
    try:
        if entry.is_symlink():
            return True
        is_junction = getattr(entry, 'is_junction', None)
        if callable(is_junction) and is_junction():
            return True
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return True  # na dúvida, não segue
    return bool(getattr(info, 'st_file_attributes', 0) & _REPARSE)


def _is_link_path(path):
    if os.path.islink(path):
        return True
    isjunction = getattr(os.path, 'isjunction', None)
    if callable(isjunction) and isjunction(path):
        return True
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(info, 'st_file_attributes', 0) & _REPARSE)


def pick_sample(origem, max_bytes=DEFAULT_MAX_BYTES, max_files=DEFAULT_MAX_FILES,
                cancelled=None, *, max_scan=DEFAULT_MAX_SCAN):
    """Escolhe arquivos da origem em ordem estável (nome), sem seguir links.

    Para no primeiro arquivo que passaria do limite de bytes ou de arquivos
    (``truncated``). Arquivo sozinho maior que ``max_bytes`` fica de fora
    (``too_big``). Só lista pastas; não abre nenhum arquivo.
    """
    sample = Sample()
    stack = [str(origem)]
    scanned = 0
    while stack:
        if _is_cancelled(cancelled):
            sample.cancelled = True
            break
        folder = stack.pop()
        try:
            with os.scandir(folder) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError:
            sample.unreadable += 1
            continue
        subfolders = []
        for entry in entries:
            scanned += 1
            if scanned > max_scan:
                sample.truncated = True
                return sample
            if _is_link_entry(entry):
                sample.skipped_links += 1
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    subfolders.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                sample.unreadable += 1
                continue
            if size > max_bytes:
                sample.too_big += 1
                continue
            if (len(sample.files) >= max_files
                    or sample.total_bytes + size > max_bytes):
                sample.truncated = True
                return sample
            sample.files.append((entry.path, size))
            sample.total_bytes += size
        stack.extend(reversed(subfolders))
    return sample


def _real(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _inside(child, parent):
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


def _check_paths(origem, destino_pai):
    if not os.path.isdir(origem):
        raise BenchRefused('A pasta de origem não existe ou não é uma pasta.')
    if _is_link_path(origem):
        raise BenchRefused('A origem é um atalho (link ou junção). '
                           'Escolha a pasta verdadeira.')
    if not os.path.isdir(destino_pai):
        raise BenchRefused('A pasta de destino não existe ou não é uma pasta.')
    if _is_link_path(destino_pai):
        raise BenchRefused('O destino é um atalho (link ou junção). '
                           'Escolha a pasta verdadeira.')
    real_origem = _real(origem)
    real_destino = _real(destino_pai)
    if _inside(real_destino, real_origem):
        raise BenchRefused('O destino fica dentro da origem (ou é a mesma pasta). '
                           'Escolha um destino fora da pasta medida.')
    if _inside(real_origem, real_destino):
        raise BenchRefused('A origem fica dentro do destino. '
                           'Escolha um destino fora da pasta medida.')


def _check_chunks(chunks):
    chunks = tuple(chunks)
    if not chunks:
        raise BenchRefused('Informe pelo menos um tamanho de bloco.')
    for value in chunks:
        if not isinstance(value, int) or not 1 <= value <= MAX_CHUNK_MIB:
            raise BenchRefused('Tamanho de bloco inválido: use de 1 a %d MiB.'
                               % MAX_CHUNK_MIB)
    return chunks


def _make_folder(destino_pai, moment):
    base = FOLDER_PREFIX + moment.strftime('%Y%m%d-%H%M%S')
    for attempt in range(1, MAX_FOLDER_TRIES + 1):
        name = base if attempt == 1 else '%s-%d' % (base, attempt)
        try:
            os.mkdir(os.path.join(destino_pai, name))
        except FileExistsError:
            continue
        return name
    raise BenchRefused('Já existem pastas de medição demais com esse horário. '
                       'Tente de novo daqui a pouco.')


def _copy_one(source, target, size, chunk, clock, cancelled, round_):
    """Copia um arquivo bloco a bloco. Devolve (sha256, bytes) ou None se cancelado."""
    digest = hashlib.sha256()
    copied = 0
    partial = target + '.parcial'
    with open(source, 'rb') as reader, open(partial, 'xb') as writer:
        remaining = size
        synced = False
        while remaining > 0:
            if _is_cancelled(cancelled):
                return None
            start = clock()
            data = reader.read(min(chunk, remaining))
            round_.read_s += clock() - start
            if not data:
                break
            digest.update(data)
            remaining -= len(data)
            start = clock()
            writer.write(data)
            if remaining <= 0:
                writer.flush()
                os.fsync(writer.fileno())
                synced = True
            round_.write_s += clock() - start
            copied += len(data)
        if not synced:
            writer.flush()
            os.fsync(writer.fileno())
    os.rename(partial, target)
    return digest.hexdigest(), copied


def _verify_one(target, copied, chunk, clock, round_):
    digest = hashlib.sha256()
    with open(target, 'rb') as reader:
        remaining = copied
        while remaining > 0:
            start = clock()
            data = reader.read(min(chunk, remaining))
            if data:
                digest.update(data)
            round_.verify_s += clock() - start
            if not data:
                break
            remaining -= len(data)
    return digest.hexdigest()


def _suggest(rounds):
    complete = [r for r in rounds if r.complete and r.bytes and r.total_mib_s]
    if not complete:
        return {'bloco_mib': None,
                'texto': 'Sem dados suficientes para sugerir uma estratégia.'}
    best = complete[0]
    for candidate in complete[1:]:
        if candidate.total_mib_s > best.total_mib_s:
            best = candidate
    read_speed = best.read_mib_s or 0.0
    write_speed = best.write_mib_s or 0.0
    bottleneck = 'escrita (disco de destino)' if write_speed < read_speed \
        else 'leitura (disco de origem)'
    minutes = REFERENCE_GIB * 1024 / best.total_mib_s / 60
    text = ('Use blocos de %d MiB, copiando um arquivo por vez e conferindo '
            'cada cópia. O ponto mais lento foi a %s. Com essa velocidade, '
            '%d GiB (um jogo grande) levariam cerca de %s, contando a '
            'conferência.' % (best.chunk_mib, bottleneck, REFERENCE_GIB,
                              _duration(minutes)))
    return {'bloco_mib': best.chunk_mib,
            'mib_s_com_conferencia': round(best.total_mib_s, 2),
            'gargalo': bottleneck,
            'minutos_para_%d_gib' % REFERENCE_GIB: round(minutes, 1),
            'texto': text}


def _duration(minutes):
    if minutes < 1:
        return 'menos de 1 minuto'
    if minutes < 90:
        return '%d minutos' % round(minutes)
    return '%.1f horas' % (minutes / 60)


def run_bench(origem, destino_pai, *, chunks=DEFAULT_CHUNKS_MIB,
              max_bytes=DEFAULT_MAX_BYTES, max_files=DEFAULT_MAX_FILES,
              usage=shutil.disk_usage, clock=time.monotonic, cancelled=None,
              now=None):
    """Mede a cópia da amostra para uma pasta nova dentro de ``destino_pai``.

    Levanta ``BenchRefused`` (sem gravar nada) se algo não for seguro.
    Ctrl+C ou ``cancelled`` param no próximo bloco: o arquivo pela metade
    fica como ``.parcial`` e o relatório diz "interrompida".
    """
    origem = str(origem)
    destino_pai = str(destino_pai)
    chunks = _check_chunks(chunks)
    _check_paths(origem, destino_pai)
    sample = pick_sample(origem, max_bytes, max_files, cancelled)
    if sample.cancelled:
        raise BenchRefused('Medição cancelada antes de começar. Nada foi gravado.')
    if not sample.files:
        raise BenchRefused('Nenhum arquivo para medir na origem '
                           '(links e arquivos grandes demais ficam de fora).')
    needed = sample.total_bytes * len(chunks) + SPACE_MARGIN
    free = usage(destino_pai).free
    if free < needed:
        raise BenchRefused(
            'Espaço livre insuficiente no destino: a medição precisa de %s '
            '(amostra para cada tamanho de bloco + 2 GiB de folga) e há %s livres.'
            % (_size(needed), _size(free)))
    moment = (now or _dt.datetime.now)()
    folder_name = _make_folder(destino_pai, moment)
    folder = os.path.join(destino_pai, folder_name)
    result = BenchResult(status='concluída', folder_name=folder_name,
                         source_drive=drive_label(_abs(origem)),
                         dest_drive=drive_label(_abs(destino_pai)),
                         sample=sample, chunks_mib=chunks,
                         date=moment.strftime('%Y-%m-%d %H:%M'))
    try:
        for chunk_mib in chunks:
            round_ = RoundResult(chunk_mib=chunk_mib)
            result.rounds.append(round_)
            round_folder = os.path.join(folder, 'bloco-%dMiB' % chunk_mib)
            os.mkdir(round_folder)
            for index, (source, size) in enumerate(sample.files, start=1):
                if _is_cancelled(cancelled):
                    result.status = 'interrompida'
                    break
                target = os.path.join(round_folder, '%05d.bin' % index)
                try:
                    copied = _copy_one(source, target, size, chunk_mib * MIB,
                                       clock, cancelled, round_)
                except OSError:
                    round_.errors += 1
                    continue
                if copied is None:
                    result.status = 'interrompida'
                    break
                expected, nbytes = copied
                result.written_bytes += nbytes
                try:
                    actual = _verify_one(target, nbytes, chunk_mib * MIB, clock, round_)
                except OSError:
                    round_.errors += 1
                    continue
                if actual != expected:
                    round_.mismatches += 1
                    continue
                round_.files_ok += 1
                round_.bytes += nbytes
            if result.status == 'interrompida':
                break
            round_.complete = True
    except KeyboardInterrupt:
        result.status = 'interrompida'
    result.written_bytes += _partial_bytes(folder)
    result.suggestion = _suggest(result.rounds)
    text, data = bench_report(result)
    _write_new(os.path.join(folder, 'relatorio.txt'), text)
    _write_new(os.path.join(folder, 'relatorio.json'),
               json.dumps(data, ensure_ascii=False, indent=2))
    return result


def _abs(path):
    return os.path.abspath(path)


def _partial_bytes(folder):
    total = 0
    for current, _dirs, files in os.walk(folder):
        for name in files:
            if name.endswith('.parcial'):
                try:
                    total += os.lstat(os.path.join(current, name)).st_size
                except OSError:
                    pass
    return total


def _write_new(path, text):
    with open(path, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(text)


def _size(nbytes):
    if nbytes >= GIB:
        return '%.2f GiB' % (nbytes / GIB)
    if nbytes >= MIB:
        return '%.1f MiB' % (nbytes / MIB)
    if nbytes >= 1024:
        return '%.1f KiB' % (nbytes / 1024)
    return '%d bytes' % nbytes


def _speed(value):
    return '-' if value is None else '%.1f MiB/s' % value


def _round2(value):
    return None if value is None else round(value, 2)


def bench_report(result):
    """Devolve ``(texto, dados)``: texto em português e dicionário para JSON.

    Nenhum dos dois tem caminhos: só letras de unidade, quantidades, tamanhos
    e velocidades.
    """
    sample = result.sample
    rounds = []
    for r in result.rounds:
        rounds.append({
            'bloco_mib': r.chunk_mib,
            'completa': r.complete,
            'arquivos_conferidos': r.files_ok,
            'bytes': r.bytes,
            'leitura_mib_s': _round2(r.read_mib_s),
            'escrita_mib_s': _round2(r.write_mib_s),
            'conferencia_mib_s': _round2(r.verify_mib_s),
            'copia_mib_s': _round2(r.copy_mib_s),
            'com_conferencia_mib_s': _round2(r.total_mib_s),
            'divergencias_sha256': r.mismatches,
            'erros': r.errors,
        })
    data = {
        'schema': 'pcro-medicao-copia/1',
        'situacao': result.status,
        'data': result.date,
        'unidade_origem': result.source_drive,
        'unidade_destino': result.dest_drive,
        'pasta_de_medicao': result.folder_name,
        'amostra': {
            'arquivos': len(sample.files),
            'bytes': sample.total_bytes,
            'links_pulados': sample.skipped_links,
            'ilegiveis': sample.unreadable,
            'grandes_demais': sample.too_big,
            'limitada': sample.truncated,
        },
        'rodadas': rounds,
        'gravado_bytes': result.written_bytes,
        'sugestao': result.suggestion,
    }
    lines = [
        'Medição de cópia — PC Restore & Optimizer',
        '',
        'Situação: %s' % ('concluída' if result.status == 'concluída'
                          else 'interrompida (parou antes do fim)'),
        'Data: %s' % result.date,
        'Origem: unidade %s (só lida, nada foi alterado)' % result.source_drive,
        'Destino: unidade %s, pasta de medição %s' % (result.dest_drive,
                                                     result.folder_name),
        '',
        'Amostra: %d arquivos, %s' % (len(sample.files), _size(sample.total_bytes)),
    ]
    if sample.truncated:
        lines.append('  (a amostra parou no limite de tamanho ou de arquivos)')
    if sample.skipped_links:
        lines.append('  %d atalhos (links/junções) foram pulados' % sample.skipped_links)
    if sample.too_big:
        lines.append('  %d arquivos maiores que o limite ficaram de fora' % sample.too_big)
    if sample.unreadable:
        lines.append('  %d itens não puderam ser lidos' % sample.unreadable)
    lines.append('')
    lines.append('Resultado por tamanho de bloco:')
    for r in result.rounds:
        lines.append(
            '  Bloco %d MiB: leitura %s, escrita %s, conferência SHA-256 %s, '
            'tudo junto %s — %d arquivos conferidos%s'
            % (r.chunk_mib, _speed(r.read_mib_s), _speed(r.write_mib_s),
               _speed(r.verify_mib_s), _speed(r.total_mib_s), r.files_ok,
               '' if r.complete else ' (rodada incompleta)'))
        if r.mismatches:
            lines.append('    ATENÇÃO: %d cópias não bateram com o original '
                         '(SHA-256 diferente).' % r.mismatches)
        if r.errors:
            lines.append('    %d arquivos deram erro de leitura ou escrita.' % r.errors)
    lines += [
        '',
        'Sugestão: %s' % result.suggestion.get('texto', ''),
        '',
        'Observação: a partir da segunda rodada o Windows pode ler a origem '
        'da memória (cache), então a leitura pode parecer mais rápida.',
        '',
        'Nada foi apagado. A pasta de medição ocupa %s e pode ser apagada à mão '
        'quando você quiser.' % _size(result.written_bytes),
    ]
    if result.status != 'concluída':
        lines.append('Arquivos terminados em .parcial são cópias pela metade '
                     'da medição interrompida.')
    return '\n'.join(lines) + '\n', data
