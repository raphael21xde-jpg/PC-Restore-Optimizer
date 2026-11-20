"""P4-02 (Fatia 1): módulo puro do assistente "Primeiro uso guiado" (sem tkinter).

Guarda os textos de introdução, a dica de modo de execução (sem administrador
para backup/restauração) e as 6 etapas de orientação do primeiro uso, além de
ler e gravar as marcações (`pendente`, `feito`, `pulado`) fora da thread da
interface.

Regras de segurança:
- orientação: este módulo nunca executa varredura, cópia, restauração,
  diagnóstico de discos nem comandos do sistema; ele grava apenas o arquivo de
  progresso das marcações na pasta de dados do app;
- nunca apaga arquivos do usuário nem o arquivo de progresso (o único arquivo
  que some é o `.lock` que o próprio `exclusive_lock` cria e tira);
- limite conhecido: se a gravação falha depois de criar o `.parcial-xxxxxxxx`,
  ele fica na pasta de dados do app (nunca é apagado); com mais de
  `MAX_PARTIAL_FILES` sobras, a gravação é recusada para não acumular;
- gravação atômica em `.parcial` de nome único (`O_CREAT | O_EXCL`), `fsync` e
  `os.replace` com espera crescente, tudo dentro de `exclusive_lock` (R-09);
- arquivos estragados, grandes demais ou que sejam links ou arquivos especiais
  do Windows ficam como estão: quem escolhe o `-2`, `-3`... é a leitura
  (`load_first_use_progress`); a gravação por cima de um deles é recusada com
  `FirstUseBadProgressFileError` (um `OSError`);
- uma janela só (decisão de 20/11/2026): a tela manda sempre as 6 marcações
  completas, e elas são gravadas como estão (sem juntar com outra janela);
  dicionário incompleto é recusado, para nunca desmarcar uma etapa sem querer;
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
MAX_PARTIAL_FILES = 20

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
        'backup que você escolher; na restauração, numa pasta nova dentro da pasta '
        'que você escolher; e, se você usar "Colocar no lugar original", no lugar '
        'original de cada arquivo, depois de mostrar uma prévia (um arquivo diferente '
        'que já existia é renomeado para .antes-pcro-AAAAMMDD, nunca apagado); '
        f'lembre-se de que o que não for copiado do {d} não entra no '
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
                'que você escolher; na restauração, numa pasta nova dentro da pasta '
                'que você escolher; e, se você usar "Colocar no lugar original", no '
                'lugar original de cada arquivo, depois de mostrar uma prévia (um '
                'arquivo diferente que já existia é renomeado para .antes-pcro-AAAAMMDD, '
                f'nunca apagado); o que não for copiado do {d} não entra no backup e se '
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
                'depois em "2. Iniciar backup (confirmação dupla)". O app grava a '
                'cópia no destino que você escolher e não apaga nenhum arquivo; '
                f'o que não for copiado do {d} não entra no backup e se perde quando '
                f'o instalador formatar o {d}.'
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
                'volta e "Otimização" para medir e ajustar o PC com segurança. '
                f'Lembre-se: o que não for copiado do {d} não entra no backup e se '
                f'perde quando o instalador formatar o {d}.'
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


class FirstUseTooManyPartialsError(OSError):
    """Recusa gravar quando já há sobras `.parcial-*` demais do arquivo (nunca apaga)."""

    def __init__(self, filename: str, count: int) -> None:
        super().__init__(
            f'Há {count} sobras de gravação de "{filename}"; nada foi gravado.'
        )
        self.filename = filename
        self.count = count


def _count_partials(path: Path) -> int:
    """Conta as sobras `<nome>.parcial-*` DESTE arquivo de progresso (só leitura)."""
    prefix = f'{path.name}{PARTIAL_SUFFIX}-'
    try:
        with os.scandir(path.parent) as entries:
            return sum(1 for entry in entries if entry.name.startswith(prefix))
    except OSError:
        return 0


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
    if isinstance(exc, ValueError):
        # A causa é o pedido, não o arquivo (R-37).
        return (
            'Não deu para salvar o progresso: as marcações não puderam ser salvas '
            '(ValueError); o arquivo de progresso foi deixado como está. '
            'O app tenta salvar de novo na próxima marcação; se você fechar a '
            'janela antes disso, estas marcações se perdem.'
        )
    if isinstance(exc, FirstUseTooManyPartialsError):
        return (
            'Não deu para salvar o progresso: há sobras de gravações que falharam '
            f'(arquivos com ".parcial" no nome, ao lado do arquivo de progresso{target}, '
            'na pasta de dados do app); nada foi apagado e o arquivo de progresso '
            'foi deixado como está. Se quiser, apague essas sobras você mesmo. '
            'O app tenta salvar de novo na próxima marcação; se você fechar a '
            'janela antes disso, estas marcações se perdem.'
        )
    if isinstance(exc, FirstUseBadProgressFileError):
        return (
            f'Não deu para salvar o progresso: o arquivo de progresso{target} não '
            'pôde ser usado; ele foi deixado como está. '
            'O app tenta salvar de novo na próxima marcação; se você fechar a '
            'janela antes disso, estas marcações se perdem.'
        )
    return (
        f'Não deu para salvar o progresso: o arquivo de progresso{target} não pôde '
        f'ser gravado ({type(exc).__name__}); ele foi deixado como está. '
        'O app tenta salvar de novo na próxima marcação; se você fechar a '
        'janela antes disso, estas marcações se perdem.'
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


def validate_complete_first_use_steps(steps) -> dict[str, str]:
    """Confere um dicionário COMPLETO (as 6 etapas); senão levanta `ValueError`.

    Com uma janela só, a tela sempre manda o estado inteiro das marcações.
    Um dicionário parcial é recusado (em vez de completar com `pendente`), para
    que um pedido incompleto nunca desmarque sem querer uma etapa já feita.
    """
    clean = validate_first_use_steps(steps)
    missing = [key for key in STEP_IDS if key not in steps]
    if missing:
        raise ValueError(f'Faltam etapas no progresso: {", ".join(missing)}.')
    return clean


def save_first_use_progress(path, steps) -> dict[str, str]:
    """Grava as 6 marcações de forma atômica sem nunca apagar arquivos (R-09).

    O guia abre uma janela só (decisão de 20/11/2026), então o que a janela
    mostra é o que vale: o dicionário completo é gravado como está, sem juntar
    com o que está no disco. Antes de gravar, dentro de `exclusive_lock` (contra
    dois processos do app gravando ao mesmo tempo), relê e confere o arquivo:
    recusa gravar por cima de link, arquivo não-comum ou arquivo estragado
    (`FirstUseBadProgressFileError`). Dicionário incompleto ou inválido é
    recusado com `ValueError` antes de tocar no disco.

    Limite aceito (exceção à R-09 só para este arquivo, decisão de 20/11/2026):
    o app não tem trava de instância única, então, se houver outro processo do
    app aberto com o guia, vale o último a gravar; a marcação gravada por outro
    processo do app pode ser trocada pela desta janela. O `exclusive_lock` só
    impede que as duas gravações se misturem no mesmo arquivo.

    Se a gravação falha depois de criar o `.parcial-xxxxxxxx`, ele fica como
    está (nunca é apagado). Com mais de `MAX_PARTIAL_FILES` sobras deste
    arquivo, a gravação é recusada (`FirstUseTooManyPartialsError`), para que
    falhas repetidas não encham a pasta de dados do app.
    """
    clean = validate_complete_first_use_steps(steps)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(path):
        kind, disk_value = _read_candidate(path)
        if kind == 'ruim':
            raise FirstUseBadProgressFileError(
                path.name,
                f'O arquivo de progresso "{path.name}" não pôde ser usado '
                f'({disk_value}); nada foi gravado.',
            )
        leftovers = _count_partials(path)
        if leftovers > MAX_PARTIAL_FILES:
            raise FirstUseTooManyPartialsError(path.name, leftovers)
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

    Feito para UMA janela só (decisão de 20/11/2026): cada pedido traz as 6
    marcações completas, e o mais novo vale sozinho.
    - Uma única thread não-daemon por gravador; pedidos que chegam durante uma
      gravação são trocados pelo mais novo (o último clique sempre vence).
    - Pedido inválido ou incompleto é recusado na hora, em `request`
      (`ValueError`), e nunca entra na fila.
    - Se a gravação falha, as marcações ficam guardadas em `pending()` e o
      aviso de erro (`poll_error()`) fica até uma gravação dar certo; o app
      tenta de novo no próximo `request` (com as marcações mais novas).
    """

    def __init__(self, path, *, save=None):
        self.path = None if path is None else Path(path)
        self._save = save
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._wanted: dict[str, str] | None = None
        self._writing: dict[str, str] | None = None
        self._failed: dict[str, str] | None = None
        self._error: str | None = None
        self._thread: threading.Thread | None = None
        self.closed = False

    def request(self, steps) -> None:
        """Pede para gravar uma cópia das 6 marcações e retorna imediatamente."""
        copy = validate_complete_first_use_steps(steps)
        with self._lock:
            if self.closed or self.path is None:
                return
            self._failed = None  # o pedido novo já traz o estado inteiro
            self._wanted = copy
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
                steps = self._wanted
                if steps is None:
                    self._writing = None
                    self._thread = None
                    self._idle.notify_all()
                    return
                self._wanted = None
                self._writing = steps
            try:
                if self._save is not None:
                    self._save(self.path, dict(steps))
                else:
                    save_first_use_progress(self.path, steps)
                error = None
            except Exception as exc:  # noqa: BLE001 - qualquer falha vira aviso fixo
                error = first_use_error_text(exc, self.path)
            with self._lock:
                if error is not None and self._wanted is None:
                    self._failed = steps  # grava de novo só no próximo request
                self._writing = None
                self._error = error

    def poll_error(self) -> str | None:
        """Erro da última gravação terminada (sem caminho completo) ou `None`."""
        with self._lock:
            return self._error

    def pending(self) -> dict[str, str] | None:
        """As 6 marcações mais novas ainda não gravadas, ou `None`.

        Vale o pedido que espera; senão, o que está sendo gravado; senão, o que
        falhou. Lido numa tomada só da trava.
        """
        with self._lock:
            for item in (self._wanted, self._writing, self._failed):
                if item is not None:
                    return dict(item)
            return None

    def busy(self) -> bool:
        """`True` enquanto há pedido esperando ou gravação em andamento.

        Depois de uma falha sem pedido novo, `busy()` é `False` mesmo com
        marcações não gravadas: o "Fechar" da janela deve decidir por
        `pending()`, nunca por `busy()`/`join()`.
        """
        with self._lock:
            return self._thread is not None

    def close(self) -> None:
        """Sinaliza que a janela fechou, sem cancelar gravação em andamento.

        Antes de fechar, a janela deve decidir pelo que `pending()` devolve
        (marcações que falharam continuam lá mesmo com `busy()` `False` e
        `join()` `True`); depois de `close()`, novos pedidos são ignorados.
        """
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
    """Lê o progresso preferindo as marcações ainda não gravadas no `saver`.

    Serve para reabrir a janela enquanto uma gravação ainda não terminou: as
    pendentes (lidas ANTES do disco) valem por inteiro no lugar do disco.
    """
    load_fn = load_first_use_progress if load is None else load
    pending = saver.pending() if saver is not None else None
    progress = load_fn(base)
    if pending is not None:
        progress = dict(progress, steps=validate_complete_first_use_steps(pending))
    return progress
