"""Focused overview, preservation preview and read-only installation preparation.

This module deliberately has no deletion, formatting or boot modification API.
"""
from __future__ import annotations
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from preservation_plan import classify_choices, summarize
from preservation_audit import build_audit
from preservation_preflight import prepare_c_preflight
from scan_gaps import report_by_drive
from backup_core import atomic_json
from volume_paths import volume_of
from ui_scale import (
    ACCENT,
    AMBER,
    BG,
    BORDER,
    ESPACO_DENTRO_GRUPO,
    ESPACO_ENTRE_BLOCOS,
    ESPACO_ENTRE_BOTOES,
    ESPACO_ENTRE_GRUPOS,
    ESPACO_M,
    ESPACO_MINIMO,
    ESPACO_P,
    FONTE_MONO,
    FONTE_UI,
    GREEN,
    MUTED,
    PADDING_CAIXA_TEXTO,
    PADDING_DIALOGO,
    PADDING_PAINEL_COMPACTO,
    PANEL,
    TAMANHO_APOIO,
    TAMANHO_CORPO,
    TAMANHO_SUBTITULO,
    TAMANHO_TITULO_ABA,
    TAMANHO_TITULO_HERO,
    TAMANHO_TITULO_MODAL,
    TEXT,
    safe_window_geometry,
    safe_window_size,
    safe_wraplength,
)
from workflow_texts import (
    installation_steps,
    overview_intro_text,
    preservation_intro_text,
    preview_drive_rows,
    system_drive,
    withdraw_choice_hint,
    withdraw_confirmation_text,
    withdraw_loss_warning,
)


def _bind_wraplength(container, *targets, padding=ESPACO_M):
    def _update(event):
        if event.widget is not container:
            return
        for label, reserve in targets:
            label.configure(
                wraplength=safe_wraplength(event.width - reserve, padding=padding)
            )

    container.bind('<Configure>', _update, add='+')


def _card(parent, tag, title, description, target, *, accent=False):
    panel = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    panel.pack(fill='x', pady=ESPACO_DENTRO_GRUPO)
    tk.Label(panel, text=tag, bg=PANEL, fg=ACCENT if accent else GREEN,
             font=(FONTE_UI, TAMANHO_APOIO, 'bold')).pack(anchor='w', padx=ESPACO_M, pady=(ESPACO_M, ESPACO_MINIMO))
    tk.Label(panel, text=title, bg=PANEL, fg=TEXT,
             font=(FONTE_UI, TAMANHO_TITULO_MODAL, 'bold')).pack(anchor='w', padx=ESPACO_M)
    desc_label = tk.Label(panel, text=description, bg=PANEL, fg=MUTED, justify='left',
                          wraplength=safe_wraplength(880, padding=ESPACO_M),
                          font=(FONTE_UI, TAMANHO_CORPO))
    desc_label.pack(anchor='w', padx=ESPACO_M, pady=(ESPACO_P, ESPACO_M))
    _bind_wraplength(panel, (desc_label, 0), padding=ESPACO_M)
    ttk.Button(panel, text='Abrir etapa  →', command=target).pack(anchor='w', padx=ESPACO_M, pady=(0, ESPACO_M))


def build_overview(app):
    sys_drive = system_drive()
    frame = ttk.Frame(app.overview, padding=PADDING_PAINEL_COMPACTO)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Uma reinstalação organizada, sem surpresas',
              font=(FONTE_UI, TAMANHO_TITULO_ABA, 'bold')).pack(anchor='w', pady=ESPACO_DENTRO_GRUPO)
    intro = ttk.Label(frame, text=overview_intro_text(sys_drive),
                      wraplength=safe_wraplength(910, padding=PADDING_PAINEL_COMPACTO))
    intro.pack(anchor='w', pady=ESPACO_ENTRE_GRUPOS)
    _bind_wraplength(frame, (intro, 0), padding=PADDING_PAINEL_COMPACTO)
    _card(frame, '01  ·  EXPLORAR', 'Meu computador',
          'Varra somente as unidades selecionadas. Agrupe jogos, arquivos e configurações sem carregar tudo na tela.',
          lambda: app.navigate(app.home), accent=True)
    _card(frame, '02  ·  ESCOLHER', 'Preservação inteligente',
          'Marque o que manter, confira os saves vinculados e visualize um plano sem exclusões automáticas.',
          lambda: app.navigate(app.preservation))
    _card(frame, '03  ·  PREPARAR', 'Instalar Windows',
          f'Checklist de backup do {sys_drive}, EFI independente, mídia oficial e recuperação pós-instalação.',
          lambda: app.navigate(app.installation))
    ttk.Label(frame, text='MODO DE PREPARAÇÃO • Nenhuma exclusão nem formatação disponível nesta versão.',
              foreground=AMBER).pack(anchor='w', pady=(ESPACO_M, 0))


def _scroll_text(parent, height=18):
    outer = ttk.Frame(parent)
    outer.pack(fill='both', expand=True, pady=(ESPACO_P, ESPACO_MINIMO))
    box = tk.Text(outer, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                  borderwidth=0, highlightthickness=1, highlightbackground=BORDER,
                  wrap='word', font=(FONTE_MONO, TAMANHO_CORPO), height=height,
                  padx=PADDING_CAIXA_TEXTO[0], pady=PADDING_CAIXA_TEXTO[1])
    sy = ttk.Scrollbar(outer, orient='vertical', command=box.yview)
    box.configure(yscrollcommand=sy.set)
    sy.pack(side='right', fill='y')
    box.pack(side='left', fill='both', expand=True)
    box.configure(state='disabled')
    return box


def _write(box, content):
    box.configure(state='normal')
    box.delete('1.0', 'end')
    box.insert('1.0', content)
    box.configure(state='disabled')


def build_preservation(app):
    # The preservation summary has several bounded tables. Keep the lower ones
    # accessible on smaller monitors instead of clipping their content.
    sys_drive = system_drive()
    canvas = tk.Canvas(app.preservation, bg=BG, borderwidth=0, highlightthickness=0)
    page_scroll = ttk.Scrollbar(app.preservation, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=page_scroll.set)
    page_scroll.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    frame = ttk.Frame(canvas, padding=PADDING_PAINEL_COMPACTO)
    window_id = canvas.create_window((0, 0), window=frame, anchor='nw')
    frame.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window_id, width=event.width))
    ttk.Label(frame, text='O que deve permanecer no computador?',
              font=(FONTE_UI, TAMANHO_TITULO_ABA, 'bold')).pack(anchor='w', pady=(ESPACO_MINIMO, ESPACO_P))
    intro_lbl = ttk.Label(frame, text=preservation_intro_text(sys_drive),
                          wraplength=safe_wraplength(940, padding=PADDING_PAINEL_COMPACTO))
    intro_lbl.pack(anchor='w')

    metrics = tk.Frame(frame, bg=BG)
    metrics.pack(fill='x', pady=(ESPACO_M, ESPACO_M))
    kept = tk.StringVar(value='0')
    paths_kept = tk.StringVar(value='0')
    cbackup = tk.StringVar(value='0')
    remove = tk.StringVar(value='0')
    for idx, (label, var, desc) in enumerate((('JOGOS / APPS', kept, 'Itens marcados Manter'),
                                              ('PASTAS / ARQUIVOS', paths_kept, 'Caminhos explicitamente marcados'),
                                              (f'BACKUP DO {sys_drive}', cbackup, 'Caminhos ainda não copiados'),
                                              ('REMOÇÃO • PRÉVIA', remove, 'Nenhum arquivo apagado'))):
        card = tk.Frame(metrics, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        card.pack(side='left', fill='both', expand=True, padx=ESPACO_ENTRE_BOTOES if idx < 3 else 0)
        tk.Label(card, text=label, bg=PANEL, fg=MUTED, font=(FONTE_UI, TAMANHO_APOIO, 'bold')).pack(
            anchor='w', padx=ESPACO_M, pady=(ESPACO_P, ESPACO_MINIMO))
        tk.Label(card, textvariable=var, bg=PANEL, fg=TEXT, font=(FONTE_UI, TAMANHO_TITULO_HERO, 'bold')).pack(
            anchor='w', padx=ESPACO_M)
        tk.Label(card, text=desc, bg=PANEL, fg=MUTED, font=(FONTE_UI, TAMANHO_APOIO)).pack(
            anchor='w', padx=ESPACO_M, pady=(0, ESPACO_P))

    bar = ttk.Frame(frame)
    bar.pack(fill='x', pady=ESPACO_DENTRO_GRUPO)
    ttk.Label(frame, text='Jogos e aplicativos escolhidos para manter (inclui itens sem saves localizados)',
              font=(FONTE_UI, TAMANHO_CORPO, 'bold')).pack(anchor='w', pady=(ESPACO_P, ESPACO_MINIMO))
    chosen_box = ttk.Frame(frame)
    chosen_box.pack(fill='both', expand=True)
    chosen = ttk.Treeview(chosen_box, columns=('type', 'drive', 'data'), show='tree headings', height=5)
    chosen.heading('#0', text='Item selecionado / local associado')
    chosen.column('#0', width=350, stretch=True)
    for field, title, width in (('type','Tipo / escolha',155), ('drive','Unidade / vínculo',128), ('data','Condição da preservação',400)):
        chosen.heading(field,text=title)
        chosen.column(field,width=width,stretch=(field=='data'))
    chosen_bar = ttk.Scrollbar(chosen_box, orient='vertical', command=chosen.yview)
    chosen.configure(yscrollcommand=chosen_bar.set)
    chosen_bar.pack(side='right',fill='y')
    chosen.pack(side='left',fill='both',expand=True)
    columns = ('decision', 'action', 'path')
    box = ttk.Frame(frame)
    box.pack(fill='x')
    tree = ttk.Treeview(box, columns=columns, show='tree headings', selectmode='browse', height=4)
    tree.heading('#0', text='Unidade / categoria')
    tree.column('#0', width=175, stretch=False)
    for key, label, width in (('decision','Escolha',145), ('action','Tratamento previsto',260),
                              ('path','Caminho original',420)):
        tree.heading(key, text=label)
        tree.column(key, width=width, stretch=(key=='path'))
    scroll = ttk.Scrollbar(box, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    tree.pack(side='left', fill='x', expand=True)
    # Controls are deliberately next to the rows they edit, rather than at
    # the top of a long scrollable page where they are invisible.
    choice_actions = ttk.Frame(frame)
    choice_actions.pack(fill='x', pady=ESPACO_DENTRO_GRUPO)
    ttk.Label(choice_actions, text=withdraw_choice_hint(sys_drive)).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    ttk.Button(choice_actions, text='Retirar do backup (não apaga)',
               command=lambda: remove_selected_path_choice()).pack(side='left')

    ttk.Label(frame, text='Vínculos de jogos e dados associados  •  não representam backup concluído',
              font=(FONTE_UI, TAMANHO_CORPO, 'bold')).pack(anchor='w', pady=(ESPACO_P, ESPACO_MINIMO))
    linked_box = ttk.Frame(frame)
    linked_box.pack(fill='x')
    linked = ttk.Treeview(linked_box, columns=('game','installation','save','situation'), show='headings', height=5)
    for col, label, width in (('game','Jogo',175), ('installation','Instalação',115),
                              ('save','Save / configuração',415), ('situation','Associação',235)):
        linked.heading(col, text=label)
        linked.column(col, width=width, stretch=(col=='save'))
    linked_scroll = ttk.Scrollbar(linked_box, orient='vertical', command=linked.yview)
    linked.configure(yscrollcommand=linked_scroll.set)
    linked_scroll.pack(side='right', fill='y')
    linked.pack(side='left', fill='both', expand=True)
    gap_status = tk.StringVar(value='Inventário não examinado.')
    gap_lbl = ttk.Label(frame, textvariable=gap_status, foreground=AMBER,
                        wraplength=safe_wraplength(900, padding=PADDING_PAINEL_COMPACTO))
    gap_lbl.pack(anchor='w', pady=(ESPACO_P, ESPACO_MINIMO))

    notice = ttk.Label(frame, text='Plano somente informativo. Nenhuma exclusão ou formatação pode ser executada nesta versão.',
                       foreground=AMBER, wraplength=safe_wraplength(900, padding=PADDING_PAINEL_COMPACTO))
    notice.pack(anchor='w', pady=(ESPACO_P, ESPACO_M))

    def make_preview():
        roots = getattr(app, 'deep_scan_report', {}) or {}
        plan = build_audit(app.choices, app.catalog_choices, app.catalog_items,
                           getattr(app, 'approved_catalog_paths', {}),
                           getattr(app, 'game_saves', {}),
                           scanned_roots=roots.get('roots', []),
                           removal_candidates=getattr(app, 'cleanup_candidates', ()))
        links = plan['game_save_candidates']
        selected = plan['catalog_selections']
        stats = plan['selection_metrics']
        kept.set(str(stats['selected_games_apps']))
        paths_kept.set(str(stats['explicit_keep_paths']))
        cbackup.set(str(stats['backup_required_paths_c']))
        remove.set(str(stats['removal_candidates']))
        tree.delete(*tree.get_children())
        for group in preview_drive_rows(plan, drive=sys_drive):
            parent = tree.insert('', 'end', text=group['header'],
                                 values=('', '', group['scan_status']),
                                 open=True)
            for e in group['entries']:
                tree.insert(parent, 'end', text='', values=(
                    {'keep':'Manter', 'skip':'Não preservar', 'pending':'Pendente'}[e['choice']],
                    e['action'], e['path']))
            for path in group['removed']:
                tree.insert(parent, 'end', text='', values=('Candidato', 'SOMENTE MARCADO • NÃO APAGAR', path))
            if group['excess']:
                tree.insert(parent, 'end', text=f"... {group['excess']} itens adicionais no relatório exportado")
        linked.delete(*linked.get_children())
        for item in links[:200]:
            condition = ('Associação confirmada; cópia pendente' if
                         item['confidence'] == 'CONFIRMADO PELO USUÁRIO' else
                         'Identificado; conferir')
            if item.get('classification_pending'):
                condition = 'Tipo do item a conferir • ' + condition
            if item['relation'] == 'ENTRE UNIDADES':
                condition = 'Entre discos • ' + condition
            elif item['relation'] == 'POSSÍVEL VÍNCULO ENTRE UNIDADES':
                condition = 'Discos a confirmar • ' + condition
            linked.insert('', 'end', values=(item['game'], item['install_volume'],
                                              item['data_path'], condition))
        if not links:
            linked.insert('', 'end', values=('Nenhum vínculo listado', '—', '—',
                                              'Sem associação de dados validada; conferir as fichas'))
        chosen.delete(*chosen.get_children())
        for item in selected:
            drive = item['display_volume']
            label = item['name'] + ('  •  confirmação pendente' if not item['has_confirmed_data'] else '')
            parent_id = chosen.insert('', 'end', text=label,
                      values=('Jogo' if item['kind'] == 'game' else 'Aplicativo', drive,
                              item['status']), open=False)
            for path in item['known_paths']:
                vol = volume_of(path)
                chosen.insert(parent_id, 'end', text=path, values=('Dado associado',vol,
                     'CÓPIA OBRIGATÓRIA ANTES DE FORMATAR' if vol == sys_drive else 'MANTER NO LOCAL / CONFERIR'))
            for path in item['possible_paths'][:30]:
                chosen.insert(parent_id, 'end', text=path, values=('Possível dado', volume_of(path),
                     'NÃO VALIDADO — NÃO PRESUMIR PRESERVADO'))
        if not selected:
            chosen.insert('', 'end', text='Nenhum jogo ou aplicativo marcado para manter.')
        gaps = report_by_drive(roots, getattr(app, 'scan_reports_by_drive', {}))
        pending = sum(x['errors_count']+x['skipped_count'] for x in gaps.values())
        if not gaps:
            gap_status.set('Nenhum inventário carregado. Examine os discos ou importe um relatório anterior.')
        elif pending:
            gap_status.set(f'Varredura: {len(gaps)} unidade(s) no inventário · {pending} erro(s)/exclusão(ões) '
                           'de análise. Revise os caminhos antes da reinstalação.')
        else:
            gap_status.set('Varredura: nenhuma lacuna registrada nas unidades inventariadas; '
                           'isto não substitui a conferência dos dados.')
        app.last_preservation_audit = plan
        return plan, links

    def export():
        plan, links = make_preview()
        path = filedialog.asksaveasfilename(parent=app, defaultextension='.json',
                 initialfile='plano-preservacao-previa.json',
                 filetypes=[('JSON', '*.json')])
        if not path:
            return
        plan['game_save_candidates'] = links
        try:
            atomic_json(Path(path), plan)
            messagebox.showinfo('Plano exportado', 'Relatório salvo. Não é backup nem autorização para excluir.', parent=app)
        except OSError as exc:
            messagebox.showerror('Erro ao exportar', str(exc), parent=app)

    def remove_selected_path_choice():
        """Remove one explicit preservation decision, never a filesystem path."""
        selected = tree.selection()
        if not selected:
            messagebox.showwarning(
                'Escolha um caminho',
                'Selecione uma linha de arquivo ou pasta na tabela de caminhos, abaixo dos jogos.',
                parent=app)
            return
        item = selected[0]
        values = tree.item(item, 'values')
        if not tree.parent(item) or len(values) != 3:
            messagebox.showwarning('Selecione um arquivo ou pasta',
                                   'A linha da unidade não é uma escolha individual.',
                                   parent=app)
            return
        path = str(values[2])
        # Do not remove game/app associations, fictitious summary rows or
        # paths changed since this view was populated.
        if path not in app.choices:
            messagebox.showwarning(
                'Escolha não encontrada',
                'Esta linha não corresponde a uma escolha explícita atual. Atualize o plano.',
                parent=app)
            return
        linked = path in getattr(app, 'auto_save_paths', set())
        if not messagebox.askyesno(
                'Retirar somente do backup?',
                withdraw_confirmation_text(path, linked=linked, drive=sys_drive),
                parent=app):
            return
        if linked:
            # Explicit skip takes precedence over game-data auto detection.
            # The association is preserved, never deleted automatically.
            app.choices[path] = 'skip'
        else:
            app.choices.pop(path)
            app.personal_paths.discard(path)
        app._on_change()  # Invalidates backup preview and saves choices.
        make_preview()

    ttk.Button(bar, text='Atualizar plano', style='Primary.TButton', command=make_preview).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    ttk.Button(bar, text='Importar escolhas da versão anterior', command=app.import_previous_choices).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    ttk.Button(bar, text='Explorar discos', command=lambda: app.navigate(app.home)).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    ttk.Button(bar, text='Exportar JSON', command=export).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    ttk.Button(bar, text='Revisar erros de varredura',
               command=lambda: show_scan_gaps(app, getattr(app, 'deep_scan_report', {}),
                                              getattr(app, 'scan_reports_by_drive', {}))).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    checkbar = ttk.Frame(frame)
    checkbar.pack(fill='x', pady=ESPACO_DENTRO_GRUPO)
    ttk.Button(checkbar, text=f'Conferir fontes do {sys_drive} (sem copiar)',
               command=lambda: show_c_preflight(app, make_preview()[0])).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    check_lbl = ttk.Label(checkbar, text='Pré-checagem rápida de caminhos; NÃO valida o conteúdo nem substitui backup.',
                          foreground=AMBER, wraplength=safe_wraplength(660, padding=PADDING_PAINEL_COMPACTO))
    check_lbl.pack(side='left')
    backupbar = ttk.Frame(frame)
    backupbar.pack(fill='x', pady=ESPACO_DENTRO_GRUPO)
    def open_selective_backup():
        from selective_backup_ui import show_selective_backup
        plan, _ = make_preview()  # Always use the current choices and approved C: paths.
        show_selective_backup(app, plan)
    ttk.Button(backupbar, text='Próximo: revisar backup dos arquivos escolhidos →',
               style='Primary.TButton',
               command=lambda: app.navigate(app.review)).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    backup_lbl = ttk.Label(backupbar, text=f'Fluxo atual: revisão → cópia verificada SHA-256 → recuperação pelo histórico. '
                           f'A revisão de reinstalação do Windows protege o {sys_drive}; o app não apaga nenhum arquivo '
                           'dos outros discos e unidades. Nenhuma formatação é autorizada.',
                           wraplength=safe_wraplength(620, padding=PADDING_PAINEL_COMPACTO),
                           foreground=AMBER)
    backup_lbl.pack(side='left')
    backup_extra = ttk.Frame(frame)
    backup_extra.pack(fill='x', pady=ESPACO_DENTRO_GRUPO)
    ttk.Button(backup_extra, text=f'Backup seletivo avançado do {sys_drive} • v0.6.6',
               command=open_selective_backup).pack(side='left', padx=ESPACO_ENTRE_BOTOES)

    auditbar = ttk.Frame(frame)
    auditbar.pack(fill='x', pady=ESPACO_DENTRO_GRUPO)
    def audit_completeness():
        from completeness_audit_ui_v068 import show_completeness_audit
        show_completeness_audit(app, make_preview()[0])
    ttk.Button(auditbar, text=f'Auditar dados do {sys_drive} • revisão e EFI v0.6.9',
               style='Primary.TButton', command=audit_completeness).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    audit_lbl = ttk.Label(auditbar, text='Somente leitura. Revela locais que ainda exigem revisão; nunca libera formatação.',
                          wraplength=safe_wraplength(600, padding=PADDING_PAINEL_COMPACTO), foreground=AMBER)
    audit_lbl.pack(side='left')
    _bind_wraplength(
        frame,
        (intro_lbl, 0),
        (gap_lbl, 0),
        (notice, 0),
        (check_lbl, 340),
        (backup_lbl, 380),
        (audit_lbl, 380),
        padding=PADDING_PAINEL_COMPACTO,
    )
    make_preview()
    app.update_preservation_preview = make_preview



def show_c_preflight(app, plan=None):
    """Read-only metadata check for explicitly chosen C: source paths."""
    sys_drive = system_drive()
    if plan is None:
        plan = getattr(app, 'last_preservation_audit', None) or {}
    check = prepare_c_preflight(plan.get('requires_verified_backup', []))
    window = tk.Toplevel(app)
    window.title(f'Conferência dos caminhos do {sys_drive} — NÃO é backup')
    sw = window.winfo_screenwidth()
    sh = window.winfo_screenheight()
    window.geometry(safe_window_geometry(1050, 600, sw, sh))
    min_w, min_h = safe_window_size(640, 420, sw, sh)
    window.minsize(min_w, min_h)
    window.resizable(True, True)
    frame = ttk.Frame(window, padding=PADDING_DIALOGO)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Conferência de fontes — somente leitura',
              font=(FONTE_UI, TAMANHO_TITULO_MODAL, 'bold')).pack(anchor='w')
    summary_lbl = ttk.Label(frame, text=(
        f"{check['selected_paths']} caminho(s) no plano, {check['checked_paths']} conferido(s) por metadados, "
        f"{check['not_checked']} não examinados. Nenhum arquivo foi copiado, lido integralmente ou recuperado."),
        wraplength=safe_wraplength(1000, padding=PADDING_DIALOGO), foreground=AMBER)
    summary_lbl.pack(anchor='w', pady=(ESPACO_MINIMO, ESPACO_P))
    actions = ttk.Frame(frame)
    actions.pack(side='bottom', fill='x', pady=(ESPACO_P, 0))
    def export():
        location = filedialog.asksaveasfilename(parent=window, defaultextension='.json',
                      initialfile='conferencia-fontes-c-previa.json',
                      filetypes=[('JSON','*.json')])
        if location:
            try:
                atomic_json(Path(location), check)
                messagebox.showinfo('Conferência exportada',
                    'Arquivo salvo; isto NÃO é um backup.', parent=window)
            except OSError as exc:
                messagebox.showerror('Falha de exportação', str(exc), parent=window)
    ttk.Button(actions, text='Exportar conferência JSON', command=export).pack(side='left')
    ttk.Button(actions, text='Fechar', command=window.destroy).pack(side='right')
    note_lbl = ttk.Label(frame, text=(
        'LOCALIZADO significa somente que o caminho existe. Pasta não foi enumerada; '
        'arquivos e tamanho total não foram verificados. Nenhum status autoriza formatar.'),
        foreground=AMBER, wraplength=safe_wraplength(1000, padding=PADDING_DIALOGO))
    note_lbl.pack(side='bottom', anchor='w', pady=ESPACO_DENTRO_GRUPO)
    _bind_wraplength(frame, (summary_lbl, 0), (note_lbl, 0), padding=PADDING_DIALOGO)
    tablebox = ttk.Frame(frame)
    tablebox.pack(fill='both', expand=True)
    tree = ttk.Treeview(tablebox, columns=('status', 'type', 'note'), show='tree headings')
    tree.heading('#0', text=f'Caminho selecionado no {sys_drive}')
    tree.column('#0', width=390, stretch=True)
    for field, label, width in [('status','Situação',135),('type','Tipo',90),('note','Observação',420)]:
        tree.heading(field, text=label)
        tree.column(field, width=width, stretch=field=='note')
    side = ttk.Scrollbar(tablebox, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=side.set)
    side.pack(side='right', fill='y')
    tree.pack(side='left', fill='both', expand=True)
    for row in check['entries']:
        tree.insert('', 'end', text=row['path'],
                    values=(row['status'], row['file_type'], row['note']))
    return window


def build_installation(app):
    sys_drive = system_drive()
    frame = ttk.Frame(app.installation, padding=PADDING_PAINEL_COMPACTO)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Preparação da instalação limpa do Windows',
              font=(FONTE_UI, TAMANHO_TITULO_ABA, 'bold')).pack(anchor='w', pady=ESPACO_DENTRO_GRUPO)
    warn_lbl = ttk.Label(frame, text='Esta versão prepara e audita o processo. Não executa formatação, exclusão ou mudança de EFI.',
                         wraplength=safe_wraplength(950, padding=PADDING_PAINEL_COMPACTO), foreground=AMBER)
    warn_lbl.pack(anchor='w', pady=ESPACO_ENTRE_BLOCOS)
    _bind_wraplength(frame, (warn_lbl, 0), padding=PADDING_PAINEL_COMPACTO)
    bottom = ttk.Frame(frame)
    bottom.pack(side='bottom', fill='x', pady=(ESPACO_M, 0))
    ttk.Button(bottom, text='Revisar preservação', style='Primary.TButton',
               command=lambda: app.navigate(app.preservation)).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    ttk.Button(bottom, text='Diagnóstico dos discos',
               command=lambda: app.navigate(app.diagnostic)).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    ttk.Button(bottom, text='Recuperação depois do Windows',
               command=lambda: app.navigate(app.recovery)).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    def open_install_audit():
        from completeness_audit_ui_v068 import show_completeness_audit
        roots = getattr(app, 'deep_scan_report', {}) or {}
        plan = build_audit(app.choices, app.catalog_choices, app.catalog_items,
                           getattr(app, 'approved_catalog_paths', {}),
                           getattr(app, 'game_saves', {}),
                           scanned_roots=roots.get('roots', []),
                           removal_candidates=getattr(app, 'cleanup_candidates', ()))
        show_completeness_audit(app, plan)
    ttk.Button(bottom, text=f'Auditoria {sys_drive} / EFI • v0.6.9',
               command=open_install_audit).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    instructions = installation_steps(sys_drive)
    tiles = tk.Frame(frame, bg=BG)
    tiles.pack(fill='both', expand=True)
    for index, (number, title, body) in enumerate(instructions):
        r, c = divmod(index, 2)
        tiles.grid_rowconfigure(r, weight=1)
        tiles.grid_columnconfigure(c, weight=1, uniform='steps')
        box = tk.Frame(tiles, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        box.grid(row=r, column=c, sticky='nsew', padx=(0, ESPACO_M), pady=(0, ESPACO_M))
        tk.Label(box, text=number+'  •  A CONFIRMAR', bg=PANEL, fg=ACCENT,
                 font=(FONTE_UI, TAMANHO_APOIO, 'bold')).pack(anchor='w', padx=ESPACO_M, pady=(ESPACO_M, ESPACO_P))
        tk.Label(box, text=title, bg=PANEL, fg=TEXT,
                 font=(FONTE_UI, TAMANHO_SUBTITULO, 'bold')).pack(anchor='w', padx=ESPACO_M)
        body_lbl = tk.Label(box, text=body, bg=PANEL, fg=MUTED, justify='left',
                            wraplength=safe_wraplength(365, padding=ESPACO_M),
                            font=(FONTE_UI, TAMANHO_CORPO))
        body_lbl.pack(anchor='w', padx=ESPACO_M, pady=(ESPACO_P, ESPACO_M))
        _bind_wraplength(box, (body_lbl, 0), padding=ESPACO_M)


def show_scan_gaps(parent, report=None, per_drive=None):
    """Bounded, actionable, read-only error inspector shared by the scan UI."""
    from scan_gaps import report_by_drive
    summary = report_by_drive(report, per_drive)
    dialog = tk.Toplevel(parent)
    dialog.title('Erros e exclusões por unidade — somente leitura')
    sw = dialog.winfo_screenwidth()
    sh = dialog.winfo_screenheight()
    dialog.geometry(safe_window_geometry(1080, 640, sw, sh))
    min_w, min_h = safe_window_size(640, 420, sw, sh)
    dialog.minsize(min_w, min_h)
    dialog.resizable(True, True)
    frame = ttk.Frame(dialog, padding=PADDING_DIALOGO)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='O que a varredura não conseguiu examinar',
              font=(FONTE_UI, TAMANHO_TITULO_MODAL, 'bold')).pack(anchor='w', pady=ESPACO_DENTRO_GRUPO)
    warn_lbl = ttk.Label(frame, text='Erros e exclusões de análise não autorizam apagar arquivos. '
                         'Inventários salvos podem estar desatualizados.',
                         wraplength=safe_wraplength(990, padding=PADDING_DIALOGO), foreground=AMBER)
    warn_lbl.pack(anchor='w', pady=ESPACO_DENTRO_GRUPO)
    _bind_wraplength(frame, (warn_lbl, 0), padding=PADDING_DIALOGO)
    drives = list(summary)
    if not drives:
        ttk.Label(frame, text='Nenhum inventário encontrado.').pack(anchor='w')
        ttk.Button(frame, text='Fechar', command=dialog.destroy).pack(anchor='e')
        return dialog
    selected_drive = tk.StringVar(value=drives[0])
    menu = ttk.Frame(frame); menu.pack(fill='x', pady=ESPACO_DENTRO_GRUPO)
    ttk.Label(menu, text='Unidade: ').pack(side='left')
    ttk.Combobox(menu, textvariable=selected_drive, values=drives, state='readonly', width=15).pack(side='left')
    total = tk.StringVar()
    ttk.Label(menu, textvariable=total).pack(side='left', padx=ESPACO_M)
    cols = ('type','path','reason')
    visible_count = tk.IntVar(value=0)
    def render(*_):
        tree.delete(*tree.get_children())
        bucket = summary[selected_drive.get()]
        rows = bucket['errors'] + bucket['skipped']
        total.set(f"{len(bucket['errors'])} erro(s) · {len(bucket['skipped'])} não examinado(s) · "
                  f"situação: {bucket['status']}")
        for row in rows[:200]:
            tree.insert('', 'end', values=('Falha de acesso' if row['kind']=='errors' else
                                           'Ignorado na análise', row['path'], row['reason']))
        visible_count.set(min(200, len(rows)))
    def more():
        rows = summary[selected_drive.get()]['errors'] + summary[selected_drive.get()]['skipped']
        old = visible_count.get()
        for row in rows[old:old+200]:
            tree.insert('', 'end', values=('Falha de acesso' if row['kind']=='errors' else
                                          'Ignorado na análise', row['path'], row['reason']))
        visible_count.set(min(len(rows), old+200))
    selected_drive.trace_add('write', render)
    footer = ttk.Frame(frame); footer.pack(side='bottom', fill='x', pady=(ESPACO_P, 0))
    ttk.Button(footer, text='Mostrar mais 200', command=more).pack(side='left', padx=ESPACO_ENTRE_BOTOES)
    def export():
        dest = filedialog.asksaveasfilename(parent=dialog,
                    title='Salvar relatório de lacunas (contém caminhos locais)',
                    defaultextension='.json', filetypes=[('JSON', '*.json')])
        if dest:
            try:
                atomic_json(Path(dest), {'schema':'pcro-scan-gaps-v1', 'drives':summary,
                                         'removal_authorized':False})
                messagebox.showinfo('Relatório salvo','Nenhuma exclusão foi executada.',parent=dialog)
            except OSError as exc:
                messagebox.showerror('Erro ao salvar', str(exc), parent=dialog)
    ttk.Button(footer, text='Exportar relatório JSON', command=export).pack(side='left')
    ttk.Button(footer, text='Fechar', command=dialog.destroy).pack(side='right')
    area = ttk.Frame(frame); area.pack(fill='both', expand=True)
    tree = ttk.Treeview(area, columns=cols, show='headings', height=12)
    for col, label, width in (('type','Categoria',125), ('path','Caminho',570), ('reason','Motivo',280)):
        tree.heading(col, text=label)
        tree.column(col, width=width, stretch=(col!='type'))
    scrollbar = ttk.Scrollbar(area, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y'); tree.pack(side='left', fill='both', expand=True)
    render()
    return dialog
