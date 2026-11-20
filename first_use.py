"""P4-02 (Fatia 1): módulo puro do assistente "Primeiro uso guiado" (sem tkinter).

Guarda os textos de introdução, a dica de modo de execução (sem administrador
para backup/restauração) e as 6 etapas de orientação do primeiro uso, além de
ler e gravar as marcações (`pendente`, `feito`, `pulado`) fora da thread da
interface.

Regras de segurança:
- orientação: este módulo nunca executa varredura, cópia, restauração,
  diagnóstico de discos nem comandos do sistema; ele grava apenas o arquivo de
  progresso das marcações na pasta de dados do app;
- nunca apaga arquivos;
- gravação atômica em `.parcial` de nome único (`O_CREAT | O_EXCL`), `fsync` e
  `os.replace` com espera crescente, tudo dentro de `exclusive_lock` (R-09);
- arquivos estragados, grandes demais ou que sejam links ou arquivos especiais
  do Windows ficam como estão: quem escolhe o `-2`, `-3`... é a leitura
  (`load_first_use_progress`); a gravação por cima de um deles é recusada com
  `FirstUseBadProgressFileError` (um `OSError`);
- `save_first_use_progress` exige `base_steps` quando `reset=False`, para que o
  dicionário da memória nunca apague a marcação gravada por outra janela;
- mensagens de erro fixas sem expor caminho completo nem nome de usuário (R-07);
- textos seguem a R-88 e usam `workflow_texts.system_drive()` (sem letra fixa).
"""
from __future__ import annotations

import json
import ntpath
import os
import stat
import threading
import time
import uuid
from pathlib import Path

from atomic_write import exclusive_lock
from choices_store import app_data_dir
from workflow_texts import system_drive

PENDING, DONE, SKIPPED = 'pendente', 'feito', 'pulado'
STATUSES = (PENDING, DONE, SKIPPED)
STATUS_TEXT = {PENDING: 'Pendente', DONE: 'Feito', SKIPPED: 'Pulado'}

STEP_IDS = (
    'diagnostico',
    'explorar',
    'preservacao',
    'backup',
    'testar',
    'proximos',
)

SCHEMA = 'pcro-primeiro-uso-v1'
PROGRESS_FILENAME = 'primeiro-uso-progresso.json'
PROGRESS_LIMIT = 64 * 1024
MAX_PROGRESS_FILES = 50
PARTIAL_SUFFIX = '.parcial'

REPLACE_FIRST_WAIT = 0.005
REPLACE_MAX_WAIT = 0.2
REPLACE_TOTAL_WAIT = 2.0

FIRST_USE_MODE_NOTE = (
    'Dica: use o aplicativo aberto do jeito normal (sem "Executar como administrador") '
    'para fazer backup e restaurar. Só abra como administrador, com a sua própria conta, '
    'se for aplicar ajustes nas abas "4  Energia reversível", "8  Ajustes seguros" ou '
    '"9  Ajustes avançados" de "Otimização" (e também para desfazer ajustes da aba '
    '"9  Ajustes avançados", inclusive pelo "Desfazer tudo" da aba "7  Alterações feitas").'
)


def FIRST_USE_INTRO_TEXT(drive: str | None = None) -> str:
    """Texto de boas-vindas e regras de segurança do Primeiro uso guiado (R-88)."""
    d = system_drive() if drive is None else drive
    return (
        'Bem-vindo ao PC Restore & Optimizer. Este guia mostra a ordem recomendada '
        'para usar o aplicativo com segurança, passo a passo.\n\n'
        'O guia orienta e abre cada tela para você (nenhuma cópia, restauração ou '
        'leitura de discos começa sozinha ao clicar em "Abrir"); ele guarda apenas '
        f'as suas marcações (Feito/Pulado) no arquivo {PROGRESS_FILENAME} na pasta de '
        'dados do app. O app não apaga nenhum arquivo: grava a cópia no destino de '
        'backup que você escolher e, na restauração, nas pastas que você indicar '
        '(um arquivo que já existia é renomeado para .antes-pcro-AAAAMMDD, nunca '
        f'apagado); lembre-se de que o que não for copiado do {d} não entra no '
        f'backup e se perde quando o instalador formatar o {d}.'
    )


def FIRST_USE_STEPS(drive: str | None = None) -> tuple[dict[str, str], ...]:
    """Devolve as 6 etapas do Primeiro uso guiado para a unidade do Windows informada."""
    d = system_drive() if drive is None else drive
    return (
        {
            'id': 'diagnostico',
            'title': 'Conhecer os discos',
            'text': (
                'Veja na tela "Diagnóstico" quais discos existem no seu PC e qual é o '
                'disco do Windows. O backup precisará ir para outro disco físico, que '
                'não será formatado. O app não apaga nenhum arquivo e, nessa tela, '
                'grava um relatório apenas se você clicar em "Exportar relatório JSON" '
                f'(no arquivo que você escolher); o que não for copiado do {d} não entra '
                f'no backup e se perde quando o instalador formatar o {d}.'
            ),
            'page': 'diagnostic',
        },
        {
            'id': 'explorar',
            'title': 'Varrer e escolher o que manter',
            'text': (
                'Na tela "Meu computador", examine as unidades desejadas e marque jogos, '
                'aplicativos e pastas como "Manter selecionados" ou "Não preservar" '
                '(as suas escolhas ficam guardadas na pasta de dados do app; '
                'o app não apaga nenhum arquivo: grava a cópia no destino de backup '
                'que você escolher e, na restauração, nas pastas que você indicar, '
                'onde um arquivo que já existia é renomeado para .antes-pcro-AAAAMMDD, '
                f'nunca apagado; o que não for copiado do {d} não entra no backup e se '
                f'perde quando o instalador formatar o {d}). Para adicionar pastas '
                'avulsas ou criar o cofre do navegador, use "Seleção avançada".'
            ),
            'page': 'home',
        },
        {
            'id': 'preservacao',
            'title': 'Revisar o plano de preservação',
            'text': (
                f'Na tela "Preservação", confira tudo o que foi marcado e os saves de '
                f'jogos que estão no {d}. O que ficar desmarcado ou pendente no {d} não '
                f'entra no backup e se perde quando o instalador formatar o {d}.'
            ),
            'page': 'preservation',
        },
        {
            'id': 'backup',
            'title': 'Escolher destino e fazer o backup',
            'text': (
                'Na tela de revisão do backup (aberta por "Próximo: revisar backup dos '
                'arquivos escolhidos →" em "Preservação"), use "Escolher destino" para '
                'apontar para outro disco, clique em "1. Recalcular plano e espaço" e '
                'depois em "2. Iniciar backup (confirmação dupla)".'
            ),
            'page': 'review',
        },
        {
            'id': 'testar',
            'title': 'Testar o backup antes de formatar',
            'text': (
                'Nunca formate sem testar o backup. Na tela "Histórico e relatórios", '
                'escolha o backup criado e use "Testar restauração de arquivo pequeno" '
                'para comprovar que os arquivos podem ser lidos (o app grava a cópia '
                'de teste numa pasta nova, dentro da pasta que você escolher, e não '
                f'apaga nenhum arquivo). O que não for copiado do {d} não entra no '
                f'backup e se perde quando o instalador formatar o {d}.'
            ),
            'page': 'history',
        },
        {
            'id': 'proximos',
            'title': 'Instalar o Windows, restaurar ou otimizar',
            'text': (
                'Com o backup testado, veja o checklist em "Instalar Windows" (quem '
                'formata e instala é o instalador oficial da Microsoft, operado por '
                'você). No Windows novo, use "Depois de formatar" para trazer tudo de '
                'volta e "Otimização" para medir e ajustar o PC com segurança.'
            ),
            'page': 'installation',
        },
    )


def default_first_use_base(environ=None) -> Path:
    """Pasta padrão do progresso em `%LOCALAPPDATA%\\PC-Restore-Optimizer`."""
    return app_data_dir(frozen=True, environ=environ)


def first_use_progress_path(base=None, environ=None) -> Path:
    """Caminho do primeiro arquivo candidato de progresso do Primeiro uso guiado."""
    folder = default_first_use_base(environ=environ) if base is None else Path(base)
    return folder / PROGRESS_FILENAME


def _candidate(first: Path, number: int) -> Path:
    if number == 1:
        return first
    return first.with_name(f'{first.stem}-{number}{first.suffix}')


def empty_first_use_steps() -> dict[str, str]:
    """Dicionário com todas as 6 etapas marcadas como `pendente`."""
    return {step_id: PENDING for step_id in STEP_IDS}


def validate_first_use_steps(steps) -> dict[str, str]:
    """Confere as marcações; levanta `ValueError` se houver etapa ou valor inválido."""
    if not isinstance(steps, dict):
        raise ValueError('Progresso inválido.')
    clean = empty_first_use_steps()
    for key, value in steps.items():
        if key not in clean:
            raise ValueError(f'Etapa desconhecida: {key!r}.')
        if value not in STATUSES:
            raise ValueError(
                f'Marcação inválida: {value!r} (use pendente, feito ou pulado).'
            )
        clean[key] = value
    return clean


def _is_link(info) -> bool:
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(
        (getattr(info, 'st_file_attributes', 0) or 0) & reparse
    )


def _read_bytes_with_retry(path: Path, limit: int, sleep=None) -> bytes:
    sleep = time.sleep if sleep is None else sleep
    wait = REPLACE_FIRST_WAIT
    waited = 0.0
    while True:
        try:
            with open(path, 'rb') as handle:
                return handle.read(limit)
        except PermissionError:
            if waited >= REPLACE_TOTAL_WAIT:
                raise
            step = min(wait, REPLACE_MAX_WAIT, REPLACE_TOTAL_WAIT - waited)
            sleep(step)
            waited += step
            wait *= 2


def _read_candidate(path: Path):
    """Devolve `('ausente', None)`, `('ok', steps)` ou `('ruim', motivo)`."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return 'ausente', None
    except OSError:
        return 'ruim', 'não pôde ser lido'
    if _is_link(info):
        return 'ruim', 'é um link ou um arquivo especial do Windows'
    if not stat.S_ISREG(info.st_mode):
        return 'ruim', 'não é um arquivo comum'
    if info.st_size > PROGRESS_LIMIT:
        return 'ruim', 'grande demais'
    try:
        data = _read_bytes_with_retry(path, PROGRESS_LIMIT + 1)
    except OSError:
        return 'ruim', 'não pôde ser lido'
    if len(data) > PROGRESS_LIMIT:
        return 'ruim', 'grande demais'
    try:
        doc = json.loads(data.decode('utf-8'))
        if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
            return 'ruim', 'formato desconhecido'
        steps = validate_first_use_steps(doc.get('steps'))
    except (ValueError, UnicodeDecodeError, RecursionError):
        return 'ruim', 'estragado'
    return 'ok', steps


def _bad_warning(path: Path, reason: str, used_path: Path | None = None) -> str:
    if used_path is not None:
        return (
            f'O progresso salvo "{path.name}" não pôde ser usado ({reason}). '
            f'Ele foi deixado como está e o guia continuou com "{used_path.name}".'
        )
    return (
        f'O progresso salvo "{path.name}" não pôde ser usado ({reason}). '
        'Ele foi deixado como está e o guia começou do zero.'
    )


def load_first_use_progress(base=None, *, environ=None) -> dict:
    """Lê o progresso salvo do Primeiro uso guiado sem tocar em arquivos ruins.

    Devolve `{'steps', 'path', 'warnings'}`. Se o arquivo principal estiver
    estragado, grande demais ou for um link, fica intocado e a função avança
    para `-2`, `-3`... até `MAX_PROGRESS_FILES`.
    """
    first = first_use_progress_path(base, environ=environ)
    bad_entries: list[tuple[Path, str]] = []
    for number in range(1, MAX_PROGRESS_FILES + 1):
        path = _candidate(first, number)
        kind, value = _read_candidate(path)
        if kind == 'ok':
            warnings = [_bad_warning(p, r, used_path=path) for p, r in bad_entries]
            return {'steps': value, 'path': path, 'warnings': warnings}
        if kind == 'ausente':
            warnings = [_bad_warning(p, r) for p, r in bad_entries]
            return {
                'steps': empty_first_use_steps(),
                'path': path,
                'warnings': warnings,
            }
        bad_entries.append((path, value))
    warnings = [_bad_warning(p, r) for p, r in bad_entries]
    warnings.append(
        'Não há onde salvar o progresso; as marcações valem só até fechar a janela.'
    )
    return {'steps': empty_first_use_steps(), 'path': None, 'warnings': warnings}


class FirstUseBadProgressFileError(OSError):
    """Erro ao gravar sobre arquivo de progresso ruim ou especial (R-07)."""

    def __init__(self, filename: str, message: str) -> None:
        super().__init__(message)
        self.filename = filename


def _file_name_only(value) -> str:
    if not value:
        return ''
    return ntpath.basename(str(value).replace('/', '\\'))


def first_use_error_text(exc: BaseException, path=None) -> str:
    """Aviso fixo de falha ao salvar o progresso (sem caminho completo, R-07).

    Mostra só o nome do arquivo (de `path`, ou do `filename` do erro) e o tipo
    do erro; nunca a mensagem do sistema, que pode ter o caminho completo.
    """
    name = _file_name_only(path) or _file_name_only(getattr(exc, 'filename', None))
    target = f' "{name}"' if name else ''
    if isinstance(exc, FirstUseBadProgressFileError):
        return (
            f'Não deu para salvar o progresso: o arquivo de progresso{target} não é '
            'um arquivo comum ou não pôde ser lido; ele foi deixado como está. As '
            'marcações valem só até fechar a janela.'
        )
    return (
        f'Não deu para salvar o progresso: o arquivo de progresso{target} não pôde '
        f'ser gravado ({type(exc).__name__}); ele foi deixado como está. As '
        'marcações valem só até fechar a janela.'
    )


def first_use_warning_text(base_warning: str, error: str | None) -> str:
    """Linha de aviso do progresso: prioriza o erro da última gravação."""
    return error if error else base_warning


def _replace_with_retry(partial: Path, path: Path, sleep=None) -> None:
    sleep = time.sleep if sleep is None else sleep
    wait = REPLACE_FIRST_WAIT
    waited = 0.0
    while True:
        try:
            os.replace(partial, path)
            return
        except PermissionError:
            if waited >= REPLACE_TOTAL_WAIT:
                raise
            step = min(wait, REPLACE_MAX_WAIT, REPLACE_TOTAL_WAIT - waited)
            sleep(step)
            waited += step
            wait *= 2


def save_first_use_progress(
    path,
    steps,
    *,
    base_steps: dict[str, str] | None = None,
    reset: bool = False,
) -> dict[str, str]:
    """Grava as marcações de forma atômica sem nunca apagar arquivos (R-09).

    Antes de cada gravação, relê e confere o arquivo no disco: recusa gravar
    por cima de link, arquivo não-comum ou arquivo estragado, e faz junção
    para que gravar o dicionário da memória nunca apague marcação gravada por
    outra janela ou instância. Com `reset=True`, sobrescreve todas as etapas
    (ex.: "Recomeçar marcações"), mantendo a recusa de arquivos ruins.
    """
    if not isinstance(steps, dict):
        raise ValueError('Progresso inválido.')
    if not reset and base_steps is None:
        raise ValueError('base_steps é obrigatório quando reset=False.')
    explicit_keys = set(steps.keys())
    clean = validate_first_use_steps(steps)
    base_clean = (
        validate_first_use_steps(base_steps) if base_steps is not None else None
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(path):
        kind, disk_value = _read_candidate(path)
        if kind == 'ruim':
            raise FirstUseBadProgressFileError(
                path.name,
                f'O arquivo de progresso "{path.name}" não é um arquivo comum ou '
                f'não pôde ser lido ({disk_value}); nada foi gravado.',
            )
        if kind == 'ok' and not reset:
            assert base_clean is not None
            merged = dict(disk_value)
            for key in STEP_IDS:
                if key in explicit_keys and clean[key] != base_clean[key]:
                    merged[key] = clean[key]
            clean = merged
        doc = {'schema': SCHEMA, 'steps': clean}
        data = json.dumps(doc, ensure_ascii=False, indent=2).encode('utf-8')
        partial = path.with_name(f'{path.name}{PARTIAL_SUFFIX}-{uuid.uuid4().hex[:8]}')
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0)
        handle = os.open(partial, flags, 0o600)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(handle, view):]
            os.fsync(handle)
        finally:
            os.close(handle)
        _replace_with_retry(partial, path)
    return clean


class FirstUseProgressSaver:
    """Grava o progresso do Primeiro uso guiado fora da thread do Tk (R-10).

    Mantém uma única thread não-daemon por gravador e junta pedidos
    intermediários para que a última marcação sempre vença, preservando no
    disco entradas gravadas por outra instância (R-09, R-94):
    - pedidos parciais que esperam são somados (`dict(anterior); update(novo)`),
      nunca trocados; um pedido com `reset=True` substitui o que esperava, e
      os pedidos seguintes herdam o `reset`;
    - a base da diferença (`base_steps`) é o que ESTA janela pediu, nunca o que
      foi lido do disco ou juntado com outra janela; `poll_merged()` devolve o
      que ficou no disco.
    """

    def __init__(self, path, *, initial_steps, save=None):
        self.path = None if path is None else Path(path)
        self._save = save
        self._base = validate_first_use_steps(initial_steps)
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._wanted: tuple[dict[str, str], bool] | None = None
        self._writing: tuple[dict[str, str], bool] | None = None
        self._merged: dict[str, str] | None = None
        self._error: str | None = None
        self._thread: threading.Thread | None = None
        self.closed = False

    def request(self, steps, *, reset: bool = False) -> None:
        """Pede para gravar uma cópia das marcações e retorna imediatamente."""
        if not isinstance(steps, dict):
            raise ValueError('Progresso inválido.')
        copy = dict(steps)
        with self._lock:
            if self.closed or self.path is None:
                return
            if reset or self._wanted is None:
                self._wanted = (copy, bool(reset) or (
                    self._wanted is not None and self._wanted[1]
                ))
            else:
                summed = dict(self._wanted[0])
                summed.update(copy)
                self._wanted = (summed, self._wanted[1])
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run,
                    name='pcro-primeiro-uso-progresso',
                    daemon=False,
                )
                self._thread.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                wanted = self._wanted
                base = dict(self._base)
                if wanted is None:
                    self._writing = None
                    self._thread = None
                    self._idle.notify_all()
                    return
                steps, reset = wanted
                self._wanted = None
                self._writing = (steps, reset)
            merged: dict[str, str] | None = None
            try:
                if self._save is not None:
                    result = self._save(self.path, steps, base_steps=base, reset=reset)
                    raw_merged = result if isinstance(result, dict) else steps
                    merged = validate_first_use_steps(raw_merged)
                else:
                    merged = save_first_use_progress(
                        self.path, steps, base_steps=base, reset=reset
                    )
                error = None
            except Exception as exc:  # noqa: BLE001 - qualquer falha vira aviso fixo
                error = first_use_error_text(exc, self.path)
            with self._lock:
                if error is None and merged is not None:
                    # R-94: a base é o que esta janela pediu, nunca o disco.
                    asked = validate_first_use_steps(steps)
                    if reset:
                        self._base = asked
                    else:
                        for key in steps:
                            self._base[key] = asked[key]
                    self._merged = dict(merged)
                self._writing = None
                self._error = error

    def poll_merged(self) -> dict[str, str] | None:
        """Último dicionário juntado e gravado com sucesso, ou `None`."""
        with self._lock:
            return None if self._merged is None else dict(self._merged)

    def poll_error(self) -> str | None:
        """Erro da última gravação terminada (sem caminho completo) ou `None`."""
        with self._lock:
            return self._error

    def pending_steps(self) -> dict[str, str] | None:
        """Marcações pedidas e ainda não gravadas, ou `None`.

        Soma o pedido em gravação (por baixo) com o que espera (por cima); se o
        que espera é um recomeço (`reset=True`), ele vale sozinho.
        """
        with self._lock:
            if self._wanted is not None and (self._wanted[1] or self._writing is None):
                return dict(self._wanted[0])
            if self._writing is None:
                return None
            steps = dict(self._writing[0])
            if self._wanted is not None:
                steps.update(self._wanted[0])
            return steps

    def pending_is_reset(self) -> bool:
        """Indica se as marcações pendentes pedem para recomeçar (`reset=True`)."""
        with self._lock:
            return bool(
                (self._wanted is not None and self._wanted[1])
                or (self._writing is not None and self._writing[1])
            )

    def busy(self) -> bool:
        """`True` enquanto há pedido esperando ou gravação em andamento."""
        with self._lock:
            return self._thread is not None

    def close(self) -> None:
        """Sinaliza que a janela fechou, sem cancelar gravação em andamento."""
        with self._lock:
            self.closed = True

    def join(self, timeout: float | None = None) -> bool:
        """Espera a gravação pendente terminar; `True` se concluiu no prazo."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            while self._thread is not None:
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._idle.wait(left)
            return True


def load_first_use_with_pending(
    base=None,
    saver: FirstUseProgressSaver | None = None,
    *,
    load=None,
) -> dict:
    """Lê o progresso preferindo marcações pendentes no `saver` antes do disco."""
    load_fn = load_first_use_progress if load is None else load
    pending = saver.pending_steps() if saver is not None else None
    pending_reset = (
        saver.pending_is_reset()
        if saver is not None and hasattr(saver, 'pending_is_reset')
        else False
    )
    progress = load_fn(base)
    if pending is not None:
        validated = validate_first_use_steps(pending)
        if pending_reset:
            steps = validated
        else:
            steps = dict(progress['steps'])
            for key in pending:
                steps[key] = validated[key]
        progress = dict(progress, steps=steps)
    return progress
