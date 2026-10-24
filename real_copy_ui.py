"""P2-09 fatia 3b-2: janela "Cópia protegida para outro disco" (Tk fino).

A tela só conversa com o RealCopyFlow (real_copy_flow.py), que ordena as
etapas e faz todas as conferências:

1. a pessoa escolhe as pastas de origem e de destino;
2. "Ler discos" monta a lista de arquivos (só leitura, num Job) e mostra o
   aviso antes da consulta dos discos;
3. "Sim, pode ler" lê a lista de discos (num Job) e mostra a prévia; "Não"
   volta ao começo sem ler nada;
4. "Confirmo esta cópia" transforma a resposta em confirmação;
5. "Copiar agora" copia e confere (num Job); "Cancelar" pede para parar.

As etapas que podem esperar rodam num Job e voltam ao Tk por
WindowTimers.after (regra R-10). Fechar a janela pede para parar o que está
rodando e invalida a confirmação. A tela mostra só os textos do fluxo
(mensagem, prévia e relatório) e os textos fixos daqui: nunca a mensagem
original de um erro nem caminhos (podem ter o nome de usuário).
A origem só é lida; nada aqui formata, apaga ou instala.
"""
from __future__ import annotations

import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import diagnostics
import real_copy_flow as rcf
from multi_source_plan import prepare_multi_source_preview
from multi_source_targets import preview_multi_source_targets
from restore_jobs import Job
from ui_timers import WindowTimers
from volume_paths import volume_of

TITLE = 'Cópia protegida para outro disco'
INTRO_TEXT = (
    'Copie pastas para outro disco, com conferência de cada arquivo (SHA-256). A origem '
    'só é lida: nada nela é gravado, apagado ou formatado. Antes de copiar, o aplicativo '
    'lê a lista de discos (só leitura) para conferir que o destino fica em outro disco, '
    'mostra uma prévia e só copia depois que você confirmar.')
MSG_ESCOLHA = ('Escolha ao menos uma pasta de origem e uma pasta de destino (em outro '
               'disco, fora do C:). Depois clique em "Ler discos".')
MSG_MONTANDO = 'Montando a lista de arquivos das origens… (só leitura)'
MSG_PLANO_FALHOU = (
    'Não deu para montar a lista de arquivos. Confira se as pastas existem, se o destino '
    'fica em outra unidade, fora das origens, e se há espaço livre. Nada foi gravado.')
MSG_NAO_LER = 'A lista de discos não foi lida. Nada foi gravado.'
MSG_LENDO = 'Lendo a lista de discos… (só leitura)'
MSG_PREVIA_PRONTA = ('Confira a prévia abaixo. Se estiver tudo certo, clique em '
                     '"Confirmo esta cópia".')
MSG_CONFIRMADO = ('Confirmado. Clique em "Copiar agora" (a confirmação vale por '
                  '5 minutos e só para esta prévia).')
MSG_COPIANDO = 'Copiando e conferindo… Você pode cancelar a qualquer momento.'
MSG_PARANDO = 'Parando… aguarde.'
MSG_CONCLUIDO = 'Cópia feita e conferida (SHA-256) em todos os destinos.'
MSG_OCUPADO = 'Aguarde: uma etapa ainda está em andamento.'

BUTTONS = ('Adicionar origem', 'Adicionar destino', 'Limpar escolhas', 'Ler discos',
           'Sim, pode ler', 'Não', 'Confirmo esta cópia', 'Copiar agora', 'Cancelar')


def _ask_folder(parent, title):
    path = filedialog.askdirectory(parent=parent, title=title, mustexist=True)
    return str(Path(path)) if path else None


def _drives(paths):
    drives = sorted({Path(p).drive.upper() for p in paths
                     if len(Path(p).drive) == 2 and Path(p).drive[1] == ':'})
    return f' (unidade(s) {", ".join(drives)})' if drives else ''


def show_real_copy(app, *, collector=None, ask_folder=None, volume_lookup=None,
                   usage=None):
    """Abre a janela (uma por vez).

    collector() -> inventário dos discos (padrão: diagnostics.disk_inventory);
    só o RealCopyFlow o chama, e só depois de confirm_disk_check(True).
    ask_folder(janela, título) -> caminho escolhido ou None.
    """
    previous = getattr(app, 'real_copy_dialog', None)
    if previous is not None:
        try:
            alive = previous.winfo_exists()
        except tk.TclError:
            alive = False
        if alive:
            previous.deiconify()
            previous.lift()
            return previous
    disk_collector = collector or diagnostics.disk_inventory
    choose = ask_folder or _ask_folder
    lookup = volume_lookup or volume_of
    space = usage or shutil.disk_usage

    dlg = tk.Toplevel(app)
    app.real_copy_dialog = dlg
    dlg.title(TITLE)
    dlg.geometry('900x640')
    dlg.minsize(680, 460)
    timers = WindowTimers(dlg)
    dlg.real_copy_timers = timers
    # stopping: a pessoa clicou em "Cancelar" depois que a etapa começou.
    state = {'sources': [], 'targets': [], 'flow': None, 'job': None, 'busy': False,
             'stopping': False}
    dlg.real_copy_state = state

    frame = ttk.Frame(dlg, padding=14)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text=TITLE, font=('Segoe UI', 12, 'bold')).pack(anchor='w')
    ttk.Label(frame, wraplength=850, text=INTRO_TEXT).pack(anchor='w', pady=(4, 8))

    choices = tk.StringVar(master=dlg, value='')
    dlg.real_copy_choices = choices
    ttk.Label(frame, textvariable=choices, wraplength=850,
              justify='left').pack(fill='x', pady=(0, 4))
    status = tk.StringVar(master=dlg, value=MSG_ESCOLHA)
    dlg.real_copy_status = status
    ttk.Label(frame, textvariable=status, wraplength=850, justify='left',
              font=('Segoe UI', 10, 'bold')).pack(fill='x', pady=(0, 6))

    box = ttk.Frame(frame)
    box.pack(fill='both', expand=True)
    text = tk.Text(box, wrap='word', height=16, state='disabled')
    bar = ttk.Scrollbar(box, orient='vertical', command=text.yview)
    text.configure(yscrollcommand=bar.set)
    text.pack(side='left', fill='both', expand=True)
    bar.pack(side='right', fill='y')

    def show_text(value):
        text.configure(state='normal')
        text.delete('1.0', 'end')
        if value:
            text.insert('1.0', value)
        text.configure(state='disabled')

    dlg.real_copy_text = lambda: text.get('1.0', 'end-1c')

    def flow_state():
        flow = state['flow']
        return flow.state if flow is not None else None

    def update_choices():
        sources, targets = state['sources'], state['targets']
        choices.set(f'Origens escolhidas: {len(sources)} pasta(s){_drives(sources)}.\n'
                    f'Destinos escolhidos: {len(targets)} pasta(s){_drives(targets)}.')

    def update_buttons():
        busy = state['busy']
        current = flow_state()
        waiting = current in (rcf.AVISO_CONSULTA, rcf.PREVIA, rcf.CONFIRMADO)
        enabled = {
            'Adicionar origem': not busy,
            'Adicionar destino': not busy,
            'Limpar escolhas': not busy,
            'Ler discos': (not busy and bool(state['sources'])
                           and bool(state['targets'])),
            'Sim, pode ler': not busy and current == rcf.AVISO_CONSULTA,
            'Não': not busy and current == rcf.AVISO_CONSULTA,
            'Confirmo esta cópia': not busy and current == rcf.PREVIA,
            'Copiar agora': not busy and current == rcf.CONFIRMADO,
            'Cancelar': busy or waiting,
        }
        for name, button in buttons.items():
            button.state(['!disabled'] if enabled[name] else ['disabled'])

    def forget_flow():
        flow = state['flow']
        state['flow'] = None
        if flow is not None:
            flow.cancel()  # invalida a confirmação que existir

    def wait_job(job, done, while_running=None):
        def poll():
            result = job.poll()
            if result is None:
                if while_running is not None:
                    while_running(job.latest)
                timers.after(150, poll)
                return
            done(*result)
        timers.after(10, poll)

    def start(work, done, message, while_running=None):
        state['busy'] = True
        state['stopping'] = False
        status.set(message)
        update_buttons()
        job = Job(work)
        state['job'] = job

        def finished(kind, value):
            state['busy'] = False
            state['job'] = None
            if state['stopping']:
                stopped()
            else:
                done(kind, value)
            state['stopping'] = False
            update_buttons()

        wait_job(job, finished, while_running)

    def stopped():
        """A etapa terminou depois de um "Cancelar".

        Montagem da lista ou leitura dos discos: nada continua (não aparece
        aviso nem prévia). Cópia: o relatório diz como ela terminou.
        """
        flow = state['flow']
        if flow is not None and flow.state in (rcf.CONCLUIDO, rcf.INCOMPLETO):
            show_flow(MSG_CONCLUIDO)
            return
        forget_flow()
        show_text('')
        status.set(rcf.CANCELADO)

    def show_flow(default=None):
        flow = state['flow']
        if flow is None:
            return
        if flow.state in (rcf.PREVIA, rcf.CONFIRMADO):
            show_text(flow.preview_text())
        elif flow.state in (rcf.CONCLUIDO, rcf.INCOMPLETO):
            show_text(flow.report or '')
        else:
            show_text('')
        status.set(flow.message or default or '')

    # -- escolhas ---------------------------------------------------------
    def add(kind, title):
        if state['busy']:
            return
        chosen = choose(dlg, title)
        if not chosen:
            return
        chosen = str(Path(chosen))
        if chosen not in state[kind]:
            state[kind].append(chosen)
        forget_flow()
        show_text('')
        status.set(MSG_ESCOLHA)
        update_choices()
        update_buttons()

    def clear():
        if state['busy']:
            return
        state['sources'].clear()
        state['targets'].clear()
        forget_flow()
        show_text('')
        status.set(MSG_ESCOLHA)
        update_choices()
        update_buttons()

    # -- etapas -----------------------------------------------------------
    def read_disks():
        if state['busy'] or not state['sources'] or not state['targets']:
            return
        forget_flow()
        show_text('')
        sources = list(state['sources'])
        targets = list(state['targets'])

        def build(cancelled, progress):
            roots = sorted({str(Path(item).parent) for item in sources})
            plan = prepare_multi_source_preview(sources, roots, cancelled=cancelled)
            preview = preview_multi_source_targets(plan, targets, usage=space,
                                                   volume_lookup=lookup)
            return plan, preview

        def done(kind, value):
            if kind != 'done':
                # Nunca mostra a mensagem original (pode ter caminho).
                status.set(rcf.CANCELADO if kind == 'cancelled' else MSG_PLANO_FALHOU)
                return
            plan, preview = value
            flow = rcf.RealCopyFlow(plan, preview, volume_lookup=lookup, usage=space,
                                    disk_collector=disk_collector)
            state['flow'] = flow
            flow.request_disk_check()
            show_flow()

        start(build, done, MSG_MONTANDO)

    def answer_yes():
        flow = state['flow']
        if state['busy'] or flow is None or flow.state != rcf.AVISO_CONSULTA:
            return

        def done(kind, value):
            if kind != 'done':
                status.set(rcf.MSG_INESPERADO)
                return
            if value == rcf.OCUPADO:
                status.set(MSG_OCUPADO)
                return
            show_flow(MSG_PREVIA_PRONTA)

        start(lambda cancelled, progress: flow.confirm_disk_check(True), done, MSG_LENDO)

    def answer_no():
        flow = state['flow']
        if state['busy'] or flow is None:
            return
        flow.confirm_disk_check(False)  # volta ao começo sem ler nada
        show_text('')
        status.set(MSG_NAO_LER)
        update_buttons()

    def confirm():
        flow = state['flow']
        if state['busy'] or flow is None:
            return
        flow.confirm_copy(True)
        show_flow(MSG_CONFIRMADO)
        update_buttons()

    def copy_now():
        flow = state['flow']
        if state['busy'] or flow is None or flow.state != rcf.CONFIRMADO:
            return
        total = len(state['targets'])

        def running(latest):
            if flow.cancel_event.is_set():
                status.set(MSG_PARANDO)
            elif latest and isinstance(latest[0], int):
                status.set(f'{MSG_COPIANDO} (destino {latest[0]} de {total})')

        def done(kind, value):
            if kind != 'done':
                status.set(rcf.MSG_INESPERADO)
                return
            if value == rcf.OCUPADO:
                status.set(MSG_OCUPADO)
                return
            show_flow(MSG_CONCLUIDO)

        start(lambda cancelled, progress: flow.run(progress=progress), done,
              MSG_COPIANDO, running)

    def cancel():
        flow = state['flow']
        job = state['job']
        if job is not None:
            job.cancelled.set()
        if state['busy']:
            # A etapa em andamento termina sozinha; o resultado vem depois.
            state['stopping'] = True
            if flow is not None:
                flow.cancel()
            status.set(MSG_PARANDO)
            update_buttons()
            return
        if flow is not None:
            flow.cancel()
        show_text('')
        status.set(rcf.CANCELADO)
        update_buttons()

    tools = ttk.Frame(frame)
    tools.pack(fill='x', pady=(8, 0))
    actions = ttk.Frame(frame)
    actions.pack(fill='x', pady=(6, 0))
    commands = {
        'Adicionar origem': lambda: add('sources', 'Pasta de origem (só será lida)'),
        'Adicionar destino': lambda: add('targets', 'Pasta de destino (em outro disco)'),
        'Limpar escolhas': clear,
        'Ler discos': read_disks,
        'Sim, pode ler': answer_yes,
        'Não': answer_no,
        'Confirmo esta cópia': confirm,
        'Copiar agora': copy_now,
        'Cancelar': cancel,
    }
    buttons = {}
    for name in BUTTONS:
        parent = tools if name in ('Adicionar origem', 'Adicionar destino',
                                   'Limpar escolhas') else actions
        button = ttk.Button(parent, text=name, command=commands[name])
        button.pack(side='left', padx=(0, 7))
        buttons[name] = button
    ttk.Button(tools, text='Fechar', command=dlg.destroy).pack(side='right')
    dlg.real_copy_buttons = buttons

    def on_destroy(event):
        if event.widget is not dlg:
            return
        if getattr(app, 'real_copy_dialog', None) is dlg:
            app.real_copy_dialog = None
        if state['job'] is not None:
            state['job'].cancelled.set()
        if state['flow'] is not None:
            # Pede para parar o que está rodando e invalida a confirmação.
            state['flow'].close()

    dlg.bind('<Destroy>', on_destroy, add='+')
    update_choices()
    update_buttons()
    return dlg
