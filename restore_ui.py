"""v0.5.19: grouped, lazy and persistent-selection backup restoration.

Only this restoration dialog is changed. It uses existing verified manifest keys
and delegates all disk operations to the unchanged restore_selected function.
"""
from __future__ import annotations

import tkinter as tk
import json
import time
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from backup_features import verified_entries, restore_selected, resume_information
from backup_core import human_size
from transfer_engine import time_text, TransferMeter
from restore_groups import PAGE_SIZE, build_restore_index, sorted_children
from restore_jobs import Job
from ui_timers import WindowTimers


def show_restore(app, manifest, small=False):
    if app.busy:
        messagebox.showinfo('Operação em andamento', 'Aguarde a operação atual terminar.')
        return
    previous = getattr(app, 'restore_dialog', None)
    if previous is not None and previous.winfo_exists():
        previous.lift()
        return

    dlg = tk.Toplevel(app)
    app.restore_dialog = dlg
    timers = WindowTimers(dlg)
    dlg.title('Restauração organizada por jogo, aplicativo e pasta · v0.5.19')
    dlg.geometry('1130x740')
    dlg.minsize(800, 500)

    frame = ttk.Frame(dlg, padding=14)
    frame.pack(fill='both', expand=True)
    status = tk.StringVar(value='Lendo arquivos verificados em segundo plano…')
    selected_text = tk.StringVar(value='Nenhum arquivo marcado para restaurar.')
    hint = tk.StringVar(value='Abra um grupo para visualizar seus itens. Clique em [ ] para marcar uma pasta inteira.')
    state = dict(job=None, index=None, selected=set(), hits={}, busy=True,
                 shown={}, after=None, small=small, started=None, meter=None, active_keys=None, prefix=None)

    ttk.Label(frame, text='Restauração organizada — sem substituir arquivos originais',
              font=('Segoe UI', 13, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Marque jogos, categorias, pastas ou arquivos. A seleção permanece ao pesquisar e navegar.',
              wraplength=1080).pack(anchor='w', pady=(5, 2))
    ttk.Label(frame, textvariable=status, wraplength=1080).pack(fill='x', pady=(5, 6))
    progress_bar = ttk.Progressbar(frame, mode='indeterminate')
    progress_bar.pack(fill='x', pady=(0, 8))
    progress_bar.start(15)

    filter_area = ttk.Frame(frame)
    filter_area.pack(fill='x', pady=4)
    ttk.Label(filter_area, text='Pesquisar jogo, pasta ou arquivo:').pack(side='left', padx=(0, 8))
    query = tk.StringVar()
    field = ttk.Entry(filter_area, textvariable=query)
    field.pack(side='left', fill='x', expand=True)

    grid = ttk.Frame(frame)
    grid.pack(fill='both', expand=True, pady=8)
    tree = ttk.Treeview(grid, columns=('mark', 'count', 'size'), show='tree headings', selectmode='browse')
    tree.heading('#0', text='Jogos, aplicativos, categorias e arquivos')
    tree.heading('mark', text='Restaurar')
    tree.heading('count', text='Exibidos / total')
    tree.heading('size', text='Tamanho')
    tree.column('#0', width=660, minwidth=300, stretch=True)
    tree.column('mark', width=105, minwidth=90, stretch=False, anchor='center')
    tree.column('count', width=140, minwidth=120, stretch=False, anchor='e')
    tree.column('size', width=120, minwidth=100, stretch=False, anchor='e')
    scrollbar_y = ttk.Scrollbar(grid, orient='vertical', command=tree.yview)
    scrollbar_x = ttk.Scrollbar(grid, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
    tree.grid(row=0, column=0, sticky='nsew')
    scrollbar_y.grid(row=0, column=1, sticky='ns')
    scrollbar_x.grid(row=1, column=0, sticky='ew')
    grid.rowconfigure(0, weight=1)
    grid.columnconfigure(0, weight=1)

    ttk.Label(frame, textvariable=hint, wraplength=1080).pack(fill='x')
    ttk.Label(frame, textvariable=selected_text, font=('Segoe UI', 10, 'bold')).pack(fill='x', pady=(5, 4))

    tools = ttk.Frame(frame)
    tools.pack(fill='x', pady=(0, 7))
    actions = ttk.Frame(frame)
    actions.pack(fill='x')

    def node_for(iid):
        if not iid.isdigit() or state['index'] is None:
            return None
        return state['index'].nodes.get(int(iid))

    def marker(node):
        selected = state['selected']
        count = sum(key in selected for key in node.keys)
        return '[x]' if node.count and count == node.count else ('[-]' if count else '[ ]')

    def show_selection():
        index = state['index']
        if index is None:
            return
        keys = state['selected']
        total = sum(index.bytes_by_key[k] for k in keys)
        selected_text.set(f'{len(keys):,} arquivo(s) marcado(s) · {human_size(total)} · seleção mantida ao filtrar'.replace(',', '.'))

    def update_visible_marks():
        def visit(parent):
            for iid in tree.get_children(parent):
                node = node_for(iid)
                if node is not None:
                    tree.set(iid, 'mark', marker(node))
                visit(iid)
        visit('')
        show_selection()

    def add_node(parent_iid, node):
        count = state['hits'].get(node.uid, 0)
        if not count:
            return
        iid = str(node.uid)
        if tree.exists(iid):
            return
        tree.insert(parent_iid, 'end', iid=iid, text=node.name,
                    values=(marker(node),
                            (f'{count:,}/{node.count:,}' if count != node.count else f'{node.count:,}').replace(',', '.'),
                            human_size(node.bytes)))
        if any(state['hits'].get(c.uid, 0) for c in node.children.values()):
            tree.insert(iid, 'end', iid=f'placeholder:{node.uid}', text='Abrir para ver os itens…')

    def populate(node):
        parent_iid = '' if node.kind == 'root' else str(node.uid)
        placeholder = f'placeholder:{node.uid}'
        more = f'more:{node.uid}'
        if tree.exists(placeholder):
            tree.delete(placeholder)
        if tree.exists(more):
            tree.delete(more)
        matching = [c for c in sorted_children(node) if state['hits'].get(c.uid, 0)]
        previous = state['shown'].get(node.uid, 0)
        desired = min(len(matching), previous + PAGE_SIZE)
        for child in matching[previous:desired]:
            add_node(parent_iid, child)
        state['shown'][node.uid] = desired
        if desired < len(matching):
            tree.insert(parent_iid, 'end', iid=more,
                        text=f'⋯ Mostrar mais {min(PAGE_SIZE, len(matching) - desired)} itens nesta pasta',
                        values=('', f'{desired:,}/{len(matching):,}'.replace(',', '.'), ''))

    def render_root():
        tree.delete(*tree.get_children(''))
        state['shown'].clear()
        if state['index'] is None:
            return
        populate(state['index'].root)
        visible = state['hits'].get(0, 0)
        hint.set(f'{visible:,} arquivo(s) encontrados em grupos. Abra um grupo com a seta; '
                 'clique na coluna Restaurar para marcar todos os seus arquivos.'.replace(',', '.'))
        show_selection()

    def apply_filter():
        state['after'] = None
        if state['busy'] or state['index'] is None:
            return
        state['hits'] = state['index'].search_counts(query.get())
        render_root()

    def schedule_filter(*_):
        if state['after'] is not None:
            timers.cancel(state['after'])
        state['after'] = timers.after(250, apply_filter)

    query.trace_add('write', schedule_filter)

    def toggle(node, select=None):
        if state['busy'] or node is None:
            return
        selected = state['selected']
        if select is None:
            select = not all(key in selected for key in node.keys)
        if select:
            selected.update(node.keys)
        else:
            selected.difference_update(node.keys)
        update_visible_marks()

    def current_node():
        ids = tree.selection()
        return node_for(ids[0]) if ids else None

    def on_open(_):
        node = node_for(tree.focus())
        if node is not None and node.uid not in state['shown']:
            populate(node)

    def on_click(event):
        iid = tree.identify_row(event.y)
        if tree.identify_column(event.x) == '#1' and node_for(iid) is not None:
            tree.selection_set(iid)
            toggle(node_for(iid))
            return 'break'

    def on_double(event):
        iid = tree.identify_row(event.y)
        if iid.startswith('more:'):
            idx = state['index']
            if idx is not None:
                populate(idx.nodes[int(iid.partition(':')[2])])
            return 'break'
        if tree.identify_column(event.x) == '#1':
            return 'break'  # avoid twice-toggling the checkbox after a click
        node = node_for(iid)
        if node is not None and node.kind == 'file':
            toggle(node)
            return 'break'

    def on_enter(_):
        ids = tree.selection()
        if not ids:
            return
        iid = ids[0]
        if iid.startswith('more:'):
            populate(state['index'].nodes[int(iid.partition(':')[2])])
        else:
            toggle(node_for(iid))

    tree.bind('<<TreeviewOpen>>', on_open)
    tree.bind('<Button-1>', on_click)
    tree.bind('<Double-1>', on_double)
    tree.bind('<Return>', on_enter)
    ttk.Button(tools, text='Marcar grupo / item', command=lambda: toggle(current_node(), True)).pack(side='left', padx=(0, 7))
    ttk.Button(tools, text='Desmarcar grupo / item', command=lambda: toggle(current_node(), False)).pack(side='left', padx=(0, 7))
    ttk.Button(tools, text='Limpar seleção', command=lambda: clear_selection()).pack(side='left')

    def clear_selection():
        if state['busy']:
            return
        state['selected'].clear()
        update_visible_marks()

    def set_busy(value):
        state['busy'] = value
        app.busy = value
        restore_button.configure(state='disabled' if value else 'normal')
        field.configure(state='disabled' if value else 'normal')
        cancel_button.configure(state='normal' if value else 'disabled')
        if value and state['meter'] is None:
            progress_bar.start(15)
        elif not value:
            progress_bar.stop()

    def poll(done):
        if not dlg.winfo_exists():
            return
        job = state['job']
        if job.latest:
            detail = job.latest
            if len(detail) == 6:
                phase, n, total, path, copied, size = detail
                if state['meter'] is not None and state['prefix'] is not None:
                    done_bytes = state['prefix'][min(n,len(state['prefix'])-1)]
                    if phase=='Copiando':
                        done_bytes += copied
                    stat=state['meter'].snapshot(bytes_done=done_bytes,files_done=n)
                    pct=100*done_bytes/max(1,state['meter'].total_bytes)
                    progress_bar.configure(value=min(100,pct))
                    status.set(f'{phase} · {n}/{total} arquivos · {human_size(done_bytes)}/{human_size(state["meter"].total_bytes)}\n'
                        f'Tempo {time_text(stat["elapsed_sec"])} · {stat["bytes_per_sec"]/1024**2:.1f} MiB/s · '
                        f'{stat["files_per_sec"]:.1f} arquivos/s · restante ~{time_text(stat["remaining_sec"])}\n{path}')
                else:
                    status.set(f'{phase} · {n}/{total} arquivo(s) · {copied:,}/{size:,} bytes no arquivo atual\n{path}')
        result = job.poll()
        if result is None:
            timers.after(90, lambda: poll(done))
            return
        set_busy(False)
        kind, value = result
        if kind == 'done':
            done(value)
        elif kind == 'cancelled':
            status.set('Cancelada. O backup original não foi alterado.')
            messagebox.showinfo('Restauração cancelada', value, parent=dlg)
        else:
            status.set('Operação não concluída. Consulte a mensagem.')
            messagebox.showerror('Restauração não concluída', value, parent=dlg)

    def start_job(chosen, destination, resume_from=None):
        state['active_keys']=chosen
        sizes=state['index'].bytes_by_key
        state['prefix']=[0]
        for key in chosen:
            state['prefix'].append(state['prefix'][-1]+sizes[key])
        state['meter']=TransferMeter(state['prefix'][-1],len(chosen))
        progress_bar.stop()
        progress_bar.configure(mode='determinate',maximum=100,value=0)
        set_busy(True)
        status.set('Preparando restauração…')
        state['job']=Job(lambda cancelled,progress: restore_selected(manifest,chosen,destination,
                            resume_from=resume_from,cancelled=cancelled,progress=progress))
        def done(result):
            path,count=result
            record=json.loads((path/'ESTADO-RESTAURACAO.json').read_text(encoding='utf-8'))
            stats=record.get('performance',{})
            detail=f'Tempo: {time_text(stats.get("elapsed_sec"))}; velocidade média: {stats.get("bytes_per_sec",0)/1024**2:.1f} MiB/s'
            status.set(f'Restauração aprovada: {count} arquivo(s) verificados por SHA-256.\n{detail}\n{path}')
            messagebox.showinfo('Restauração aprovada',f'{count} arquivo(s) recuperados e verificados:\n{path}\n{detail}',parent=dlg)
        poll(done)

    def perform():
        if state['busy']:
            return
        chosen = sorted(state['selected'], key=str.casefold)
        if not chosen:
            messagebox.showinfo('Nenhum item marcado',
                                'Marque pelo menos um arquivo, pasta, jogo ou aplicativo na coluna Restaurar.',
                                parent=dlg)
            return
        destination = filedialog.askdirectory(parent=dlg,
                    title='Escolha onde criar uma NOVA pasta de restauração')
        if not destination:
            return
        bytes_total = sum(state['index'].bytes_by_key[k] for k in chosen)
        if not messagebox.askyesno('Confirmar restauração',
                f'Restaurar {len(chosen):,} arquivo(s), total {human_size(bytes_total)}, '
                f'em uma pasta NOVA dentro de:\n{destination}?\n\n'
                'A pasta original de backup e os arquivos do sistema não serão alterados.', parent=dlg):
            return
        start_job(chosen,destination)

    restore_button = ttk.Button(actions, text='Restaurar arquivos marcados para pasta nova', command=perform)
    restore_button.pack(side='left')

    def resume_restore():
        if state['busy'] or state['index'] is None: return
        folder=filedialog.askdirectory(parent=dlg,title='Selecione uma pasta TESTE-RESTAURACAO interrompida v0.5.19')
        if not folder: return
        try:
            journal=resume_information(folder,manifest)
            chosen=journal['keys']
            if not all(key in state['index'].bytes_by_key for key in chosen):
                raise ValueError('Os arquivos da retomada não estão no índice carregado.')
        except Exception as exc:
            messagebox.showerror('Retomada indisponível',str(exc),parent=dlg)
            return
        if not messagebox.askyesno('Retomar restauração',
                f'Retomar {len(chosen)} arquivo(s) em\n{folder}?\n'
                'Arquivos concluídos serão conferidos por SHA-256. O backup original não será alterado.',parent=dlg):
            return
        state['selected'].update(chosen)
        update_visible_marks()
        start_job(chosen,str(Path(folder).resolve().parent),resume_from=folder)

    resume_button=ttk.Button(actions,text='Retomar restauração interrompida',command=resume_restore)
    resume_button.pack(side='left',padx=(9,0))

    def cancel():
        if state['job'] is not None and state['busy']:
            state['job'].cancelled.set()
            status.set('Cancelamento solicitado. Aguardando a operação atual de disco…')

    cancel_button = ttk.Button(actions, text='Cancelar operação', command=cancel)
    cancel_button.pack(side='left', padx=12)

    def close():
        if state['busy']:
            if messagebox.askyesno('Operação em andamento',
                    'Solicitar cancelamento? Aguarde a confirmação antes de fechar.', parent=dlg):
                cancel()
        else:
            if state['after'] is not None:
                timers.cancel(state['after'])
            timers.close()
            dlg.destroy()
    dlg.protocol('WM_DELETE_WINDOW', close)

    def load(cancelled, progress):
        entries = verified_entries(manifest)
        if cancelled.is_set():
            raise InterruptedError('Leitura cancelada.')
        if small:
            candidates = [key for key, value in entries.items()
                          if int(value.get('bytes') or 0) <= 50 * 1024**2]
            chosen = min(candidates, key=lambda key: (int(entries[key].get('bytes') or 0), key)) if candidates else None
            entries = {chosen: entries[chosen]} if chosen else {}
        index = build_restore_index(entries)
        if cancelled.is_set():
            raise InterruptedError('Leitura cancelada.')
        return index

    def loaded(index):
        state['index'] = index
        state['hits'] = index.search_counts('')
        if small and index.files:
            state['selected'].add(next(iter(index.files)))
        render_root()
        if small and index.files:
            # Reveal the one marked file in the existing hierarchy.
            chain = []
            node = next(iter(index.files.values())).parent
            while node is not None and node.kind != 'root':
                chain.append(node)
                node = node.parent
            for node in reversed(chain):
                tree.item(str(node.uid), open=True)
                if node.uid not in state['shown']:
                    populate(node)
        status.set(f'{index.root.count:,} arquivo(s) verificados; '
                   'organizados por aplicativo e tipo. Selecione o que deseja restaurar.'.replace(',', '.'))

    set_busy(True)
    state['job'] = Job(load)
    poll(loaded)
