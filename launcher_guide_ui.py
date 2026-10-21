"""P2-05: janela "Launchers de jogos" (somente leitura).

Mostra onde estão as bibliotecas de Steam, Epic, EA, Ubisoft, Riot e Rockstar
e o passo a passo para religá-las depois de formatar. Esta janela não abre
launchers nem pastas e não executa nada: só lê nomes de pastas (em segundo
plano, pelo game_launchers.detect_launchers) e mostra texto.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from game_launchers import (SYSTEM_DRIVE_WARNING, UNKNOWN_SYSTEM_DRIVE_WARNING,
                            detect_launchers, guide_for)
from restore_jobs import Job
from ui_timers import WindowTimers

INTRO_TEXT = (
    'O aplicativo procura, só olhando nomes de pastas, as bibliotecas de jogos da Steam, '
    'Epic Games, EA app, Ubisoft Connect, Riot Games e Rockstar Games em todas as unidades '
    'deste computador. Nada é alterado, aberto ou apagado. Clique numa linha para ver como '
    'religar a biblioteca depois de formatar. Jogos guardados numa unidade que NÃO vai ser '
    'formatada continuam lá e podem ser aproveitados.'
)
EMPTY_TEXT = 'Nenhuma biblioteca de jogos foi encontrada nas unidades deste computador.'


def _drive_note(lib):
    on_system = lib.get('on_system_drive', False)
    if on_system is None:
        return 'Confira'  # não deu para confirmar o disco do Windows
    return 'Disco do Windows' if on_system else ''


def show_launchers(parent, *, roots=None, scanner=None):
    # scanner(roots, cancelled) -> resultado de detect_launchers
    scan = scanner or (lambda chosen_roots, cancelled: detect_launchers(
        chosen_roots, cancelled=cancelled))
    dlg = tk.Toplevel(parent)
    dlg.title('Launchers de jogos')
    dlg.geometry('960x620')
    dlg.minsize(640, 440)
    timers = WindowTimers(dlg)
    state = {'libraries': [], 'busy': False, 'result': None, 'job': None}
    dlg.launcher_state = state

    frame = ttk.Frame(dlg, padding=14)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Bibliotecas de jogos encontradas',
              font=('Segoe UI', 12, 'bold')).pack(anchor='w')
    ttk.Label(frame, wraplength=900, text=INTRO_TEXT).pack(anchor='w', pady=(4, 6))
    status = tk.StringVar(master=dlg, value='')
    dlg.launcher_status = status
    ttk.Label(frame, textvariable=status, wraplength=900).pack(fill='x', pady=(0, 2))
    warning = tk.StringVar(master=dlg, value='')
    dlg.launcher_warning = warning  # aviso fica visível mesmo depois de copiar um caminho
    ttk.Label(frame, textvariable=warning, wraplength=900,
              font=('Segoe UI', 10, 'bold')).pack(fill='x', pady=(0, 6))

    grid = ttk.Frame(frame)
    grid.pack(fill='both', expand=True)
    tree = ttk.Treeview(grid, columns=('path', 'games', 'confidence', 'warning'),
                        show='tree headings',
                        selectmode='browse', height=8)
    tree.heading('#0', text='Launcher')
    tree.heading('path', text='Pasta')
    tree.heading('games', text='Jogos')
    tree.heading('confidence', text='Confiança')
    tree.heading('warning', text='Aviso')
    tree.column('#0', width=150, stretch=False)
    tree.column('path', width=420, stretch=True)
    tree.column('games', width=70, anchor='center', stretch=False)
    tree.column('confidence', width=90, anchor='center', stretch=False)
    tree.column('warning', width=130, anchor='center', stretch=False)
    bar = ttk.Scrollbar(grid, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.grid(row=0, column=0, sticky='nsew')
    bar.grid(row=0, column=1, sticky='ns')
    grid.rowconfigure(0, weight=1)
    grid.columnconfigure(0, weight=1)

    guide = tk.Text(frame, height=11, wrap='word')
    guide.pack(fill='both', expand=True, pady=(8, 6))

    def show_guide(text):
        guide.configure(state='normal')
        guide.delete('1.0', 'end')
        guide.insert('1.0', text)
        guide.configure(state='disabled')  # só leitura

    show_guide('Selecione uma biblioteca na tabela para ver o passo a passo.')

    def current():
        ids = tree.selection()
        if not ids or not ids[0].startswith('lib:'):
            return None
        index = int(ids[0][4:])
        libraries = state['libraries']
        return libraries[index] if index < len(libraries) else None

    def on_select(_event=None):
        lib = current()
        if lib is None:
            return
        text = guide_for(lib['launcher'], lib['path'])
        if lib.get('on_system_drive'):
            text = SYSTEM_DRIVE_WARNING + '\n\n' + text
        elif lib.get('on_system_drive', False) is None:
            text = UNKNOWN_SYSTEM_DRIVE_WARNING + '\n\n' + text
        if lib['games']:
            text += '\n\nJogos encontrados: ' + ', '.join(lib['games'])
        if lib['confidence'] != 'alta':
            text += ('\n\nConfiança "provável": a pasta tem o nome usado pelo launcher, '
                     'mas o aplicativo não achou um arquivo que confirme.')
        show_guide(text)

    tree.bind('<<TreeviewSelect>>', on_select, add='+')

    def copy_path():
        lib = current()
        if lib is None:
            status.set('Clique numa linha da tabela e depois em "Copiar caminho".')
            return
        dlg.clipboard_clear()
        dlg.clipboard_append(lib['path'])
        status.set(f'Caminho copiado: {lib["path"]}')

    def update_buttons():
        again_button.state(['disabled'] if state['busy'] else ['!disabled'])

    def loaded(result):
        libraries = list(result.get('libraries', []))
        state['libraries'] = libraries
        state['result'] = result
        for index, lib in enumerate(libraries):
            tree.insert('', 'end', iid=f'lib:{index}', text=lib['launcher'],
                        values=(lib['path'], len(lib['games']), lib['confidence'],
                                _drive_note(lib)))
        text = (f'{len(libraries)} biblioteca(s) encontrada(s).' if libraries else EMPTY_TEXT)
        warnings = list(result.get('warnings', []))
        if result.get('truncated') and not warnings:
            warnings.append('A busca parou antes do fim; pode haver bibliotecas que não apareceram.')
        warning.set(('Atenção: ' + ' '.join(warnings)) if warnings else '')
        status.set(text)

    def wait_job(job, done):
        def poll():
            result = job.poll()
            if result is None:
                timers.after(150, poll)
                return
            done(*result)
        timers.after(10, poll)

    def search():
        if state['busy']:
            return
        state['busy'] = True
        tree.delete(*tree.get_children(''))
        state['libraries'] = []
        warning.set('')
        show_guide('Selecione uma biblioteca na tabela para ver o passo a passo.')
        status.set('Procurando bibliotecas de jogos nas unidades… (só leitura)')
        update_buttons()
        job = Job(lambda cancelled, progress: scan(roots, cancelled))
        state['job'] = job

        def finished(kind, value):
            state['busy'] = False
            if kind == 'done':
                loaded(value)
            else:
                status.set('Não foi possível concluir a busca. Nada foi alterado. '
                           'Tente "Pesquisar de novo".')
            update_buttons()

        wait_job(job, finished)

    tools = ttk.Frame(frame)
    tools.pack(fill='x')
    again_button = ttk.Button(tools, text='Pesquisar de novo', command=search)
    again_button.pack(side='left')
    ttk.Button(tools, text='Copiar caminho', command=copy_path).pack(side='left', padx=(7, 0))
    ttk.Button(tools, text='Fechar', command=dlg.destroy).pack(side='right')

    def on_destroy(event):
        # fechar a janela pede para a busca parar (checado a cada pasta)
        if event.widget is dlg and state['job'] is not None:
            state['job'].cancelled.set()

    dlg.bind('<Destroy>', on_destroy, add='+')

    search()
    return dlg
