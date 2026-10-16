"""v0.6: per-volume, on-demand, read-only discovery and preservation choices.

The UI never copies or formats any disk. A 'Manter' flag only changes a plan:
formatting the containing volume still requires a verified independent copy.
"""
import json
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from deep_discovery import scan, local_drives
from volume_inventory import collect_volume_inventory
from discovery_groups import record_indices, family, selected_records, other_osu_editions_under_selection
from drive_catalog import (groups_by_volume, coverage, list_folder_page,
                           safe_to_mark, CATEGORIES)
from volume_paths import volume_of, drive_root
from scan_scope import in_scope, filter_report
from scan_sessions import split_by_drive, merge_cache, cache_from_saved
from inventory_import import read_inventory
from backup_core import effective_choice, beneath, atomic_json, norm, is_reparse
from program_catalog import discover_apps
from windows_evidence import collect, evidence_apps
from app_data import find_app_data
from game_saves import find_game_saves, _roots as known_save_roots
from scoped_saves import scoped_user_roots, incorporate_saves
from unified_selection import index_cards, card_detail, decision_label

PAGE_SIZE = 120


def show_deep_discovery(parent, container=None):
    if getattr(parent, 'deep_scan_running', False):
        messagebox.showinfo('Varredura em andamento', 'Aguarde ou cancele a busca na janela aberta.')
        return
    embedded = container is not None
    win = parent if embedded else tk.Toplevel(parent)
    if not embedded:
        win.title('Meu Computador — varredura por unidade e preservação')
        win.geometry('1220x800')
    frame = ttk.Frame(container if embedded else win, padding=12)
    frame.pack(fill='both', expand=True)
    cancel = threading.Event()
    state = {'busy': False, 'report': None, 'records': [], 'nodes': {},
             'folders': {}, 'dynamic': {}, 'angle': 0, 'group_count': 0, 'sequence': 0, 'grouped': {}, 'active_roots': [], 'animation_job': None,
             'cache': {}, 'latest': set(), 'card_nodes': {}, 'child_owner': {}}
    status = tk.StringVar(value='Escolha a unidade. Varredura apenas de leitura; nada será apagado.')
    ttk.Label(frame, text='Meu Computador — Seleção Inteligente Unificada',
              font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    ttk.Label(frame, text=(
        'Cada aba mostra somente arquivos da própria unidade, identificando o inventário atual ou salvo. Expanda jogos e pastas. '
        'As escolhas de jogos, dados e pastas usam um plano único. Pastas grandes são carregadas aos poucos. ' 'Manter NÃO substitui um backup do C:.'),
        wraplength=1160).pack(anchor='w', pady=6)
    hero = ttk.Frame(frame)
    hero.pack(fill='x', pady=4)
    ring = tk.Canvas(hero, width=90, height=90, bg='#192438', highlightthickness=0)
    ring.pack(side='left', padx=(0, 14))
    ring.create_oval(9, 9, 81, 81, outline='#334155', width=7)
    arc = ring.create_arc(9, 9, 81, 81, start=90, extent=0, style='arc', outline='#9C85FF', width=7)
    ring_text = ring.create_text(45, 45, text='Pronto', fill='#EFF4FF', font=('Segoe UI', 9, 'bold'))
    ttk.Label(hero, textvariable=status, wraplength=710).pack(side='left', fill='x', expand=True)
    shortcuts = ttk.Frame(hero)
    shortcuts.pack(side='right')
    ttk.Button(shortcuts, text='+ Pasta pessoal',
               command=lambda: parent.add_folder()).pack(fill='x', pady=2)
    ttk.Button(shortcuts, text='+ Arquivo pessoal',
               command=lambda: parent.add_file()).pack(fill='x', pady=2)

    def animate():
        if not state['busy']:
            state['animation_job'] = None
            return
        state['angle'] = (state['angle'] + 12) % 360
        ring.itemconfigure(arc, start=state['angle'], extent=90)
        state['animation_job'] = ring.after(70, animate)

    scope = ttk.Frame(frame)
    scope.pack(fill='x')
    ttk.Label(scope, text='Unidades a examinar:').pack(side='left')
    roots = []
    for d in local_drives():
        var = tk.BooleanVar(value=True)
        roots.append((d, var))
        ttk.Checkbutton(scope, text=d, variable=var).pack(side='left', padx=5)
    extras = []

    def add_root():
        if state['busy']:
            return
        path = filedialog.askdirectory(parent=win, title='Adicionar pasta à varredura')
        if path:
            extras.append(path)
            status.set('Pasta adicionada à varredura: ' + path)
    ttk.Button(scope, text='Adicionar pasta específica', command=add_root).pack(side='left', padx=8)

    def open_volume_inventory():
        """Read-only metadata view, including volumes without drive letters."""
        if state['busy']:
            messagebox.showinfo('Inventário', 'Aguarde a varredura em andamento.', parent=win)
            return
        snapshot = collect_volume_inventory()
        popup = tk.Toplevel(win)
        popup.title('Inventário de volumes Windows — somente leitura')
        popup.geometry('850x460')
        pane = ttk.Frame(popup, padding=12)
        pane.pack(fill='both', expand=True)
        status_text = ('Consulta de metadados finalizada' if snapshot['status'] == 'ok'
                       else 'ATENÇÃO: inventário de volumes parcial ou indisponível')
        ttk.Label(pane, text=status_text, font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(pane, text=snapshot.get('notice', ''), wraplength=800).pack(anchor='w', pady=6)
        body = ttk.Frame(pane)
        body.pack(fill='both', expand=True)
        viewer = tk.Text(body, wrap='word', background='#192438', foreground='#EFF4FF',
                         insertbackground='#EFF4FF', relief='flat')
        scrollbar = ttk.Scrollbar(body, orient='vertical', command=viewer.yview)
        viewer.configure(yscrollcommand=scrollbar.set)
        viewer.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        for index, volume in enumerate(snapshot['volumes'], 1):
            locations = ', '.join(volume['mount_points']) or '(sem letra ou pasta montada)'
            viewer.insert('end', f'Volume {index}: {volume["drive_type"]}\n'
                                 f'ID: {volume["volume_id"]}\n'
                                 f'Montagens: {locations}\n')
            if volume['needs_manual_review']:
                viewer.insert('end', 'ATENÇÃO: volume não incluído na varredura automática.\n')
            elif not volume['has_letter']:
                viewer.insert('end', 'Pasta montada: examinar separadamente; não há aba própria.\n')
            viewer.insert('end', '\n')
        for issue in snapshot.get('issues', ()):
            viewer.insert('end', 'LACUNA: ' + issue + '\n')
        viewer.configure(state='disabled')
        ttk.Button(pane, text='Fechar', command=popup.destroy).pack(anchor='e', pady=5)

    ttk.Button(scope, text='Ver todos os volumes', command=open_volume_inventory).pack(side='left', padx=8)

    controls = ttk.Frame(frame)
    controls.pack(fill='x', pady=5)
    filter_var = tk.StringVar()
    ttk.Label(frame, text='Buscar jogos, aplicativos ou arquivos da unidade selecionada:').pack(anchor='w')
    ttk.Entry(frame, textvariable=filter_var).pack(fill='x')

    tabs = ttk.Notebook(frame)
    tabs.pack(fill='x', pady=(8, 4))
    tab_to_drive = {}
    drive_to_tab = {}
    tab_info = {}
    for d, _ in roots:
        letter = volume_of(d)
        panel = ttk.Frame(tabs, padding=5)
        info = ttk.Label(panel, text='Varredura ainda não concluída neste volume.')
        info.pack(anchor='w')
        tabs.add(panel, text=letter)
        tab_to_drive[str(panel)] = letter
        drive_to_tab[letter] = panel
        tab_info[letter] = info
    if not roots:
        panel = ttk.Frame(tabs, padding=5)
        tabs.add(panel, text='Sem unidades')
        tab_to_drive[str(panel)] = None

    area = ttk.Frame(frame)
    area.pack(fill='both', expand=True, pady=5)
    tree = ttk.Treeview(area, columns=('choice', 'path', 'evidence'), show='tree headings',
                        selectmode='extended')
    tree.heading('#0', text='Jogos, aplicativos e pastas desta unidade')
    tree.column('#0', width=275, stretch=True)
    for col, label, width in [
        ('choice', 'Escolha', 115), ('path', 'Unidade / caminho', 195),
        ('evidence', 'Dados e situação', 315)]:
        tree.heading(col, text=label)
        tree.column(col, width=width, stretch=False)
    sy = ttk.Scrollbar(area, orient='vertical', command=tree.yview)
    sx = ttk.Scrollbar(area, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
    tree.grid(row=0, column=0, sticky='nsew')
    sy.grid(row=0, column=1, sticky='ns')
    sx.grid(row=1, column=0, sticky='ew')
    area.rowconfigure(0, weight=1)
    area.columnconfigure(0, weight=1)

    def current_drive():
        return tab_to_drive.get(tabs.select())

    def new_iid():
        state['sequence'] += 1
        return 'node' + str(state['sequence'])

    def decision(path):
        if norm(path) in getattr(parent, 'cleanup_candidates', set()):
            return 'Candidato a remover (prévia)'
        return {'keep': 'Manter', 'skip': 'Não preservar', 'pending': 'Pendente'}[
            effective_choice(path, parent.choices)]

    def dummy(node):
        tree.insert(node, 'end', iid=new_iid(), text='Abrir para carregar…')

    def render(*_):
        # No disk enumeration here: switching tabs and typing must be fast.
        if tree.get_children():
            tree.delete(*tree.get_children())
        state['nodes'] = {}
        state['card_nodes'] = {}
        state['child_owner'] = {}
        state['folders'] = {}
        state['dynamic'] = {}
        report = state['report']
        drive = current_drive()
        if not drive:
            return
        for letter, tab in drive_to_tab.items():
            state_name = ('não examinado' if letter not in state['cache'] else
                          'atual' if letter in state['latest'] else 'salvo')
            tabs.tab(tab, text=letter + '  ·  ' + state_name)
        if not report or drive not in state['cache']:
            tree.insert('', 'end', text='Unidade ainda não examinada. Marque a unidade e inicie a varredura.')
            return
        q = filter_var.get().strip().casefold()
        # ONE source of truth: scanned records + saved game/app identities + user
        # choices. No global game discovery when changing disk tabs or filtering.
        all_cards = index_cards(report, getattr(parent,'catalog_items',{}), getattr(parent,'catalog_choices',{}),
                            parent.choices, getattr(parent, 'approved_catalog_paths', {}))
        cards = all_cards.get(drive, [])
        matched = 0
        categories = dict()
        for card in cards:
            haystack = ' '.join([card['name'], card['key'], card['install_location'],
                                 *card['record_paths'], *card['data_paths'], *card['possible_paths']]).casefold()
            if q and q not in haystack:
                continue
            category = card['kind'] if card['kind'] in CATEGORIES else 'Aplicativos'
            if category not in categories:
                cid = new_iid()
                categories[category] = cid
                tree.insert('', 'end', iid=cid, text=category,
                            values=('', '', 'Abra a ficha do item para revisar saves'), open=True)
            gid = new_iid()
            state['card_nodes'][gid] = card
            state['dynamic'][gid] = {'type': 'card', 'card': card}
            install = 'Instalado aqui' if card['install_here'] else 'Dados nesta unidade'
            count = len(set(card['record_paths'] + card['data_paths']))
            note = f'{install} · {count} caminho(s) identificado(s)'
            if card['needs_review'] or not card['data_paths']:
                note += ' · CONFERIR saves/configurações'
            tree.insert(categories[category], 'end', iid=gid, text=card['name'],
                        values=(decision_label(card['choice']), drive, note), open=False)
            if card['record_paths'] or card['data_paths'] or card['possible_paths']:
                dummy(gid)
            matched += 1
        state['group_count'] = matched
        if not q:
            root_id = new_iid()
            path = drive_root(drive)
            tree.insert('', 'end', iid=root_id, text='Explorar todas as pastas de ' + drive,
                        values=('Somente leitura', path, 'Pastas não identificadas também podem ser escolhidas'), open=False)
            state['folders'][root_id] = path
            state['dynamic'][root_id] = {'type': 'directory', 'path': path}
            dummy(root_id)
        elif not matched:
            tree.insert('', 'end', text='Nenhum grupo identificado corresponde à pesquisa nesta unidade.')
        marked_by_drive = {}
        for choice_path, value in parent.choices.items():
            if value == 'keep':
                d = volume_of(choice_path)
                marked_by_drive[d] = marked_by_drive.get(d, 0) + 1
        for letter, label in tab_info.items():
            if letter not in state['cache']:
                label.configure(text='Não examinada. Selecione esta unidade para iniciar a varredura.')
                tabs.tab(drive_to_tab[letter], text=letter + '  ·  não examinado')
                continue
            tabs.tab(drive_to_tab[letter], text=letter + ('  ·  atual' if letter in state['latest'] else '  ·  salvo'))
            stat = coverage(report, letter)
            count = len(all_cards.get(letter, []))
            label.configure(text=(
                f"{stat['directories']:,} pastas · {stat['files']:,} arquivos examinados · "
                f"{count} grupos · {sum(c['choice']=='keep' for c in all_cards.get(letter, []))} itens marcados Manter · "
                f"{stat['errors']} erros · {stat['skipped']} itens não examinados. "
                + ('Cobertura completa somente nesta análise. ' if stat['complete']
                   else 'ATENÇÃO: inventário incompleto — não presumir proteção de todos os arquivos. ')
                + 'Dados não identificados: use Explorar pastas.'
            ))

    def fill_card(iid, card):
        if not tree.exists(iid):
            return
        for child in tree.get_children(iid):
            tree.delete(child)
        trusted = list(dict.fromkeys(card['data_paths']))
        candidates = [p for p in dict.fromkeys(card['record_paths'] + card['possible_paths'])
                      if p not in trusted]
        for path, reviewed in [(p, True) for p in trusted] + [(p, False) for p in candidates]:
            child = new_iid()
            state['child_owner'][child] = card['key']
            state['folders'][child] = path
            title = 'Dados conferidos' if reviewed else 'Caminho a conferir'
            note = ('Backup verificado exigido antes do Windows' if volume_of(path)=='C:' else
                    'Permanecerá aqui, se o volume não for apagado') if reviewed else 'Não presumir que seja um save'
            tree.insert(iid, 'end', iid=child, text=title,
                        values=(decision(path), path, note))
            if os.path.isdir(path) and not is_reparse(path):
                state['dynamic'][child] = {'type':'directory', 'path':path}
                dummy(child)
        state['dynamic'][iid] = {'type': 'loaded_card', 'card': card}

    def load_folder(iid, path, offset=0):
        if state['busy'] or not tree.exists(iid):
            return
        if offset == 0:
            for child in tree.get_children(iid):
                tree.delete(child)
        loading = new_iid()
        tree.insert(iid, 'end', iid=loading, text='Lendo até 120 itens…')
        def worker():
            try:
                page = list_folder_page(path, offset=offset, limit=PAGE_SIZE)
                error = None
            except (OSError, ValueError) as exc:
                page, error = None, str(exc)
            def finish():
                if not tree.exists(iid):
                    return
                if tree.exists(loading):
                    tree.delete(loading)
                if error:
                    tree.insert(iid, 'end', iid=new_iid(), text='Indisponível: ' + error)
                    return
                for item in page['entries']:
                    child = new_iid()
                    choice = 'Link/junção: não seguido' if item['special'] else decision(item['path'])
                    suffix = ' [pasta]' if item['is_dir'] else ''
                    tree.insert(iid, 'end', iid=child, text=item['name'] + suffix,
                                values=(choice, item['path'], 'Somente leitura / caminho não associado'))
                    if item['is_dir'] and not item['special']:
                        state['folders'][child] = item['path']
                        state['dynamic'][child] = {'type': 'directory', 'path': item['path']}
                        dummy(child)
                    elif not item['special']:
                        state['folders'][child] = item['path']
                if page['next_offset'] is not None:
                    more = new_iid()
                    tree.insert(iid, 'end', iid=more, text='Carregar mais 120 itens…',
                                values=('', path, 'Somente esta pasta / próxima página'))
                    state['dynamic'][more] = {'type': 'more', 'path': path,
                                               'offset': page['next_offset'], 'owner': iid}
                    dummy(more)
            # Tk may already be destroyed (standalone window closed).
            try:
                parent.after(0, finish)
            except (RuntimeError, tk.TclError):
                pass
        threading.Thread(target=worker, daemon=True).start()

    def on_open(_event=None):
        iid = tree.focus()
        data = state['dynamic'].get(iid)
        if not data:
            return
        if data['type'] == 'card':
            fill_card(iid, data['card'])
        elif data['type'] == 'directory':
            state['dynamic'][iid] = {'type': 'loaded_directory', 'path': data['path']}
            load_folder(iid, data['path'])
        elif data['type'] == 'more':
            owner = data['owner']
            if tree.exists(iid):
                tree.delete(iid)
            load_folder(owner, data['path'], data['offset'])
    tree.bind('<<TreeviewOpen>>', on_open)
    tabs.bind('<<NotebookTabChanged>>', render)
    filter_var.trace_add('write', render)

    def progress(dirs, files, path):
        parent.after(0, lambda: status.set(
            f'{dirs:,} pastas · {files:,} arquivos examinados · {path}'))

    def start():
        if state['busy']:
            return
        chosen = [p for p, v in roots if v.get()] + extras
        if not chosen:
            messagebox.showinfo('Escopo', 'Escolha ao menos uma unidade ou pasta.', parent=win)
            return
        state['busy'] = True
        parent.deep_scan_running = True
        cancel.clear()
        # Não apagar relatórios anteriores nem escolhas do usuário ao reexaminar
        # outra combinação de unidades. Os outros volumes ficam como 'salvo'.
        state['active_roots'] = list(chosen)
        selected_drives = {volume_of(p) for p in chosen}
        selected_drives.discard('SEM UNIDADE')
        if not selected_drives:
            messagebox.showerror('Escopo', 'Nenhuma unidade local foi selecionada.', parent=win)
            state['busy'] = False
            parent.deep_scan_running = False
            return
        current = sorted(selected_drives)[0]
        if current in drive_to_tab:
            tabs.select(drive_to_tab[current])
        render()
        status.set('Preparando a varredura somente nas unidades escolhidas…')
        ring.itemconfigure(ring_text, text='Lendo…')
        animate()
        exclusions = [str(Path(__file__).resolve().parent), parent.dest.get()]
        parent_catalog = {k: dict(v) for k, v in parent.catalog_items.items()}

        def finish(report=None, error=None):
            state['busy'] = False
            parent.deep_scan_running = False
            if state.get('animation_job'):
                try:
                    ring.after_cancel(state['animation_job'])
                except tk.TclError:
                    pass
                state['animation_job'] = None
            if error:
                # Conserva o inventário anterior, pois a tentativa atual falhou.
                ring.itemconfigure(ring_text, text='Falha')
                ring.itemconfigure(arc, extent=0)
                status.set('Varredura falhou.')
                messagebox.showerror('Varredura', error, parent=win)
                return
            report = filter_report(report, state['active_roots'])
            freshly_scanned = split_by_drive(report, selected_drives)
            state['cache'].update(freshly_scanned)
            state['latest'] = set(freshly_scanned)
            merged = merge_cache(state['cache'], latest=state['latest'])
            state['report'] = merged
            state['grouped'] = {}
            state['records'] = merged['records']
            parent.deep_scan_report = merged
            parent.scan_reports_by_drive = dict(state['cache'])
            render()
            complete = report['status'] != 'cancelada_parcial'
            ring.itemconfigure(ring_text, text=('Lacunas' if report['errors'] or report['skipped'] else '100%') if complete else 'Parcial')
            ring.itemconfigure(arc, start=90, extent=359 if complete else 0)
            try:
                atomic_json(Path(__file__).parent / 'deteccao-detalhada-v065.json', merged)
            except OSError as exc:
                messagebox.showwarning('Relatório', 'Varredura concluída, mas não foi possível salvar o relatório: ' + str(exc), parent=win)
            status.set(f"{report['status']} · unidades reexaminadas: {', '.join(sorted(selected_drives))} · "
                       f"{report['directories']:,} pastas · {report['files']:,} arquivos examinados · "
                       f"{len(report['errors'])} erros · {len(report['skipped'])} exclusões. "
                       'Escolha os itens por unidade; Manter não é uma cópia de segurança.')

        def worker():
            try:
                apps = discover_apps()
                # Windows metadata may search shortcuts on unrelated volumes.
                # Only gather it when the system volume is in the explicit scope.
                includes_c = in_scope('C:/', chosen)
                windows = collect() if includes_c else {'shortcuts': [], 'packages': [], 'errors': []}
                apps += [a for a in evidence_apps(windows, allowed_roots=chosen) if
                         in_scope(a.get('install_location'), chosen)]
                for key, item in parent_catalog.items():
                    if not item.get('registry_id') and item.get('kind') == 'game':
                        apps.append({'id': key, 'name': item['name'],
                                     'source': item.get('source', ''), 'category': 'Jogo'})
                # AppData lives under Windows user profiles; do not enumerate it
                # when C: was not selected. All results are scope-checked below.
                quick = find_app_data(apps, allowed_roots=chosen) if includes_c else []
                report = scan(apps, chosen, excluded=exclusions, cancel=cancel, progress=progress)
                if includes_c and not cancel.is_set():
                    # Search known user-save locations ONLY inside selected
                    # roots; do not automatically traverse unselected SSDs.
                    roots_for_saves = scoped_user_roots(known_save_roots(), chosen)
                    save_candidates = find_game_saves([], roots=roots_for_saves, steam_roots=[])
                    report = incorporate_saves(report, save_candidates, parent_catalog, chosen)
                # Metadata failures are global and must not be misreported as
                # filesystem errors of the selected units.
                for r in quick:
                    if not in_scope(r['path'], chosen):
                        continue
                    report['records'].append(dict(app_id=r['app_id'], app=r['app'],
                                                  path=r['path'], kind='Dados/configurações conhecidos',
                                                  evidence=r['source'], confidence='candidato', edition=None))
                for key, item in parent_catalog.items():
                    if item.get('kind') == 'game':
                        for p in item.get('paths', []):
                            if not in_scope(p, chosen):
                                continue
                            report['records'].append(dict(app_id=key, app=item['name'],
                                                          path=p, kind='Save/configuração associado ao jogo',
                                                          evidence='Catálogo de saves e launcher',
                                                          confidence='caminho identificado', edition=None))
                if report['errors'] and report['status'] == 'concluida':
                    report['status'] = 'concluida_com_lacunas'
                parent.after(0, lambda: finish(report=report))
            except Exception as exc:
                parent.after(0, lambda e=str(exc): finish(error=e))
        threading.Thread(target=worker, daemon=True).start()

    ttk.Button(controls, text='Examinar unidades marcadas', command=start).pack(side='left', padx=4)
    ttk.Button(controls, text='Cancelar (guardar resultado parcial)', command=cancel.set).pack(side='left', padx=4)

    def import_previous_inventory():
        """Load old read-only scan snapshots without discarding current results."""
        if state['busy']:
            messagebox.showinfo('Aguarde', 'Finalize a varredura antes de importar.', parent=win)
            return
        path = filedialog.askopenfilename(parent=win,
                    title='Selecione deteccao-detalhada-v063/v064.json (NÃO preferencias-v05.json)',
                    filetypes=[('Inventário JSON', '*.json')])
        if not path:
            return
        try:
            imported = read_inventory(path)
            imported = {d: snapshot for d, snapshot in imported.items()
                        if d in drive_to_tab and d not in state['cache']}
            if not imported:
                messagebox.showinfo('Inventário existente',
                    'As unidades deste inventário já estão carregadas. Nenhum resultado foi substituído.', parent=win)
                return
            state['cache'].update(imported)
            state['latest'].difference_update(imported)
            combined = merge_cache(state['cache'], latest=state['latest'])
            state['report'] = combined
            state['records'] = combined['records']
            parent.deep_scan_report = combined
            parent.scan_reports_by_drive = dict(state['cache'])
            render()
            status.set('Inventários anteriores importados: ' + ', '.join(sorted(imported)) +
                       '. Estes dados são antigos; revise antes de usar no plano.')
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror('Falha ao importar inventário', str(exc), parent=win)

    ttk.Button(controls, text='Importar inventário anterior',
               command=import_previous_inventory).pack(side='left', padx=4)

    def show_gaps():
        if not state['report']:
            return
        from workflow_ui import show_scan_gaps
        show_scan_gaps(parent, state['report'], state['cache'])
    ttk.Button(controls, text='Erros e exclusões', command=show_gaps).pack(side='left', padx=4)

    def export():
        if not state['report']:
            return
        p = filedialog.asksaveasfilename(parent=win, defaultextension='.json',
                                         title='Salvar relatório (contém caminhos locais)',
                                         filetypes=[('JSON', '*.json')])
        if p:
            atomic_json(p, state['report'])
    ttk.Button(controls, text='Exportar relatório', command=export).pack(side='left', padx=4)

    def selections():
        """Return (chosen cards, explicit leaf paths); never select a category implicitly."""
        cards = list({state['card_nodes'][iid]['key']: state['card_nodes'][iid]
                      for iid in tree.selection() if iid in state['card_nodes']}.values())
        leaves = [(state['folders'][iid], state['child_owner'].get(iid))
                  for iid in tree.selection() if iid in state['folders']]
        # Folders have no owner; selected cards are intents, NOT all their paths.
        return cards, list(dict.fromkeys(leaves))

    def paths_unsafe(paths):
        blocked = []
        for src in paths:
            p = Path(src)
            destination = parent.dest.get()
            program = str(Path(__file__).resolve().parent)
            if (not p.exists() or not safe_to_mark(src) or
                    any(is_reparse(a) for a in (p, *p.parents)) or
                    (destination and (beneath(src, destination) or beneath(destination, src))) or
                    beneath(src, program)):
                blocked.append(src)
        return blocked

    def open_card():
        cards, leaves = selections()
        if len(cards) != 1:
            messagebox.showinfo('Ficha do item',
                                'Selecione apenas um jogo/aplicativo e clique em Abrir ficha.', parent=win)
            return
        card = cards[0]
        detail = card_detail(card, parent.catalog_items, parent.approved_catalog_paths)
        dialog = tk.Toplevel(win)
        dialog.title('Ficha de preservação — ' + card['name'])
        dialog.geometry('850x610')
        body = ttk.Frame(dialog, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=card['name'], font=('Segoe UI', 17, 'bold')).pack(anchor='w')
        ttk.Label(body, text=f"Unidade atual: {card['drive']}  •  Escolha: {decision_label(detail['choice'])}").pack(anchor='w', pady=(7, 12))
        location = detail['install'] or 'Local de instalação não confirmado'
        ttk.Label(body, text='INSTALAÇÃO: ' + location, wraplength=770).pack(anchor='w', pady=(0, 9))
        ttk.Label(body, text='Dados associados e confirmados:', font=('Segoe UI',10,'bold')).pack(anchor='w')
        known = tk.Text(body, height=5, bg='#192438', fg='#EFF4FF', wrap='word', relief='flat')
        known.pack(fill='x', pady=(4, 12))
        known.insert('1.0', '\n'.join(detail['confirmed']) or 'Nenhum arquivo de save/configuração confirmado.')
        known.config(state='disabled')
        ttk.Label(body, text='Possíveis caminhos encontrados — confirme apenas se pertencerem a este item:',
                  wraplength=770).pack(anchor='w')
        path_list = tk.Listbox(body, selectmode='extended', height=8, bg='#192438',
                               fg='#EFF4FF', selectbackground='#394C75', relief='flat')
        path_list.pack(fill='both', expand=True, pady=(5, 7))
        for path in detail['candidates']:
            path_list.insert('end', path)
        ttk.Label(body, text='Se o save confirmado estiver no C:, será necessário copiar e verificar '
                  'antes da reinstalação. Este painel não copia nem apaga arquivos.',
                  foreground='#F3BE67', wraplength=765).pack(anchor='w', pady=(2, 8))
        buttons = ttk.Frame(body)
        buttons.pack(fill='x', pady=5)
        def confirm_candidates():
            chosen = [detail['candidates'][n] for n in path_list.curselection()]
            invalid = paths_unsafe(chosen)
            if not chosen:
                messagebox.showinfo('Dados', 'Selecione os candidatos que você conferiu.', parent=dialog)
                return
            if invalid:
                messagebox.showwarning('Dados inválidos',
                         'Estes caminhos são inacessíveis, amplos ou inseguros:\n'+'\n'.join(invalid[:10]), parent=dialog)
                return
            if not messagebox.askyesno('Confirmar vínculo',
                  'Você conferiu pessoalmente que estes caminhos pertencem a ' + card['name'] +
                  '?\n\n'+'\n'.join(chosen[:8])+
                  '\n\nApenas a associação é registrada; nenhum arquivo é copiado.',parent=dialog):
                return
            key = card['key']
            parent.set_unified_entity_choice(key,'keep',name=card['name'],
                    kind=card.get('entity_kind', 'app'),
                    observed_volume=card['drive'], notify=False)
            item = parent.catalog_items[key]
            for path in chosen:
                if path not in item['paths']:
                    item['paths'].append(path)
                if path in item['possible_paths']:
                    item['possible_paths'].remove(path)
                parent.approved_catalog_paths.setdefault(key, [])
                if path not in parent.approved_catalog_paths[key]:
                    parent.approved_catalog_paths[key].append(path)
                parent.choices[norm(path)] = 'keep'
                parent.auto_save_paths.add(norm(path))
            parent._on_change()
            dialog.destroy()
            status.set(f'{len(chosen)} caminho(s) conferido(s) para {card["name"]}.')
        ttk.Button(buttons,text='Confirmar caminhos selecionados',command=confirm_candidates).pack(side='left')
        ttk.Button(buttons,text='Fechar',command=dialog.destroy).pack(side='right')

    def approve():
        if state['busy']:
            return
        cards, leaves = selections()
        if not cards and not leaves:
            messagebox.showinfo('Seleção', 'Marque um item ou arquivo primeiro.', parent=win)
            return
        raw = list(dict.fromkeys(path for path, _ in leaves))
        blocked = paths_unsafe(raw)
        blocked.extend(path for path in raw if volume_of(path)!=current_drive())
        if blocked:
            messagebox.showerror('Seleção insegura', '\n'.join(dict.fromkeys(blocked))[:1000], parent=win)
            return
        if not messagebox.askyesno('Manter — não é backup',
           f'Marcar {len(cards)} jogo(s)/aplicativo(s) e {len(raw)} caminho(s) individuais para MANTER?\n\n'
           'Saves apenas sugeridos continuarão pendentes até serem conferidos. '
           'Arquivos no C: exigem backup verificado antes da reinstalação.',parent=win):
            return
        for card in cards:
            parent.set_unified_entity_choice(card['key'], 'keep', name=card['name'],
                kind=card.get('entity_kind', 'app'),
                install_location=card['install_location'],
                possible_paths=card['possible_paths']+card['record_paths'],
                observed_volume=card['drive'], notify=False)
        for path, key in leaves:
            parent.choices[norm(path)]='keep'
            parent.cleanup_candidates.discard(norm(path))
            if key:
                parent.set_unified_entity_choice(key, 'keep', notify=False)
                item = parent.catalog_items[key]
                if path not in item['paths']:
                    item['paths'].append(path)
                if path in item['possible_paths']:
                    item['possible_paths'].remove(path)
                parent.approved_catalog_paths.setdefault(key, [])
                if path not in parent.approved_catalog_paths[key]:
                    parent.approved_catalog_paths[key].append(path)
                parent.auto_save_paths.add(norm(path))
            else:
                parent.personal_paths.add(norm(path))
        parent._on_change()
        status.set('Escolhas atualizadas nas duas telas. Nenhuma cópia ou exclusão executada.')

    def skip():
        if state['busy']:
            return
        cards, leaves = selections()
        if not cards and not leaves:
            return
        if not messagebox.askyesno('Não preservar — NÃO exclui',
               'Retirar os itens do plano de preservação? Arquivos originais permanecem intactos.',parent=win):
            return
        for card in cards:
            parent.set_unified_entity_choice(card['key'],'skip',name=card['name'],
                kind=card.get('entity_kind', 'app'),notify=False)
        for path, _ in leaves:
            parent.choices[norm(path)]='skip'
            parent.cleanup_candidates.discard(norm(path))
        parent._on_change()
        status.set('Escolhas atualizadas: não preservar NÃO significa excluir.')

    def mark_removal_candidate():
        if state['busy']:
            return
        cards, leaves = selections()
        paths = list(dict.fromkeys(path for path, _ in leaves))
        if not paths:
            return
        blocked = paths_unsafe(paths)
        selected_drive = current_drive()
        blocked.extend(p for p in paths if volume_of(p) != selected_drive)
        blocked.extend(p for p in paths if effective_choice(p, parent.choices) == 'keep')
        if blocked:
            messagebox.showwarning('Não permitido',
                'Não é possível sinalizar a raiz, links, caminhos fora desta unidade, arquivos protegidos '
                'ou itens já marcados para MANTER. Reveja a escolha primeiro.\n' +
                '\n'.join(dict.fromkeys(blocked)), parent=win)
            return
        if not messagebox.askyesno('Somente candidato — nenhuma exclusão',
            f'Sinalizar {len(paths)} caminho(s) como CANDIDATO A REMOÇÃO no plano?\n\n'
            'Não exclui nada agora. O aplicativo ainda NÃO possui execução de limpeza. '
            'Não selecionar para manter também não autoriza exclusão.', parent=win):
            return
        parent.cleanup_candidates.update(map(norm, paths))
        parent._on_change()
        render()
        status.set(f'{len(paths)} candidato(s) registrados. Nenhum arquivo excluído.')

    def clear_removal_candidate():
        cards, leaves = selections()
        paths = [path for path, _ in leaves]
        for path in paths:
            parent.cleanup_candidates.discard(norm(path))
        parent._on_change()
        render()

    bottom = ttk.Frame(frame)
    bottom.pack(fill='x', pady=5, before=area)
    ttk.Button(bottom, text='Manter selecionados', command=approve).pack(side='left', padx=4)
    ttk.Button(bottom, text='Não preservar', command=skip).pack(side='left', padx=4)
    ttk.Button(bottom, text='Candidato à remoção (prévia)', command=mark_removal_candidate).pack(side='left', padx=4)
    ttk.Button(bottom, text='Retirar sinalização', command=clear_removal_candidate).pack(side='left', padx=4)
    ttk.Button(bottom, text='Abrir ficha do jogo/app', command=open_card).pack(side='left', padx=4)
    ttk.Button(bottom, text='Ver Preservação →',
               command=lambda: parent.navigate(parent.preservation)).pack(side='right', padx=4)
    ttk.Label(frame, textvariable=status, wraplength=1150).pack(anchor='w', pady=7)

    def close():
        if state['busy']:
            cancel.set()
            messagebox.showinfo('Cancelando', 'Aguarde o resultado parcial antes de fechar.', parent=win)
        else:
            win.destroy()
    if not embedded:
        win.protocol('WM_DELETE_WINDOW', close)
    previous = getattr(parent, 'deep_scan_report', None)
    if not previous:
        for name in ('deteccao-detalhada-v065.json', 'deteccao-detalhada-v064.json', 'deteccao-detalhada-v063.json', 'deteccao-detalhada-v062.json', 'deteccao-detalhada-v060.json', 'deteccao-detalhada-v0514.json'):
            try:
                candidate = json.loads((Path(__file__).parent / name).read_text(encoding='utf-8'))
                if candidate.get('schema') == 'pcro-discovery-v1':
                    previous = candidate
                    break
            except (OSError, ValueError, AttributeError):
                pass
    if previous:
        state['cache'] = cache_from_saved(previous)
        state['report'] = merge_cache(state['cache']) if state['cache'] else None
        state['grouped'] = {}
        state['records'] = state['report'].get('records', []) if state['report'] else []
        parent.deep_scan_report = state['report']
        parent.scan_reports_by_drive = dict(state['cache'])
        render()
        status.set('Inventários anteriores carregados por unidade. Para atualizar, selecione as unidades desejadas.')
    else:
        render()
    parent.refresh_scan_groups = render
    return frame
