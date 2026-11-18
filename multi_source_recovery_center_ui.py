"""Standalone Tk recovery center for synthetic multi-source backup fixtures.

There is intentionally NO import from app.py, no production disk picker, and
no real multi-disk executor. A user-supplied isolated test_root is mandatory.
Inspection is read-only; restoring requires an explicit selection and consent.
"""
from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from backup_core import human_size
from multi_source_fixture_restore import (
    _inside, recover_from_fixture_copies,
)
from multi_source_recovery_center import inspect_fixture_recovery
from selective_recovery import _any_reparse_ancestor
from ui_scale import (
    ESPACO_ENTRE_BOTOES,
    ESPACO_M,
    ESPACO_MINIMO,
    ESPACO_P,
    FONTE_UI,
    PADDING_DIALOGO,
    TAMANHO_CORPO,
    TAMANHO_SUBTITULO,
    TAMANHO_TITULO_MODAL,
    safe_window_geometry,
    safe_wraplength,
)
from ui_timers import WindowTimers

DESIRED_WIDTH = 1050
DESIRED_HEIGHT = 710
MIN_WIDTH = 750
MIN_HEIGHT = 510
PAGE_SIZE = 200

LABELS = {
    'not_verified': 'Aguardando verificação',
    'copy_verified': 'SHA-256 aprovado',
    'integrity_failed': 'Integridade reprovada',
    'manifest_invalid': 'Manifesto inválido',
    'manifest_missing': 'Manifesto ausente',
    'manifest_conflict': 'Manifestos incompatíveis',
    'not_completed_at_backup': 'Cópia não concluída',
}


def show_fixture_recovery_center(parent, plan, copies_report, *,
                                 test_root, restore_parent):
    """Open an opt-in lab-only UI. It never starts copying on opening."""
    if test_root is None:
        raise ValueError('A central exige uma raiz isolada de testes.')
    _any_reparse_ancestor(Path(test_root))
    sandbox = Path(test_root).resolve(strict=True)
    if not sandbox.is_dir():
        raise ValueError('Raiz isolada inválida.')
    _inside(sandbox, restore_parent)

    dlg = tk.Toplevel(parent)
    dlg.title('PC Restore & Optimizer — Central multidisco (SOMENTE TESTES)')
    dlg.geometry(safe_window_geometry(
        DESIRED_WIDTH,
        DESIRED_HEIGHT,
        dlg.winfo_screenwidth() or 0,
        dlg.winfo_screenheight() or 0,
        min_w=MIN_WIDTH,
        min_h=MIN_HEIGHT,
    ))
    dlg.minsize(MIN_WIDTH, MIN_HEIGHT)
    timers = WindowTimers(dlg)
    pending = Queue()
    cancelled = threading.Event()
    state = {
        'busy': False, 'closing': False,
        'inspection': None, 'selected': set(),
        'files': [], 'shown': [],
    }

    body = ttk.Frame(dlg, padding=PADDING_DIALOGO)
    body.pack(fill='both', expand=True)
    ttk.Label(
        body, text='Central de recuperação multidisco · ambiente de testes',
        font=(FONTE_UI, TAMANHO_TITULO_MODAL, 'bold'),
    ).pack(anchor='w')
    intro_label = ttk.Label(
        body, text=('Somente pastas fictícias da raiz isolada. Nenhuma formatação, '
                    'limpeza, recuperação no local original ou acesso à nuvem.'),
        wraplength=980,
    )
    intro_label.pack(anchor='w', pady=(ESPACO_MINIMO, ESPACO_P))
    status = tk.StringVar(
        master=dlg,
        value='Nenhuma verificação executada. Selecione Verificar cópias.',
    )
    status_label = ttk.Label(body, textvariable=status, wraplength=980)
    status_label.pack(fill='x', pady=(0, ESPACO_M))

    def _update_wrap(event):
        if event.widget is body and event.width > 1:
            wrap = safe_wraplength(event.width, padding=PADDING_DIALOGO)
            intro_label.configure(wraplength=wrap)
            status_label.configure(wraplength=wrap)

    body.bind('<Configure>', _update_wrap)

    ttk.Label(body, text='Cópias disponíveis', font=(FONTE_UI, TAMANHO_SUBTITULO, 'bold')
              ).pack(anchor='w', pady=(0, ESPACO_MINIMO))
    copies = ttk.Treeview(
        body, columns=('state', 'files'), show='tree headings', height=5)
    copies.heading('#0', text='Pasta de teste')
    copies.heading('state', text='Integridade')
    copies.heading('files', text='Arquivos verificados')
    copies.column('#0', width=560)
    copies.column('state', width=250)
    copies.column('files', width=150, anchor='e')
    copies.pack(fill='x', pady=(0, ESPACO_M))
    rows = copies_report.get('destinations', []) if isinstance(copies_report, dict) else []
    for i, row in enumerate(rows, 1):
        name = str(row.get('path', '(sem caminho)')) if isinstance(row, dict) else '(registro inválido)'
        copies.insert('', 'end', iid=f'copy:{i}', text=name,
                      values=('Aguardando verificação', '—'))

    header = ttk.Frame(body)
    header.pack(fill='x', pady=(0, ESPACO_MINIMO))
    ttk.Label(header, text='Arquivos selecionáveis', font=(FONTE_UI, TAMANHO_SUBTITULO, 'bold')
              ).pack(side='left')
    ttk.Label(header, text='Pesquisar:').pack(side='left', padx=(ESPACO_M, ESPACO_MINIMO))
    query = tk.StringVar(master=dlg)
    search = ttk.Entry(header, textvariable=query)
    search.pack(side='left', fill='x', expand=True)

    files_view = ttk.Treeview(
        body, columns=('chosen', 'bytes'), show='tree headings',
        height=11, selectmode='browse')
    files_view.heading('#0', text='Arquivo do plano')
    files_view.heading('chosen', text='Recuperar')
    files_view.heading('bytes', text='Tamanho')
    files_view.column('#0', width=690)
    files_view.column('chosen', width=105, anchor='center', stretch=False)
    files_view.column('bytes', width=140, anchor='e', stretch=False)

    chosen_status = tk.StringVar(master=dlg, value='Nenhum arquivo selecionado.')
    chosen_status_label = ttk.Label(body, textvariable=chosen_status)
    restored_label = ttk.Label(
        body,
        text='Resultado da última recuperação verificada',
        font=(FONTE_UI, TAMANHO_CORPO, 'bold'),
    )
    restored_view = ttk.Treeview(
        body, columns=('verification', 'copy'), show='tree headings', height=4)
    restored_view.heading('#0', text='Arquivo restaurado')
    restored_view.heading('verification', text='Integridade')
    restored_view.heading('copy', text='Cópia utilizada')
    restored_view.column('#0', width=650)
    restored_view.column('verification', width=190)
    restored_view.column('copy', width=140, anchor='center')
    actions = ttk.Frame(body)

    actions.pack(side='bottom', fill='x', pady=(ESPACO_P, 0))
    restored_view.pack(side='bottom', fill='x', pady=(ESPACO_MINIMO, ESPACO_P))
    restored_label.pack(side='bottom', anchor='w', pady=(ESPACO_P, 0))
    chosen_status_label.pack(side='bottom', anchor='w')
    files_view.pack(fill='both', expand=True, pady=(0, ESPACO_P))

    def update_restore_button():
        permitted = (not state['busy'] and state['inspection'] is not None
                     and state['inspection']['can_restore_in_fixture']
                     and bool(state['selected']))
        restore_btn.configure(state='normal' if permitted else 'disabled')
        chosen_status.set(
            f"{len(state['selected'])} arquivo(s) selecionado(s); "
            'nenhum item será recuperado sem confirmação.')

    def populate_files():
        for iid in files_view.get_children(''):
            files_view.delete(iid)
        search_text = query.get().strip().casefold()
        matching = [item for item in state['files']
                    if search_text in item['key'].casefold()]
        state['shown'] = matching[:PAGE_SIZE]
        for item in state['shown']:
            name = item['key']
            files_view.insert(
                '', 'end', iid=name, text=name,
                values=('[x]' if name in state['selected'] else '[ ]',
                        human_size(item['bytes'])))
        if len(matching) > PAGE_SIZE:
            chosen_status.set(
                f'Exibindo os primeiros {PAGE_SIZE} de {len(matching)} itens '
                '(refine a pesquisa para encontrar outros).')
        else:
            update_restore_button()

    def toggle_selected():
        if state['busy']:
            return
        chosen = files_view.selection()
        if not chosen:
            return
        key = chosen[0]
        if key in state['selected']:
            state['selected'].remove(key)
        else:
            state['selected'].add(key)
        files_view.set(key, 'chosen', '[x]' if key in state['selected'] else '[ ]')
        update_restore_button()

    def set_busy(busy):
        state['busy'] = busy
        verify_btn.configure(state='disabled' if busy else 'normal')
        toggle_btn.configure(state='disabled' if busy else 'normal')
        update_restore_button()

    def launch(kind, task):
        if state['busy']:
            return
        # Never let an older recovery result look like the outcome of a new
        # inspection or copy attempt.
        for row in restored_view.get_children(''):
            restored_view.delete(row)
        cancelled.clear()
        set_busy(True)
        status.set('Verificando SHA-256…' if kind == 'inspect'
                   else 'Restaurando somente os arquivos marcados no laboratório…')

        def worker():
            try:
                pending.put((kind, 'ok', task()))
            except InterruptedError:
                pending.put((kind, 'cancelled', None))
            except Exception as exc:
                pending.put((kind, 'error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def verify():
        if state['busy']:
            return
        state['inspection'] = None
        update_restore_button()
        launch(
            'inspect',
            lambda: inspect_fixture_recovery(
                plan, copies_report, restore_parent,
                test_root=str(sandbox), cancelled=cancelled))

    def restore():
        if state['busy'] or state['inspection'] is None:
            return
        if not state['inspection']['can_restore_in_fixture']:
            return
        keys = sorted(state['selected'])
        if not keys:
            return
        if not messagebox.askyesno(
            'Confirmar ensaio isolado',
            f'Recuperar {len(keys)} arquivo(s) para uma NOVA pasta de teste '
            f'dentro de:\n{restore_parent}?\n\n'
            'Nenhum original será substituído ou apagado.',
            parent=dlg,
        ):
            return
        launch(
            'restore',
            lambda: recover_from_fixture_copies(
                plan, copies_report, keys, restore_parent,
                test_root=str(sandbox), cancelled=cancelled))

    verify_btn = ttk.Button(actions, text='Verificar cópias (SHA-256)',
                            command=verify)
    verify_btn.pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    toggle_btn = ttk.Button(actions, text='Marcar/desmarcar arquivo',
                            command=toggle_selected)
    toggle_btn.pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    restore_btn = ttk.Button(actions, text='Restaurar selecionados (TESTE)',
                             command=restore, state='disabled')
    restore_btn.pack(side='left')
    ttk.Button(actions, text='Cancelar / Fechar',
               command=lambda: close()).pack(side='right')

    def handle_result(kind, outcome, value):
        set_busy(False)
        if outcome == 'cancelled':
            status.set('Operação interrompida; nenhuma restauração foi aprovada.')
        elif outcome == 'error':
            status.set(f'Operação bloqueada: {value}')
        elif kind == 'inspect':
            state['inspection'] = value
            state['files'] = value['files']
            for record in value['copies']:
                copies.set(
                    f"copy:{record['copy_index']}", 'state',
                    LABELS.get(record['status'], record['status']))
                copies.set(f"copy:{record['copy_index']}", 'files',
                           str(record['files_verified']))
            populate_files()
            if value['status'] == 'manifest_conflict':
                status.set('BLOQUEADO: manifestos divergentes. Nenhuma recuperação permitida.')
            elif value['can_restore_in_fixture']:
                status.set(
                    f"{value['copies_verified']} de {value['copies_checked']} "
                    'cópia(s) SHA-256 aprovada(s). Marque os arquivos desejados.')
            else:
                status.set('Nenhuma cópia íntegra disponível para recuperar.')
        else:
            if (value['status'] == 'restored_verified'
                    and value['restore_verified']
                    and value['files_restored'] == len(value.get('restored_files', []))):
                for item in value['restored_files']:
                    restored_view.insert(
                        '', 'end', text=item['key'],
                        values=('SHA-256 aprovado', f"#{item['copy_index']}"))
                status.set(
                    f"Recuperados e verificados {value['files_restored']} arquivo(s) "
                    f"da cópia #{value['chosen_copy_index']}. "
                    f"Pasta de testes: {value['restored_folder']}")
            else:
                status.set('Recuperação não aprovada; verifique os arquivos de teste.')
        update_restore_button()

    def poll():
        if timers.closed:
            return
        for _ in range(8):
            try:
                kind, outcome, value = pending.get_nowait()
            except Empty:
                break
            if state['closing']:
                state['busy'] = False
                dlg.destroy()
                return
            handle_result(kind, outcome, value)
        if not timers.closed:
            timers.after(100, poll)

    def close():
        if state['busy']:
            state['closing'] = True
            cancelled.set()
            status.set('Aguardando cancelamento da tarefa para fechar com segurança…')
        else:
            dlg.destroy()

    files_view.bind('<Double-1>', lambda _event: toggle_selected(), add='+')
    query.trace_add('write', lambda *_: populate_files())
    dlg.protocol('WM_DELETE_WINDOW', close)
    timers.after(100, poll)
    return dlg
