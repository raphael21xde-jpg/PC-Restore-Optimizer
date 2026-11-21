"""P4-02 (Fatia 2): janela "Primeiro uso guiado".

Uma janela só por app (decisão de 20/11/2026): abrir de novo traz a mesma
janela para a frente (`deiconify` + `lift`). Ela mostra as 6 etapas de
`first_use.FIRST_USE_STEPS(workflow_texts.system_drive())`, cada uma com
"Abrir" (que apenas chama `app.navigate` para a página que já existe),
"Feito" e "Pular". "Recomeçar marcações" volta as 6 etapas para Pendente.

Regras de segurança:
- o guia orienta: "Abrir" nunca começa varredura, cópia, restauração nem
  diagnóstico; ele troca a página do app e mais nada;
- a leitura do arquivo de progresso roda num `Job` (segundo plano), nunca na
  thread do Tk (R-10); até ela voltar, a janela mostra "Carregando..." e os
  botões das etapas ficam desligados;
- a gravação das marcações é feita pelo `FirstUseProgressSaver` (thread
  própria); a janela manda sempre as 6 marcações e nunca grava na thread do Tk;
- o gravador é um por app (`app.first_use_saver`) e não é fechado quando a
  janela fecha: reabrir a janela continua no mesmo gravador, então uma
  marcação nova nunca é gravada antes de uma antiga ainda pendente;
- os avisos mostram só o nome do arquivo (R-07) e os timers da janela são
  cancelados ao fechar (`WindowTimers`, R-11).

A lógica fica em `FirstUseFlow`, sem tkinter, para ser testada com objetos
falsos; `show_first_use` monta os widgets e liga os botões a ela.
"""
from __future__ import annotations

from first_use import (
    DONE,
    FIRST_USE_CLOSE_SAVING_TEXT,
    FIRST_USE_INTRO_TEXT,
    FIRST_USE_LOAD_ERROR_TEXT,
    FIRST_USE_MODE_NOTE,
    FIRST_USE_STEPS,
    PENDING,
    SKIPPED,
    STATUS_TEXT,
    STEP_IDS,
    FirstUseProgressSaver,
    empty_first_use_steps,
    first_use_warning_text,
    load_first_use_with_pending,
)
from restore_jobs import Job
from ui_scale import (
    ESPACO_FINO,
    ESPACO_MINIMO,
    ESPACO_P,
    FONTE_UI,
    PADDING_DIALOGO,
    TAMANHO_CORPO,
    TAMANHO_TITULO_MODAL,
    safe_window_geometry,
    safe_wraplength,
)
import workflow_texts

TITLE = 'Primeiro uso guiado'
LOADING_TEXT = 'Carregando...'
# Páginas que "Abrir" pode mostrar (atributos de App que já existem).
OPEN_PAGES = frozenset({'diagnostic', 'home', 'preservation', 'review', 'history',
                        'installation'})
POLL_MS = 50
WATCH_MS = 150

DESIRED_WIDTH = 980
DESIRED_HEIGHT = 760
MIN_WIDTH = 720
MIN_HEIGHT = 520


def _alive(widget) -> bool:
    try:
        return bool(widget.winfo_exists())
    except Exception:  # noqa: BLE001 - TclError de janela já destruída
        return False


class FirstUseFlow:
    """Estado e ações da janela, sem tkinter (testável com objetos falsos).

    `view` precisa ter: `set_status(step_id, text)`, `set_warning(text)`,
    `set_ready(bool)`, `after(ms, callback)`, `destroy()` e `warn(text)`.
    """

    def __init__(self, app, view, *, base=None, steps=None, job_factory=Job):
        self.app = app
        self.view = view
        self.base = base
        self.spec = tuple(steps if steps is not None
                          else FIRST_USE_STEPS(workflow_texts.system_drive()))
        self.pages = {step['id']: step['page'] for step in self.spec}
        self.job_factory = job_factory
        self.steps = empty_first_use_steps()
        self.saver: FirstUseProgressSaver | None = None
        self.path = None
        self.base_warning = ''
        self.ready = False
        self.job = None
        self.watching = False
        self.closed = False

    # leitura (num Job; volta ao Tk por view.after)
    def start(self) -> None:
        for step_id in STEP_IDS:
            self.view.set_status(step_id, LOADING_TEXT)
        self.view.set_warning('')
        self.view.set_ready(False)
        old = getattr(self.app, 'first_use_saver', None)
        base = self.base
        self.job = self.job_factory(
            lambda cancelled, progress: load_first_use_with_pending(base, old))
        self.view.after(POLL_MS, self._poll)

    def _poll(self) -> None:
        if self.closed or self.job is None:
            return
        result = self.job.poll()
        if result is None:
            self.view.after(POLL_MS, self._poll)
            return
        self.job = None
        kind, value = result
        if kind == 'done':
            self._loaded(value)
        else:
            # mensagem do sistema pode ter o caminho completo: texto fixo (R-07)
            self.steps = empty_first_use_steps()
            self.saver = None
            self.path = None
            self.base_warning = FIRST_USE_LOAD_ERROR_TEXT
            self._finish_loading()

    def _loaded(self, progress) -> None:
        self.steps = dict(progress['steps'])
        self.path = progress['path']
        self.base_warning = ' '.join(progress['warnings'])
        old = getattr(self.app, 'first_use_saver', None)
        if self.path is None:
            self.saver = None  # sem lugar seguro: as marcações valem até fechar
        elif old is not None and not old.closed and old.path == self.path:
            self.saver = old
        else:
            self.saver = FirstUseProgressSaver(self.path)
            self.app.first_use_saver = self.saver
        self._finish_loading()

    def _finish_loading(self) -> None:
        self.ready = True
        for step_id in STEP_IDS:
            self._refresh(step_id)
        self._show_warning()
        self.view.set_ready(True)
        if self.saver is not None and self.saver.busy():
            self._watch()

    # marcações
    def _refresh(self, step_id) -> None:
        self.view.set_status(step_id, STATUS_TEXT[self.steps[step_id]])

    def _show_warning(self) -> None:
        error = self.saver.poll_error() if self.saver is not None else None
        self.view.set_warning(first_use_warning_text(self.base_warning, error))

    def _request(self) -> None:
        if self.saver is None:
            return
        self.saver.request(dict(self.steps))  # grava em segundo plano
        self._watch()

    def _watch(self) -> None:
        if not self.watching:
            self.watching = True
            self.view.after(WATCH_MS, self._watch_tick)

    def _watch_tick(self) -> None:
        if self.closed or self.saver is None:
            self.watching = False
            return
        busy = self.saver.busy()  # antes do erro: se terminou, o erro já está lá
        self._show_warning()
        if busy:
            self.view.after(WATCH_MS, self._watch_tick)
        else:
            self.watching = False

    def mark(self, step_id, value) -> None:
        if not self.ready or self.closed:
            return
        if value not in (DONE, SKIPPED):
            raise ValueError(value)
        # clicar de novo no mesmo botão volta para "Pendente"
        self.steps[step_id] = PENDING if self.steps[step_id] == value else value
        self._refresh(step_id)
        self._request()

    def reset(self) -> None:
        if not self.ready or self.closed:
            return
        self.steps = empty_first_use_steps()
        for step_id in STEP_IDS:
            self._refresh(step_id)
        self._request()

    # navegação
    def open_step(self, step_id) -> None:
        page = self.pages[step_id]
        if page not in OPEN_PAGES:
            raise ValueError(page)
        self.app.navigate(getattr(self.app, page))

    # fechar
    def close(self) -> None:
        if self.closed:
            return
        text = None
        if self.saver is not None and self.saver.pending() is not None:
            busy = self.saver.busy()
            error = self.saver.poll_error()
            text = FIRST_USE_CLOSE_SAVING_TEXT if busy or not error else error
        self.forget()
        self.view.destroy()  # não espera a gravação: ela continua na thread dela
        if text is not None:
            self.view.warn(text)

    def forget(self) -> None:
        """Janela destruída: para de ler e de olhar o gravador (ele continua)."""
        self.closed = True
        if self.job is not None:
            self.job.cancelled.set()
            self.job = None


def _show_close_warning(parent, text) -> None:
    from tkinter import messagebox
    messagebox.showwarning(TITLE, text, parent=parent)


def show_first_use(app, *, base=None):
    """Abre a janela "Primeiro uso guiado" (ou traz a que já está aberta)."""
    previous = getattr(app, 'first_use_dialog', None)
    if previous is not None and _alive(previous):
        previous.deiconify()  # traz de volta se estiver minimizada
        previous.lift()
        return previous

    import tkinter as tk
    from tkinter import ttk

    from ui_timers import WindowTimers

    dlg = tk.Toplevel(app)
    dlg.title(TITLE)
    dlg.geometry(safe_window_geometry(
        DESIRED_WIDTH, DESIRED_HEIGHT,
        dlg.winfo_screenwidth() or 0, dlg.winfo_screenheight() or 0,
        min_w=MIN_WIDTH, min_h=MIN_HEIGHT))
    dlg.minsize(MIN_WIDTH, MIN_HEIGHT)
    app.first_use_dialog = dlg
    timers = WindowTimers(dlg)
    drive = workflow_texts.system_drive()
    spec = FIRST_USE_STEPS(drive)

    frame = ttk.Frame(dlg, padding=PADDING_DIALOGO)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text=TITLE, font=(FONTE_UI, TAMANHO_TITULO_MODAL, 'bold')).pack(anchor='w')
    intro_label = ttk.Label(frame, text=FIRST_USE_INTRO_TEXT(drive), wraplength=900)
    intro_label.pack(anchor='w', pady=(ESPACO_MINIMO, ESPACO_FINO))
    mode_label = ttk.Label(frame, text=FIRST_USE_MODE_NOTE, wraplength=900)
    mode_label.pack(anchor='w', pady=(0, ESPACO_MINIMO))
    # aviso do progresso numa linha própria (arquivo ruim, link ou erro ao salvar)
    warning_var = tk.StringVar(master=dlg, value='')
    warning_label = ttk.Label(frame, textvariable=warning_var, wraplength=900,
                              font=(FONTE_UI, TAMANHO_CORPO, 'bold'))
    warning_label.pack(fill='x', pady=(0, ESPACO_P))

    footer = ttk.Frame(frame)
    footer.pack(side='bottom', fill='x', pady=(ESPACO_P, 0))
    reset_btn = ttk.Button(footer, text='Recomeçar marcações')
    reset_btn.pack(side='left')
    close_btn = ttk.Button(footer, text='Fechar')
    close_btn.pack(side='right')

    holder = ttk.Frame(frame)
    holder.pack(fill='both', expand=True)
    canvas = tk.Canvas(holder, highlightthickness=0, borderwidth=0)
    bar = ttk.Scrollbar(holder, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    canvas.pack(side='left', fill='both', expand=True)
    bar.pack(side='right', fill='y')
    steps_box = ttk.Frame(canvas)
    window_id = canvas.create_window((0, 0), window=steps_box, anchor='nw')
    steps_box.bind('<Configure>',
                   lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',
                lambda event: canvas.itemconfigure(window_id, width=event.width))

    status_vars = {}
    buttons = {}
    step_labels = []
    for number, step in enumerate(spec, 1):
        row = ttk.Frame(steps_box, padding=(0, ESPACO_MINIMO))
        row.pack(fill='x')
        text_box = ttk.Frame(row)
        text_box.pack(side='left', fill='x', expand=True)
        ttk.Label(text_box, text=f'{number}. {step["title"]}',
                  font=(FONTE_UI, TAMANHO_CORPO, 'bold')).pack(anchor='w')
        desc = ttk.Label(text_box, text=step['text'], wraplength=560)
        desc.pack(anchor='w')
        step_labels.append(desc)
        status_vars[step['id']] = tk.StringVar(master=dlg, value=LOADING_TEXT)
        ttk.Label(row, textvariable=status_vars[step['id']], width=12).pack(
            side='left', padx=ESPACO_P)
        own = {
            'Abrir': ttk.Button(row, text='Abrir'),
            'Feito': ttk.Button(row, text='Feito'),
            'Pular': ttk.Button(row, text='Pular'),
        }
        for name in ('Abrir', 'Feito', 'Pular'):
            own[name].pack(side='left', padx=(ESPACO_MINIMO, 0))
        buttons[step['id']] = own

    def _update_wrap(event):
        if event.widget is frame and event.width > 1:
            wrap = safe_wraplength(event.width, padding=PADDING_DIALOGO)
            for label in (intro_label, mode_label, warning_label):
                label.configure(wraplength=wrap)
            for label in step_labels:
                label.configure(wraplength=max(260, wrap - 340))

    frame.bind('<Configure>', _update_wrap)

    class _View:
        def set_status(self, step_id, text):
            status_vars[step_id].set(text)

        def set_warning(self, text):
            warning_var.set(text)

        def set_ready(self, ready):
            state = '!disabled' if ready else 'disabled'
            for own in buttons.values():
                for button in own.values():
                    button.state([state])
            reset_btn.state([state])

        def after(self, ms, callback):
            return timers.after(ms, callback)

        def destroy(self):
            timers.close()
            if _alive(dlg):
                dlg.destroy()

        def warn(self, text):
            _show_close_warning(app, text)

    flow = FirstUseFlow(app, _View(), base=base, steps=spec)
    for step_id, own in buttons.items():
        own['Abrir'].configure(command=lambda s=step_id: flow.open_step(s))
        own['Feito'].configure(command=lambda s=step_id: flow.mark(s, DONE))
        own['Pular'].configure(command=lambda s=step_id: flow.mark(s, SKIPPED))
    reset_btn.configure(command=flow.reset)
    close_btn.configure(command=flow.close)
    dlg.protocol('WM_DELETE_WINDOW', flow.close)

    def on_destroy(event):
        if event.widget is not dlg:
            return
        flow.forget()
        if getattr(app, 'first_use_dialog', None) is dlg:
            app.first_use_dialog = None

    dlg.bind('<Destroy>', on_destroy, add='+')
    dlg.first_use_flow = flow
    dlg.first_use_timers = timers
    dlg.first_use_buttons = buttons
    dlg.first_use_reset = reset_btn
    dlg.first_use_close = close_btn
    dlg.first_use_status = status_vars
    dlg.first_use_warning = warning_var
    flow.start()
    return dlg
