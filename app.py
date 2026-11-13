"""PC Restore & Optimizer v0.5 experimental — sem operações destrutivas."""
import json
import ntpath
import os
from pathlib import Path
import shutil
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime
import webbrowser

from runtime_volumes import discover_drive_letters, choose_backup_destination
from backup_core import (norm, effective_choice, human_size, build_plan, check_space,
                         copy_backup, restore_test, is_reparse)
from browser_vault import (BROWSERS, BrowserProfile, discover_profiles, profile_files,
                           browser_is_running, create_vault, verify_vault, restore_to_staging)
from backup_identity import make_descriptors, title_for, inventory_text, owner_text
from deep_discovery_ui import show_deep_discovery
from restore_ui import show_restore
from restore_jobs import Job
from app_recovery_ui import show_app_recovery
from browser_recovery_ui import show_recovery
from after_format_ui import show_after_format
from recovery_center_ui import show_recovery_center
from browser_guard import (verify_encrypted_backup as verify_legacy_opera,
                           extract_to_staging as restore_legacy_opera)

from game_saves import find_game_saves, find_installed_games, associate_saves, progress_is_online
from program_catalog import discover_apps, find_desktop_shortcuts, catalog_summary
from app_data import find_app_data, associate_app_data
from backup_features import (friendly_backup_name, backup_labels, set_backup_label,
                             verified_entries)
from restore_elevation import (guarded_restore_selected, is_process_elevated,
                               ElevatedRestoreRefused)
from diagnostics import disk_inventory, system_inventory, make_recommendations, save_report
from backup_preflight_scenario_ui import show_backup_preflight_scenario
from drive_safety_ui import show_drive_safety_dialog
from recovery_kit import create_plan, load_plan, summarize_plan
from optimization_ui import OptimizationPanel
from reinstall_audit import audit_backup, audit_text
from backup_core import atomic_json
import choices_store  # FIX-P3-06-09: grava com atomic_write_text dentro da trava
from transfer_engine import TransferMeter, time_text
from workflow_ui import build_overview, build_preservation, build_installation
from choice_migration import merge_preferences
from plaintext_passwords import TITLE as PASSWORDS_TITLE, alert_lines as password_alert_lines
from plaintext_passwords import find_password_exports, scan_paths as scan_password_paths
from plaintext_passwords import user_folders
from winget_programs import export_after_backup

APP_VERSION = "0.7.0-dev"

# Interface 0.5.4.1 — tokens visuais centralizados (alto contraste + teclado).
BG = '#0C1220'
PANEL = '#192438'
TEXT = '#EFF4FF'
MUTED = '#9CAAC0'
ACCENT = '#9C85FF'
GREEN = '#5DDEB1'
SIDEBAR = '#10192A'
BORDER = '#2B3952'
HOVER = '#27334A'
WHITE = '#FFFFFF'
AMBER = '#F3BE67'

DISKS = ''.join(discover_drive_letters())


def drive_of(path):
    d = os.path.splitdrive(os.path.abspath(str(path)))[0].upper()
    return d if d else None


def open_dir(path):
    if os.name == 'nt':
        os.startfile(str(path))
    else:
        webbrowser.open(Path(path).as_uri())


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'PC Restore & Optimizer | v{APP_VERSION} — Plano Inteligente')
        self.geometry('1400x875')
        self.minsize(1050, 660)
        self.configure(bg=BG)
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        self.style.configure('.', font=('Segoe UI', 10), background=BG, foreground=TEXT)
        self.style.configure('TFrame', background=BG)
        self.style.configure('TLabel', background=BG, foreground=TEXT)
        self.style.configure('TButton', background=PANEL, foreground=TEXT, padding=(14, 10), borderwidth=0, font=('Segoe UI', 10))
        self.style.map('TButton', background=[('active', HOVER), ('disabled', PANEL)], foreground=[('disabled', MUTED)])
        self.style.configure('Primary.TButton', background=ACCENT, foreground=BG,
                             padding=(16, 11), borderwidth=0, font=('Segoe UI', 10, 'bold'))
        self.style.map('Primary.TButton', background=[('active', '#B2A2FF'), ('disabled', BORDER)],
                       foreground=[('disabled', MUTED)])
        self.style.configure('Subtle.TButton', background=SIDEBAR, foreground=TEXT,
                             padding=(13, 10), borderwidth=0)
        self.style.map('Subtle.TButton', background=[('active', HOVER)])
        self.style.configure('TEntry', fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT,
                             padding=7, bordercolor=BORDER)
        self.style.configure('TScrollbar', background=HOVER, troughcolor=BG, borderwidth=0)
        for axis in ('Horizontal', 'Vertical'):
            self.style.configure(axis+'.TScrollbar', background=HOVER, troughcolor=PANEL,
                                 arrowcolor=TEXT, lightcolor=HOVER, darkcolor=HOVER, bordercolor=PANEL)
        self.style.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor=PANEL,
                             bordercolor=PANEL, lightcolor=ACCENT, darkcolor=ACCENT)
        # Tabs remain functional for the existing business logic but are navigated by the sidebar.
        self.style.layout('Hidden.TNotebook.Tab', [])
        self.style.configure('Hidden.TNotebook', background=BG, borderwidth=0, bordercolor=BG, lightcolor=BG, darkcolor=BG)
        self.style.configure('TNotebook', background=BG, borderwidth=0)
        self.style.configure('TNotebook.Tab', padding=(18, 11), background=PANEL, foreground=MUTED, font=('Segoe UI', 10))
        self.style.map('TNotebook.Tab', background=[('selected', HOVER)],foreground=[('selected', TEXT)])
        self.style.configure('Treeview', background=PANEL, fieldbackground=PANEL,
                             foreground=TEXT, rowheight=34, borderwidth=0, font=('Segoe UI', 10))
        self.style.configure('Treeview.Heading', background=HOVER, foreground=TEXT, font=('Segoe UI', 10, 'bold'), padding=(8, 10))
        self.style.map('Treeview', background=[('selected', '#394C75')])
        self.style.configure('TCheckbutton', background=BG, foreground=TEXT, font=('Segoe UI', 10))
        self.style.map('TCheckbutton',background=[('active',BG),('selected',BG),('focus',BG)],foreground=[('active',TEXT),('selected',TEXT)])
        self.style.configure('TCombobox',fieldbackground=PANEL,background=PANEL,foreground=TEXT,selectforeground=TEXT,selectbackground=PANEL)
        self.style.map('TCombobox',fieldbackground=[('readonly',PANEL)],foreground=[('readonly',TEXT)])
        self.choices = {}
        self.cleanup_candidates = set()  # explicit preview-only candidates, NEVER deleted
        self.format_vars = {d: tk.BooleanVar(value=False) for d in DISKS}
        self.dest = tk.StringVar(value=choose_backup_destination(DISKS))
        self.profile = tk.StringVar()
        self.extended = tk.BooleanVar(value=False)
        self.csv_path = tk.StringVar()
        self.bookmarks_html = tk.StringVar()
        self.status = tk.StringVar(value='Inventário local. Nenhuma cópia ou formatação foi executada.')
        self.busy = False
        self.plan = None
        self.plan_stamp = None
        self.created_backup = None
        self.known_profiles = discover_profiles()
        if self.known_profiles:
            self.profile.set(str(self.known_profiles[0].path))
        self.local_state = Path(__file__).resolve().parent / 'preferencias-v05.json'
        self.catalog_choices = {}
        self.auto_save_paths = set()
        self.loaded_recovery_plan = None
        self.catalog_items = {}
        self.catalog_snapshots = {}  # metadata for restoring chosen games/apps after restart
        self.retained_discoveries = {}
        self.game_saves = {}
        self.app_data_paths = {}
        self.approved_catalog_paths = {}
        self.personal_paths = set()
        self.browser_keep_paths = set()
        self.browser_vaults = {}
        self.pending_browser_path = None
        self._migrate_choices_if_needed()
        self._restore_choices()
        self._build()
        self._rehydrate_selected_catalog()
        # FIX-P3-06-09: base para juntar com o que outra janela gravar depois.
        self._choices_base=self._choices_doc()
        self._choices_unsaved=False
        self._choices_last_warning=None  # FIX-P3-06-11: último aviso de "não salvou"
        self._tree_roots()
        self.refresh_browser()
        self.refresh_history()
        # A pesquisa avançada global pode percorrer todas as bibliotecas de jogos.
        # Não iniciá-la silenciosamente quando o usuário pretende examinar só C: ou D:.
        self.catalog_status.set('Catálogo global ainda não pesquisado. Clique em Pesquisar jogos e apps para iniciá-lo.')
        self.protocol('WM_DELETE_WINDOW', self._quit)

    def label(self, parent, text, size=10, fg=TEXT, **kwargs):
        w = tk.Label(parent, text=text, font=('Segoe UI', size), fg=fg, bg=BG,
                     justify='left', anchor='w', **kwargs)
        return w

    def _build(self):
        """Navegação orientada por tarefas. O Notebook continua sendo o controlador das páginas."""
        shell = tk.Frame(self, bg=BG)
        shell.pack(fill='both', expand=True)
        self.sidebar = tk.Frame(shell, bg=SIDEBAR, width=244)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        self._build_sidebar()

        workspace = tk.Frame(shell, bg=BG)
        workspace.pack(side='left', fill='both', expand=True)
        self.page_header = tk.Frame(workspace, bg=BG)
        self.page_header.pack(fill='x', padx=26, pady=(20, 14))
        left = tk.Frame(self.page_header, bg=BG)
        left.pack(side='left', fill='x', expand=True)
        self.page_eyebrow = tk.StringVar(value='VISÃO GERAL  /  ÁREA DE TRABALHO')
        self.page_title = tk.StringVar(value='Seu PC, seus dados, suas escolhas')
        self.page_description = tk.StringVar(value='Gerencie uma reinstalação com clareza, etapa por etapa.')
        tk.Label(left, textvariable=self.page_eyebrow, fg=ACCENT, bg=BG,
                 font=('Segoe UI', 9, 'bold'), anchor='w').pack(anchor='w')
        tk.Label(left, textvariable=self.page_title, fg=TEXT, bg=BG,
                 font=('Segoe UI', 21, 'bold'), anchor='w').pack(anchor='w', pady=(4, 2))
        tk.Label(left, textvariable=self.page_description, fg=MUTED, bg=BG,
                 font=('Segoe UI', 10), anchor='w').pack(anchor='w')
        tk.Label(self.page_header, text='●  MODO SEGURO', bg=PANEL, fg=GREEN,
                 font=('Segoe UI', 9, 'bold'), padx=16, pady=10,
                 highlightbackground=BORDER, highlightthickness=1).pack(side='right', padx=(12, 0))

        footer = tk.Frame(workspace, bg=SIDEBAR, height=39)
        footer.pack(fill='x', side='bottom')
        footer.pack_propagate(False)
        tk.Label(footer, textvariable=self.status, bg=SIDEBAR, fg=MUTED,
                 anchor='w', font=('Segoe UI', 9)).pack(side='left', fill='x', expand=True, padx=24)
        tk.Label(footer, text='Sem exclusão • sem formatação', bg=SIDEBAR,
                 fg=GREEN, font=('Segoe UI', 9)).pack(side='right', padx=20)

        self.tabs = ttk.Notebook(workspace, style='Hidden.TNotebook')
        self.tabs.pack(fill='both', expand=True, padx=(22, 22), pady=(0, 10))
        self.overview = ttk.Frame(self.tabs)
        self.home = ttk.Frame(self.tabs)
        self.preservation = ttk.Frame(self.tabs)
        self.installation = ttk.Frame(self.tabs)
        self.review = ttk.Frame(self.tabs)
        self.history = ttk.Frame(self.tabs)
        self.catalog = ttk.Frame(self.tabs)
        self.catalog_tabs = ttk.Notebook(self.catalog)
        self.inventory = ttk.Frame(self.catalog_tabs)
        self.browsers = ttk.Frame(self.catalog_tabs)
        self.diagnostic = ttk.Frame(self.tabs)
        self.optimization = ttk.Frame(self.tabs)
        self.recovery = ttk.Frame(self.tabs)
        for page, label in (
            (self.overview, 'Visão geral'), (self.home, 'Meu computador'),
            (self.preservation, 'Preservação'), (self.installation, 'Instalar Windows'),
            (self.catalog, 'Seleção avançada'),
            (self.review, 'Revisão do backup'), (self.history, 'Histórico e testes'),
            (self.optimization, 'Otimização'), (self.diagnostic, 'Discos e diagnóstico'), (self.recovery, 'Recuperação / Windows')):
            self.tabs.add(page, text=label)

        build_overview(self)
        ttk.Button(self.overview, text='Depois de formatar  →', style='Primary.TButton',
                   command=self.open_after_format).pack(anchor='w', padx=16, pady=(0, 12))
        self._build_home()
        build_preservation(self)
        build_installation(self)
        self._build_catalog()
        self._build_inventory()
        self._build_browsers()
        self._build_review()
        self._build_history()
        self._build_diagnostic()
        self.optimizer_panel = OptimizationPanel(self.optimization, app_dir=Path(__file__).resolve().parent)
        self.optimizer_panel.pack(fill='both', expand=True)
        self._build_recovery()
        self.tabs.bind('<<NotebookTabChanged>>', self._page_changed)
        self.tabs.select(self.overview)
        self._page_changed()
        for number, page in enumerate((self.overview, self.home, self.preservation,
                                        self.installation, self.recovery, self.optimization,
                                        self.diagnostic, self.history), 1):
            self.bind(f'<Control-Key-{number}>', lambda event, target=page: self.navigate(target))


    def _build_sidebar(self):
        brand = tk.Frame(self.sidebar, bg=SIDEBAR)
        brand.pack(fill='x', padx=22, pady=(28, 30))
        tk.Label(brand, text='◈', bg=SIDEBAR, fg=ACCENT, font=('Segoe UI Symbol', 24)).pack(side='left', padx=(0, 9))
        text_container=tk.Frame(brand,bg=SIDEBAR)
        text_container.pack(side='left', anchor='w')
        tk.Label(text_container, text='PC RESTORE', bg=SIDEBAR, fg=WHITE,
                 font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        tk.Label(text_container, text=f'& OPTIMIZER  •  v{APP_VERSION}', bg=SIDEBAR, fg=MUTED,
                 font=('Segoe UI', 8)).pack(anchor='w')
        self.nav_buttons = {}
        self._nav_heading('MENU PRINCIPAL')
        self._nav_entry('overview', '⌂', 'Visão geral')
        self._nav_entry('home', '▣', 'Meu computador')
        self._nav_entry('preservation', '✓', 'Preservação')
        self._nav_entry('catalog', '☰', 'Seleção avançada')
        self._nav_entry('installation', '↧', 'Instalar Windows')
        self._nav_entry('recovery', '↗', 'Recuperação')
        self.after_format_nav = self._nav_action('✚', 'Depois de formatar', self.open_after_format)
        self.recovery_center_nav = self._nav_action('⟲', 'Central de recuperação',
                                                    self.open_recovery_center)
        self.real_copy_nav = self._nav_action('⇉', 'Cópia protegida para outro disco',
                                              self.open_real_copy)
        self._nav_entry('optimization', '⚡', 'Otimização')
        self._nav_heading('SISTEMA E DIAGNÓSTICO')
        self._nav_entry('diagnostic', '◫', 'Diagnóstico')
        self._nav_entry('history', '◷', 'Histórico e relatórios')
        tk.Frame(self.sidebar, bg=SIDEBAR).pack(fill='both',expand=True)
        notice = tk.Frame(self.sidebar, bg=PANEL, highlightthickness=1,
                          highlightbackground=BORDER)
        notice.pack(fill='x', padx=15, pady=(0, 18))
        tk.Label(notice, text='BACKUP NÃO VERIFICADO NESTA TELA', bg=PANEL,
                 fg=AMBER, font=('Segoe UI', 8, 'bold'), anchor='w').pack(fill='x', padx=13, pady=(12, 5))
        tk.Label(notice, text='Detecção não protege dados. Antes da reinstalação, valide seu backup e o destino.',
                 bg=PANEL, fg=MUTED, justify='left', wraplength=182,
                 font=('Segoe UI', 9)).pack(fill='x', padx=13, pady=(0, 12))
        tk.Label(self.sidebar, text=f'v{APP_VERSION}  •  PLANO SEGURO / PRÉVIA', bg=SIDEBAR,
                 fg=MUTED, font=('Segoe UI', 8)).pack(anchor='w', padx=22, pady=(0, 17))

    def _nav_heading(self, heading):
        tk.Label(self.sidebar, text=heading, bg=SIDEBAR, fg=MUTED,
                 font=('Segoe UI', 8, 'bold'), anchor='w').pack(fill='x', padx=22, pady=(4, 11))

    def _nav_entry(self, key, symbol, text):
        holder = tk.Frame(self.sidebar, bg=SIDEBAR)
        holder.pack(fill='x', padx=10, pady=2)
        stripe = tk.Frame(holder, bg=SIDEBAR, width=4)
        stripe.pack(side='left', fill='y')
        label=tk.Label(holder, text=f'{symbol}    {text}', bg=SIDEBAR, fg=MUTED,
                       anchor='w', padx=12, pady=11, cursor='hand2', takefocus=True,
                       highlightbackground=SIDEBAR, highlightcolor=ACCENT, highlightthickness=1,
                       font=('Segoe UI', 10))
        label.pack(side='left', fill='x', expand=True)
        self.nav_buttons[key] = (holder, stripe, label)
        target_name = 'home' if key=='home' else key
        label.bind('<Button-1>',lambda event, name=target_name:self.navigate(getattr(self,name)))
        label.bind('<Return>',lambda event, name=target_name:self.navigate(getattr(self,name)))
        label.bind('<space>',lambda event, name=target_name:self.navigate(getattr(self,name)))
        label.bind('<Enter>',lambda event, button=label:button.configure(bg=HOVER) if button.cget('fg')!=TEXT else None)
        label.bind('<Leave>',lambda event:self._page_changed())

    def _nav_action(self, symbol, text, command):
        # Item do menu que abre uma janela (não é uma página; fica fora de nav_buttons).
        holder = tk.Frame(self.sidebar, bg=SIDEBAR)
        holder.pack(fill='x', padx=10, pady=2)
        tk.Frame(holder, bg=SIDEBAR, width=4).pack(side='left', fill='y')
        label = tk.Label(holder, text=f'{symbol}    {text}', bg=SIDEBAR, fg=MUTED,
                         anchor='w', padx=12, pady=11, cursor='hand2', takefocus=True,
                         highlightbackground=SIDEBAR, highlightcolor=ACCENT, highlightthickness=1,
                         font=('Segoe UI', 10))
        label.pack(side='left', fill='x', expand=True)
        for sequence in ('<Button-1>', '<Return>', '<space>'):
            label.bind(sequence, lambda event: command())
        label.bind('<Enter>', lambda event: label.configure(bg=HOVER))
        label.bind('<Leave>', lambda event: label.configure(bg=SIDEBAR))
        return label

    def open_recovery_center(self):
        """P2-08: central de recuperação (só leitura); começa pela pasta dos backups.

        A pasta não é conferida aqui (na thread da tela): a busca, num Job,
        já avisa se ela não existir.
        """
        destination = self.dest.get()
        return show_recovery_center(self, folder=Path(destination) if destination else None)

    def open_after_format(self):
        """P2-11: assistente "Depois de formatar" (pede o manifest.json do backup)."""
        return show_after_format(self)

    def open_real_copy(self):
        """P2-09 (fatia 3b-2): janela "Cópia protegida para outro disco".

        Import tardio: a janela só é carregada quando a pessoa a abre. Ela
        avisa antes de ler a lista de discos e só copia depois da confirmação.
        """
        from real_copy_ui import show_real_copy
        return show_real_copy(self)

    def navigate(self, page):
        if page in (self.inventory, self.browsers):
            self.tabs.select(self.catalog)
            self.catalog_tabs.select(page)
        else:
            self.tabs.select(page)
        self._page_changed()

    def _page_changed(self, event=None):
        if not hasattr(self,'tabs') or not hasattr(self,'nav_buttons'):
            return
        selected = self.tabs.select()
        page_map = {
            'overview':('VISÃO GERAL  /  ÁREA DE TRABALHO', 'Seu PC, suas escolhas',
                        'Um caminho claro até a reinstalação segura.'),
            'home':('MEU COMPUTADOR  /  VARREDURA', 'Analisar somente as unidades escolhidas',
                    'Arquivos organizados por disco, jogo e aplicativo.'),
            'preservation':('PRESERVAÇÃO  /  PRÉVIA', 'Escolher o que manter',
                            'No C: requer cópia; nas outras unidades pode permanecer no local.'),
            'catalog':('SELEÇÃO AVANÇADA  /  PRÉVIA', 'Escolher jogos, apps, arquivos e navegadores',
                       'Marcar Manter não é backup. Nada é apagado.'),
            'installation':('WINDOWS  /  PREPARAÇÃO', 'Reinstalar com segurança',
                            'Checklist do backup do C:, EFI e mídia de instalação.'),
            'recovery':('RECUPERAÇÃO  /  REINSTALAÇÃO', 'Recuperar jogos e saves',
                        'Assistentes para a etapa após o novo Windows.'),
            'optimization':('OTIMIZAÇÃO  /  MONITORAMENTO', 'Desempenho e manutenção',
                            'Medições e ajustes conservadores após a recuperação.'),
            'diagnostic':('DIAGNÓSTICO  /  SOMENTE LEITURA', 'Conheça seus discos',
                          'Confira EFI, Storage Spaces e discos físicos.'),
            'history':('HISTÓRICO  /  RELATÓRIOS', 'Backups e verificações anteriores',
                       'Acesso às operações e registros legados.')}
        for name, (holder, stripe, label) in self.nav_buttons.items():
            active = str(getattr(self,name))==selected
            holder.configure(bg=HOVER if active else SIDEBAR)
            stripe.configure(bg=ACCENT if active else SIDEBAR)
            label.configure(bg=HOVER if active else SIDEBAR,
                            fg=TEXT if active else MUTED,
                            font=('Segoe UI',10,'bold' if active else 'normal'))
            if active:
                tag,title,description=page_map[name]
                self.page_eyebrow.set(tag)
                self.page_title.set(title)
                self.page_description.set(description)
        if selected == str(self.preservation) and hasattr(self, 'update_preservation_preview'):
            self.update_preservation_preview()
        if selected == str(self.home) and hasattr(self,'refresh_scan_groups'):
            self.refresh_scan_groups()
        if selected == str(self.catalog) and hasattr(self, 'catalog_tabs'):
            self._catalog_tab_changed()
        if selected == str(self.review):
            self.page_eyebrow.set('FERRAMENTAS AVANÇADAS  /  COMPATIBILIDADE')
            self.page_title.set('Ferramentas de backup e seleção')
            self.page_description.set('Funções existentes mantidas, sem exclusão ou formatação automática.')
        self._refresh_home_metrics()

    def _info_card(self, parent, tag, value_var, description, width=165):
        card=tk.Frame(parent,bg=PANEL,highlightthickness=1,highlightbackground=BORDER)
        card.pack(side='left',fill='both',expand=True,padx=(0,12))
        tk.Label(card,text=tag,bg=PANEL,fg=MUTED,font=('Segoe UI',9),anchor='w').pack(fill='x',padx=18,pady=(15,5))
        tk.Label(card,textvariable=value_var,bg=PANEL,fg=TEXT,font=('Segoe UI',23,'bold'),anchor='w').pack(fill='x',padx=18)
        tk.Label(card,text=description,bg=PANEL,fg=MUTED,font=('Segoe UI',9),anchor='w').pack(fill='x',padx=18,pady=(3,16))
        return card

    def _build_home(self):
        show_deep_discovery(self, container=self.home)

    def _build_legacy_home(self):
        # At small window heights the dashboard remains scrollable, not clipped.
        frame = tk.Frame(self.home,bg=BG)
        frame.pack(fill='both',expand=True,padx=(16,4),pady=(6,8))
        canvas = tk.Canvas(frame,bg=BG,highlightthickness=0,bd=0)
        scrollbar = ttk.Scrollbar(frame,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        panel=tk.Frame(canvas,bg=BG)
        window=canvas.create_window((0,0),window=panel,anchor='nw')
        panel.bind('<Configure>',lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e: canvas.itemconfigure(window,width=e.width))
        self.home_canvas=canvas
        def wheel(event):
            if self.tabs.select()==str(self.home):
                canvas.yview_scroll(-int(event.delta / 120), 'units')
        canvas.bind('<MouseWheel>',wheel)
        panel.bind('<MouseWheel>',wheel)
        hero=tk.Frame(panel,bg=PANEL,highlightthickness=1,highlightbackground=BORDER)
        hero.pack(fill='x',pady=(0,16))
        tk.Label(hero,text='PREPARE SEU PRÓXIMO WINDOWS COM TRANQUILIDADE',bg=PANEL,fg=ACCENT,
                 font=('Segoe UI',9,'bold'),anchor='w').pack(fill='x',padx=24,pady=(22,6))
        tk.Label(hero,text='Primeiro seus dados. Depois, a reinstalação.',bg=PANEL,fg=TEXT,
                 font=('Segoe UI',19,'bold'),anchor='w').pack(fill='x',padx=24)
        tk.Label(hero,text='Descubra jogos e aplicativos, preserve os dados escolhidos e teste a restauração antes de qualquer mudança no sistema.',
                 bg=PANEL,fg=MUTED,font=('Segoe UI',10),anchor='w',justify='left',wraplength=820).pack(fill='x',padx=24,pady=(8,17))
        actions=tk.Frame(hero,bg=PANEL)
        actions.pack(fill='x',padx=24,pady=(0,22))
        ttk.Button(actions,text='Começar pela detecção  →',style='Primary.TButton',
                   command=lambda:self.navigate(self.catalog)).pack(side='left',padx=(0,10))
        ttk.Button(actions,text='Revisar o plano',style='Subtle.TButton',
                   command=lambda:self.navigate(self.review)).pack(side='left',padx=(0,10))
        ttk.Button(actions,text='Navegadores',style='Subtle.TButton',
                   command=lambda:self.navigate(self.browsers)).pack(side='left',padx=(0,10))
        ttk.Button(actions,text='Otimização  →',style='Subtle.TButton',
                   command=lambda:self.navigate(self.optimization)).pack(side='left')
        tk.Label(panel,text='SEU PLANO, EM NÚMEROS',bg=BG,fg=TEXT,
                 font=('Segoe UI',12,'bold'),anchor='w').pack(fill='x',pady=(4,10))
        metric_row=tk.Frame(panel,bg=BG)
        metric_row.pack(fill='x',pady=(0,20))
        self.home_games=tk.StringVar(value='—')
        self.home_apps=tk.StringVar(value='—')
        self.home_chosen=tk.StringVar(value='0')
        self.home_plan=tk.StringVar(value='Não calculado')
        self._info_card(metric_row,'Jogos identificados',self.home_games,'Após a pesquisa')
        self._info_card(metric_row,'Aplicativos',self.home_apps,'Instalações encontradas')
        self._info_card(metric_row,'Escolhas registradas',self.home_chosen,'Escolhas registradas')
        self._info_card(metric_row,'Backup atual',self.home_plan,'Precisa ser validado')
        tk.Label(panel,text='UM CAMINHO CLARO, SEM SURPRESAS',bg=BG,fg=TEXT,
                 font=('Segoe UI',12,'bold'),anchor='w').pack(fill='x',pady=(0,10))
        steps=tk.Frame(panel,bg=BG)
        steps.pack(fill='x')
        for num,title,description,target in (
            ('01','Descubra','Busque jogos, saves e perfis de aplicativos.',self.catalog),
            ('02','Proteja','Confira arquivos extras e cofres de navegador.',self.inventory),
            ('03','Valide','Revise, copie e teste a recuperação.',self.review)):
            card=tk.Frame(steps,bg=PANEL,highlightthickness=1,highlightbackground=BORDER)
            card.pack(side='left',fill='both',expand=True,padx=(0,12))
            tk.Label(card,text=num,bg=PANEL,fg=ACCENT,font=('Segoe UI',15,'bold')).pack(anchor='w',padx=17,pady=(15,6))
            tk.Label(card,text=title,bg=PANEL,fg=TEXT,font=('Segoe UI',12,'bold')).pack(anchor='w',padx=17)
            tk.Label(card,text=description,bg=PANEL,fg=MUTED,font=('Segoe UI',9),
                     wraplength=190,justify='left').pack(anchor='w',padx=17,pady=(6,12))
            ttk.Button(card,text='Abrir etapa  →',style='Subtle.TButton',
                       command=lambda page=target:self.navigate(page)).pack(anchor='w',padx=12,pady=(0,12))
        tk.Label(panel,text='ATENÇÃO  •  Este aplicativo não formata SSDs nem reinstala o Windows. Detectar não é o mesmo que fazer backup.',
                 bg=BG,fg=AMBER,font=('Segoe UI',9),anchor='w',justify='left').pack(fill='x',pady=(18,2))

    def _refresh_home_metrics(self):
        if not hasattr(self, 'home_games'):
            return
        games=sum(i.get('kind')=='game' and not str(k).startswith('savelocal:') for k,i in self.catalog_items.items())
        apps=sum(i.get('kind')=='app' and str(k).startswith('app:') for k,i in self.catalog_items.items())
        self.home_games.set(str(games) if self.catalog_items else 'A pesquisar')
        self.home_apps.set(str(apps) if self.catalog_items else 'A pesquisar')
        self.home_chosen.set(str(sum(v=='keep' for v in self.catalog_choices.values())+
                                  sum(v=='keep' for p,v in self.choices.items() if p not in self.auto_save_paths)+
                                  len(self.browser_keep_paths)))
        self.home_plan.set(human_size(self.plan.total) if self.plan else 'Não calculado')

    def _build_inventory(self):
        self.label(self.inventory,'Seus documentos e arquivos fora dos jogos e aplicativos',size=13,fg=ACCENT).pack(fill='x',padx=14,pady=(16,6))
        self.label(self.inventory,'Adicione só o que você deseja preservar: fotos, documentos, projetos e outras pastas.\nNão é necessário explorar todos os SSDs nem marcar os saves que já foram associados a jogos.',fg=MUTED).pack(fill='x',padx=14,pady=(0,10))
        actions=ttk.Frame(self.inventory);actions.pack(fill='x',padx=14,pady=8)
        ttk.Button(actions,text='+ Adicionar pasta',style='Primary.TButton',command=self.add_folder).pack(side='left',padx=(0,8))
        ttk.Button(actions,text='+ Adicionar arquivo',command=self.add_file).pack(side='left',padx=(0,8))
        ttk.Button(actions,text='Revisar plano  →',command=lambda:self.navigate(self.review)).pack(side='left')
        box=ttk.Frame(self.inventory);box.pack(fill='both',expand=True,padx=14,pady=(8,10))
        self.tree=ttk.Treeview(box,columns=('item','path','decision'),show='headings',selectmode='extended',height=2)
        for col,title,width in [('item','Arquivo / pasta',235),('path','Local original (somente leitura)',570),('decision','Escolha',150)]:
            self.tree.heading(col,text=title)
            self.tree.column(col,width=width,anchor='w')
        ybar=ttk.Scrollbar(box,orient='vertical',command=self.tree.yview)
        xbar=ttk.Scrollbar(box,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set,xscrollcommand=xbar.set)
        xbar.pack(side='bottom',fill='x');ybar.pack(side='right',fill='y')
        self.tree.pack(side='left',fill='both',expand=True)
        bottom=ttk.Frame(self.inventory);bottom.pack(fill='x',padx=14,pady=(0,7))
        ttk.Button(bottom,text='Manter',command=lambda:self.set_choice('keep')).pack(side='left',padx=(0,8))
        ttk.Button(bottom,text='Não incluir no backup',command=lambda:self.set_choice('skip')).pack(side='left',padx=(0,8))
        ttk.Button(bottom,text='Pendente',command=lambda:self.set_choice('pending')).pack(side='left',padx=(0,8))
        ttk.Button(bottom,text='Remover da lista',command=self.remove_personal_item).pack(side='left')
        self.label(self.inventory,'Remover da lista ou não copiar NUNCA apaga os arquivos originais. Dados em G: não podem ser copiados para o mesmo G:.',fg=MUTED).pack(fill='x',padx=14,pady=(0,10))

    def _tree_roots(self):
        # As pastas escolhidas aparecem diretamente. Não navegar por todo o SSD.
        self._update_choices()

    def set_choice(self,choice):
        selected=self.tree.selection()
        if not selected:
            return
        for path in selected:
            self.personal_paths.add(path)
            if choice=='pending':
                self.choices.pop(path,None)
            else:
                self.choices[path]=choice
        self._on_change()

    def remove_personal_item(self):
        for path in self.tree.selection():
            self.personal_paths.discard(path)
            if path not in self.auto_save_paths:
                self.choices.pop(path,None)
        self._on_change()

    def _update_choices(self):
        if not hasattr(self,'tree'):
            return
        for row in self.tree.get_children():
            self.tree.delete(row)
        for path in sorted(self.personal_paths):
            choice=self.choices.get(path,'pending')
            label={'keep':'Manter','skip':'Não copiar','pending':'Pendente'}.get(choice,'Pendente')
            short=os.path.basename(os.path.normpath(path)) or path
            self.tree.insert('','end',iid=path,values=(short,path,label))

    def add_folder(self):
        path=filedialog.askdirectory(title='Escolha uma pasta pessoal para preservar')
        if path:self._add_path(path)

    def add_file(self):
        path=filedialog.askopenfilename(title='Escolha um arquivo pessoal para preservar')
        if path:self._add_path(path)

    def add_saves(self):
        self.navigate(self.catalog)
        self.catalog_tabs.select(self.catalog_games_tab)

    def _add_path(self,path):
        if drive_of(path) not in {f'{d}:' for d in DISKS}:
            messagebox.showwarning('Unidade fora do plano','Escolha uma pasta ou arquivo em uma das unidades disponíveis.')
            return
        if not (os.path.isfile(path) or os.path.isdir(path)) or is_reparse(path):
            messagebox.showwarning('Arquivo não permitido','Escolha um arquivo ou pasta local acessível, sem atalhos ou junções.')
            return
        if os.path.abspath(path)==os.path.abspath(os.path.splitdrive(path)[0]+'\\'):
            messagebox.showwarning('Pasta muito ampla','Selecione uma pasta específica, não a raiz do SSD.')
            return
        name=norm(path)
        self.personal_paths.add(name)
        self.choices[name]='keep'
        self._on_change()
        if self.tree.exists(name):
            self.tree.selection_set(name)
            self.tree.see(name)

    def _build_review(self):
        self.label(self.review,'Backup seletivo dos dados do C:',size=15,fg=ACCENT).pack(fill='x',padx=18,pady=(19,8))
        self.label(self.review,'Somente os arquivos marcados no C: serão copiados. O que não for marcado no C: não entra no backup e se perde quando o instalador formatar o C:. O app não apaga nenhum arquivo dos outros discos e unidades.').pack(fill='x',padx=18,pady=(0,8))
        self.label(self.review,'Nome do backup (opcional — vazio gera um nome pelos itens selecionados):').pack(fill='x',padx=18)
        self.backup_name = tk.StringVar()
        ttk.Entry(self.review, textvariable=self.backup_name).pack(fill='x', padx=18, pady=(0, 8))
        self.label(self.review,'Destino escolhido (pode ser outro SSD ou unidade externa):').pack(fill='x',padx=18)
        drow=ttk.Frame(self.review);drow.pack(fill='x',padx=18,pady=8)
        ttk.Entry(drow,textvariable=self.dest,width=88).pack(side='left',fill='x',expand=True)
        ttk.Button(drow,text='Escolher destino',command=self.choose_dest).pack(side='left',padx=8)
        self.summary=tk.Text(self.review,height=19,wrap='word',bg=PANEL,fg=TEXT,insertbackground=TEXT,
                             relief='flat',font=('Consolas',10),padx=14,pady=14)
        self.summary.pack(fill='both',expand=True,padx=18,pady=9)
        self.summary.insert('end','Gere a revisão do plano antes de iniciar o backup.\n')
        self.summary.configure(state='disabled')
        buttons=ttk.Frame(self.review);buttons.pack(fill='x',padx=18,pady=12)
        ttk.Button(buttons,text='1. Recalcular plano e espaço',style='Primary.TButton',command=self.generate_preview).pack(side='left',padx=(0,12))
        self.backup_btn = ttk.Button(buttons,text='2. Iniciar backup (confirmação dupla)',
                                     command=self.begin_backup, state='disabled')
        self.backup_btn.pack(side='left')
        ttk.Button(buttons,text='Retomar backup interrompido',command=self.select_backup_resume).pack(side='left',padx=(10,0))
        ttk.Button(buttons,text='3. Histórico / Testar restauração',
                   command=lambda:(self.refresh_history(), self.navigate(self.history))).pack(side='left',padx=(10,0))
        ttk.Button(buttons,text='Voltar às escolhas',
                   command=lambda:self.navigate(self.preservation)).pack(side='left',padx=(10,0))
        self.review_feedback=tk.StringVar(value='Backup bloqueado até o plano ser calculado sem avisos impeditivos.')
        tk.Label(self.review,textvariable=self.review_feedback,bg=BG,fg=AMBER,
                 font=('Segoe UI',9),anchor='w').pack(fill='x',padx=18,pady=(0,5))
        self.progress=ttk.Progressbar(self.review,maximum=100)
        self.progress.pack(fill='x',padx=18,pady=(0,15))

    def choose_dest(self):
        d=filedialog.askdirectory(title='Destino para os backups')
        if d:self.dest.set(d);self._on_change()

    def _on_change(self):
        self.plan=None;self.plan_stamp=None
        if hasattr(self,'backup_btn'):
            self.backup_btn.state(['disabled'])
            self.review_feedback.set('Escolhas alteradas. Recalcule o plano antes de copiar.')
        self._update_choices()
        warning=self._save_choices()
        self.status.set(warning or 'Escolhas atualizadas. Gere novamente a revisão antes do backup.')
        self._refresh_home_metrics()
        if hasattr(self, 'refresh_scan_groups') and hasattr(self, 'tabs') and self.tabs.select()==str(self.home):
            self.refresh_scan_groups()
        if hasattr(self, 'update_preservation_preview') and hasattr(self, 'tabs') and self.tabs.select()==str(self.preservation):
            self.update_preservation_preview()

    def _set_summary(self,text):
        self.summary.configure(state='normal');self.summary.delete('1.0','end')
        self.summary.insert('end',text);self.summary.configure(state='disabled')

    def generate_preview(self):
        if self.busy:return
        self.busy=True;self.status.set('Calculando tamanhos e procurando arquivos...')
        # v0.6.1: the C: partition is the only reinstall target.
        # Other disks are preserved in place and are NEVER copied by this action.
        system_drive=os.environ.get('SystemDrive','C:').upper() if os.name=='nt' else 'C:'
        choices={p:v for p,v in self.choices.items() if drive_of(p)==system_drive}
        def worker():
            try:
                plan=build_plan(choices,[f'{d}:\\' for d in DISKS])
                # P2-06: só pelo nome, sem abrir os arquivos; nunca apaga nada.
                try:
                    passwords=find_password_exports(user_folders())
                except Exception:
                    passwords=None
                self.after(0,lambda:self._preview_ready(plan,passwords))
            except Exception as exc:
                self.after(0,lambda e=str(exc):self._error(e))
        threading.Thread(target=worker,daemon=True).start()

    def _password_section(self,plan,passwords):
        """P2-06: aviso de senhas exportadas sem proteção (não bloqueia a cópia)."""
        found=list(getattr(passwords,'findings',[]) or [])
        known={os.path.normcase(str(f)) for f in found}
        # Também avisa sobre arquivos de senhas marcados em outras pastas da cópia.
        found+=[p for p in scan_password_paths(task.source for task in plan.files)
                if os.path.normcase(str(p)) not in known]
        alert=password_alert_lines(found,getattr(passwords,'incomplete',False))
        if not alert:return []
        copied={os.path.normcase(str(task.source)) for task in plan.files}
        going=[p for p in found if os.path.normcase(str(p)) in copied]
        lines=['',PASSWORDS_TITLE+':']+['  '+x for x in alert]
        if going:
            lines.append(f'  ATENÇÃO: {len(going)} desses arquivos entram nesta cópia. '
                         'O backup não é criptografado, então as senhas ficariam legíveis no disco de backup.')
            lines += ['    → '+str(p) for p in going[:20]]
        return lines

    def _preview_ready(self,plan,passwords=None):
        self.busy=False;self.plan=plan
        selected=['C:']  # current Windows reinstall plan, not an executed format
        lines=['PLANO UNIFICADO DE PRESERVAÇÃO  •  nenhuma cópia realizada','',
               'Unidades planejadas para futura formatação: '+(', '.join(selected) or 'nenhuma'),
               f'Arquivos a copiar: {plan.count}  /  tamanho total: {human_size(plan.total)}',
               f'Itens explicitamente marcados Preservar: {len(plan.selected)}',
               f'Itens explicitamente marcados Não copiar: {len(plan.skipped)}','',
               'JOGOS E APLICATIVOS A PRESERVAR:']
        items=[item for key,item in self.catalog_items.items() if self.catalog_choices.get(key)=='keep']
        lines += [f'  + {item.get("name","?")} — {len(item.get("paths",[]))} local(is) associado(s); {len(item.get("possible_paths",[]))} pendente(s)' for item in items] or ['  (nenhum selecionado)']
        lines += ['','NAVEGADORES ESCOLHIDOS (cofre independente):']
        for browser_path in sorted(self.browser_keep_paths):
            vault=self.browser_vaults.get(browser_path)
            lines.append('  + '+browser_path+' | '+('Cofre criado nesta versão: '+vault if vault and os.path.isfile(vault) else 'COFRE NÃO CONFIRMADO; conferir sincronização ou criar cofre'))
        if not self.browser_keep_paths:lines.append('  (nenhum perfil selecionado)')
        lines += ['','ARQUIVOS E PASTAS LOCAIS QUE ENTRAM NA CÓPIA:']
        lines += ['  + '+x for x in plan.selected] or ['  (nenhum)']
        lines += ['','ITENS QUE NÃO SERÃO COPIADOS:']
        lines += ['  - '+x for x in plan.skipped] or ['  (nenhum)']
        descriptors=make_descriptors(self.catalog_items, plan.selected)
        lines += ['', 'IDENTIFICAÇÃO DO BACKUP:', self.backup_name.get().strip() or title_for(descriptors)]
        lines += list(dict.fromkeys(owner_text([r]) + ' | ' + r['root'] for r in descriptors))
        lines += self._password_section(plan,passwords)
        issues=self._preflight(plan,quiet=True)
        if issues:lines+=['','BLOQUEIOS / ALERTAS:']+['  ! '+x for x in issues]
        awaiting_vault=sum(1 for bp in self.browser_keep_paths if not os.path.isfile(self.browser_vaults.get(bp,'')))
        if hasattr(self, 'backup_btn'):
            if issues:
                self.backup_btn.state(['disabled'])
                self.review_feedback.set(f'Cópia bloqueada: {len(issues)} problema(s) a corrigir no plano.')
            else:
                self.backup_btn.state(['!disabled'])
                if awaiting_vault:
                    self.review_feedback.set(
                        f'Backup de arquivos liberado, MAS {awaiting_vault} navegador(es) ainda precisam de cofre/sincronização conferida. '
                        'Os cofres NÃO entram automaticamente nesta cópia.')
                else:
                    self.review_feedback.set('Revisão sem bloqueios para os arquivos locais. Cofres de navegadores são gerados separadamente.')
        self._set_summary('\n'.join(lines))
        self.status.set('Revisão atualizada. Confira tudo antes de confirmar a cópia.')
        self._refresh_home_metrics()

    def _preflight(self,plan,quiet=False):
        issues=list(plan.warnings)
        # Persisted choices may refer to deleted content under the Windows
        # recycle bin. Never silently back up old trashed paths: the user must
        # explicitly withdraw them on the Preservação screen.
        for source in plan.selected:
            path_parts = ntpath.normpath(str(source)).replace('/', '\\').casefold().split('\\')
            if '$recycle.bin' in path_parts or 'recycler' in path_parts:
                issues.append(
                    'Seleção antiga da Lixeira encontrada: '
                    + str(source)
                    + '. Retire esta escolha em Preservação antes de copiar.')
        dst=Path(self.dest.get()).expanduser()
        anchor=dst
        while not anchor.exists() and anchor!=anchor.parent:anchor=anchor.parent
        if not anchor.exists() or not anchor.is_dir():return issues+['Destino inacessível.']
        disk=drive_of(anchor)
        system_drive=os.environ.get('SystemDrive','C:').upper() if os.name=='nt' else None
        if system_drive and disk==system_drive:
            issues.append('Destino no volume do Windows: use unidade preservada e independente antes da reinstalação.')
        fmt={system_drive} if system_drive else set()  # only current Windows volume
        if disk and disk in fmt:
            issues.append(f'O destino {disk} está planejado para formatação: escolha outro SSD antes do backup.')
        if disk and any(drive_of(task.source)==disk for task in plan.files):
            issues.append('O backup não pode ficar na mesma unidade dos dados de origem selecionados.')
        try:
            free, reserve, fit=check_space(plan,anchor)
            if not fit:issues.append(f'Espaço insuficiente: {human_size(free)} livres; reserva de {human_size(reserve)}.')
        except OSError as e:issues.append(f'Erro de disco: {e}')
        if not plan.files:issues.append('Nenhum arquivo marcado para preservar.')
        return issues

    def select_backup_resume(self):
        if self.busy:
            return
        filename=filedialog.askopenfilename(title='Manifesto de backup interrompido v0.5.19',
                 filetypes=[('Manifesto de backup','manifest.json'),('JSON','*.json')])
        if filename:
            self.begin_backup(resume_manifest=filename)

    def begin_backup(self, resume_manifest=None):
        if self.busy:return
        if not self.plan:
            messagebox.showwarning('Revisão necessária','Clique primeiro em “Recalcular plano e espaço”.')
            return
        issues=self._preflight(self.plan)
        # A partial backup may need less space than the full new job.
        if resume_manifest:
            issues=[issue for issue in issues if not issue.startswith('Espaço insuficiente:')]
        if issues:
            messagebox.showerror('Backup bloqueado','\n'.join(issues[:12]))
            return
        selected='C: (somente planejamento; nenhuma formatação automática)'
        info=f'Arquivos: {self.plan.count}\nTamanho: {human_size(self.plan.total)}\nDestino: {self.dest.get()}\nPossível formatação: {selected}\n\nSomente cópia, sem excluir arquivos. Continuar?'
        if resume_manifest:
            info+='\n\nRETOMADA: somente da v0.5.19, com plano idêntico; arquivos anteriores serão conferidos por SHA-256.'
        if not messagebox.askyesno('Confirmar itens e espaço',info):return
        descriptors=make_descriptors(self.catalog_items, self.plan.selected)
        display_name=self.backup_name.get().strip() or title_for(descriptors)
        planned_disks=['C:']
        self.busy=True;plan=self.plan;destination=self.dest.get()
        self.backup_btn.state(['disabled'])
        self.review_feedback.set('Cópia em andamento. Aguarde a verificação completa.')
        meter=TransferMeter(plan.total,plan.count)
        def worker(cancelled, progress):
            return copy_backup(plan,destination,display_name=display_name,progress=progress,
                               planned_disks=planned_disks,item_descriptors=descriptors,
                               cancelled=cancelled,resume_manifest=resume_manifest)
        job=Job(worker)
        def poll_backup():
            if job.latest:
                n,c,b,total,path=job.latest
                self.progress.configure(value=(100*b/total if total else (100*n/c if c else 0)))
                stats=meter.snapshot(bytes_done=b,files_done=min(n-1,c))
                self.review_feedback.set(f'Backup: arquivo {n}/{c} · {human_size(b)}/{human_size(total)} · '
                    f'tempo {time_text(stats["elapsed_sec"])} · {stats["bytes_per_sec"]/1024**2:.1f} MiB/s · '
                    f'{stats["files_per_sec"]:.1f} arq/s · restante ~{time_text(stats["remaining_sec"])}')
            else:
                stats=meter.snapshot()
                self.review_feedback.set(f'Preparando operação… · tempo decorrido {time_text(stats["elapsed_sec"])}')
            result=job.poll()
            if result is None:
                self.after(100,poll_backup)
            elif result[0]=='done':
                self._backup_done(*result[1])
            else:
                self._error(result[1])
        self.after(100,poll_backup)
        self.status.set('Backup iniciado. NÃO desligue o computador durante a operação.')

    def _backup_done(self,folder,manifest):
        self.busy=False;self.created_backup=str(folder)
        self.review_feedback.set('Backup encerrado. Consulte o histórico e teste uma restauração antes de reinstalar o Windows.')
        self.status.set('Resultado do backup: '+manifest['status']+' · '+str(folder))
        perf=manifest.get('performance',{})
        messagebox.showinfo('Resultado do backup',
            f"Status: {manifest['status']}\nVerificados: {len(manifest['files'])} arquivos\n"
            f"Falhas: {len(manifest['errors'])}\nTempo desta operação: {time_text(perf.get('elapsed_sec'))}\n"
            f"Velocidade média: {perf.get('bytes_per_sec',0)/1024**2:.1f} MiB/s\n"
            f"Armazenamento: {manifest.get('transfer_strategy','não identificado')}\n{folder}\n\n"
            'Não formate nenhuma unidade antes de testar a restauração.')
        self.refresh_history()
        self._refresh_home_metrics()
        if manifest.get('status') == 'concluido':
            # Offer the next real step immediately after a successful copy:
            # select the new manifest in the history without starting restore.
            expected = Path(folder) / 'manifest.json'
            for index, listed in enumerate(self.backup_manifests):
                if os.path.normcase(os.path.abspath(str(listed))) == os.path.normcase(os.path.abspath(str(expected))):
                    self.backup_list.selection_clear(0, 'end')
                    self.backup_list.selection_set(index)
                    self.backup_list.see(index)
                    break
            self.navigate(self.history)
            self._offer_program_list(folder, manifest)

    def _offer_program_list(self, folder, manifest):
        """P2-04: só com o "Sim" da pessoa; uma falha aqui nunca afeta o backup."""
        if manifest.get('status') != 'concluido':
            return
        wanted = messagebox.askyesno('Lista de programas',
            'Backup concluído. Quer salvar junto a lista dos programas instalados?\n\n'
            'Ela ajuda a reinstalar tudo depois de formatar. O aplicativo só consulta o '
            'winget (Instalador de Aplicativo da Microsoft); nada é instalado ou removido.')
        if not wanted:
            return
        self.status.set('Salvando a lista de programas…')
        job = Job(lambda cancelled, progress: export_after_backup(folder, manifest, lambda: True))
        def poll_programs():
            result = job.poll()
            if result is None:
                self.after(200, poll_programs)
                return
            kind, value = result
            if kind == 'done' and value and value.get('status') == 'salvo':
                self.status.set(value['message'])
                messagebox.showinfo('Lista de programas', value['message'] +
                    '\nPara ver, abra Restaurar e clique em "Programas do backup".')
            else:
                text = value.get('message') if isinstance(value, dict) else str(value or '')
                self.status.set('Lista de programas não salva. O backup continua válido.')
                messagebox.showwarning('Lista de programas', text or
                    'Não foi possível salvar a lista de programas. O backup continua válido.')
        self.after(200, poll_programs)

    def _build_browsers(self):
        """Fluxo visual: encontrar -> sincronizar -> proteger -> verificar -> recuperar."""
        pane=tk.Frame(self.browsers,bg=BG)
        pane.pack(fill='both',expand=True,padx=(18,4),pady=(4,6))
        canvas=tk.Canvas(pane,bg=BG,highlightthickness=0,bd=0)
        ybar=ttk.Scrollbar(pane,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=ybar.set)
        ybar.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        page=tk.Frame(canvas,bg=BG)
        cid=canvas.create_window((0,0),window=page,anchor='nw')
        page.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(cid,width=e.width))
        self.browser_canvas=canvas
        def section(title,explanation):
            header=tk.Frame(page,bg=BG)
            header.pack(fill='x',pady=(9,6))
            tk.Label(header,text=title,bg=BG,fg=TEXT,font=('Segoe UI',13,'bold'),anchor='w').pack(fill='x')
            tk.Label(header,text=explanation,bg=BG,fg=MUTED,font=('Segoe UI',9),anchor='w',
                     wraplength=960,justify='left').pack(fill='x',pady=(3,0))
        def actions():
            frame=tk.Frame(page,bg=BG)
            frame.pack(fill='x',pady=(5,7))
            return frame

        section('1. Encontre seu perfil','Apenas nomes e caminhos são analisados na descoberta. Nenhuma senha é lida.')
        row=actions()
        self.browser_profile_name=tk.StringVar()
        self.browser_picker=ttk.Combobox(row,textvariable=self.browser_profile_name,state='readonly',width=38)
        self.browser_picker.pack(side='left',fill='x',expand=True)
        self.browser_picker.bind('<<ComboboxSelected>>',self._browser_selected)
        self.browser_want_keep=tk.BooleanVar(value=False)
        ttk.Button(row,text='Pesquisar perfis',command=self._browser_discover).pack(side='left',padx=(8,0))
        ttk.Button(row,text='Escolher pasta',command=self.choose_profile).pack(side='left',padx=(8,0))
        ttk.Checkbutton(page,text='Quero preservar este perfil (incluir no meu plano)',
                        variable=self.browser_want_keep,command=self._mark_browser_keep).pack(anchor='w',pady=(2,6))
        self.browser_status=tk.StringVar(value='Aguardando seleção do navegador.')
        tk.Label(page,textvariable=self.browser_status,bg=PANEL,fg=MUTED,font=('Segoe UI',9),
                 anchor='w',justify='left',wraplength=1030,padx=13,pady=10).pack(fill='x',pady=(3,8))

        section('2. Verifique a sincronização','Entre na conta do navegador correspondente e confirme, nele, senhas, favoritos e demais itens disponíveis.')
        row=actions()
        ttk.Button(row,text='Abrir ajuda oficial',command=self.browser_official_help).pack(side='left',padx=(0,8))
        ttk.Button(row,text='Copiar endereço de sincronização',command=self.browser_copy_sync).pack(side='left')
        self.browser_sync_checked=tk.BooleanVar(value=False)
        ttk.Checkbutton(page,text='Eu conferi a sincronização neste navegador (autodeclaração, não verificada pelo aplicativo)',
                        variable=self.browser_sync_checked).pack(anchor='w',pady=(2,6))

        section('3. Crie uma cópia criptografada','Para favoritos, preferências e parte do histórico. Opcionalmente inclua um CSV de senhas exportado por você.')
        ttk.Checkbutton(page,text='Incluir dados extras de sites (sensíveis; apenas dentro do cofre criptografado)',
                        variable=self.extended,command=self.refresh_browser).pack(anchor='w',pady=(0,5))
        row=actions()
        tk.Label(row,text='Arquivo de senhas exportadas (CSV):',bg=BG,fg=MUTED).pack(side='left')
        ttk.Entry(row,textvariable=self.csv_path,width=53).pack(side='left',fill='x',expand=True,padx=8)
        ttk.Button(row,text='Selecionar arquivo de senhas',command=self.choose_csv).pack(side='left')
        ttk.Button(row,text='Limpar',command=lambda:self.csv_path.set('')).pack(side='left',padx=(8,0))
        row=actions()
        tk.Label(row,text='Arquivo de favoritos exportados (HTML):',bg=BG,fg=MUTED).pack(side='left')
        ttk.Entry(row,textvariable=self.bookmarks_html,width=49).pack(side='left',fill='x',expand=True,padx=8)
        ttk.Button(row,text='Selecionar arquivo de favoritos',command=self.choose_bookmarks_html).pack(side='left')
        ttk.Button(row,text='Limpar',command=lambda:self.bookmarks_html.set('')).pack(side='left',padx=(8,0))
        self.browser_csv_warning=tk.StringVar(value='Um CSV de senhas é texto legível. Nunca envie por chat e não o deixe desprotegido.')
        tk.Label(page,textvariable=self.browser_csv_warning,bg=BG,fg=AMBER,font=('Segoe UI',9),
                 wraplength=1030,justify='left',anchor='w').pack(fill='x',pady=(2,7))
        row=actions()
        ttk.Button(row,text='Criar backup protegido do navegador',style='Primary.TButton',command=self.browser_backup).pack(side='left',padx=(0,10))
        ttk.Button(row,text='Verificar integridade',command=self.browser_verify).pack(side='left',padx=(0,10))
        ttk.Button(row,text='Extrair backup do navegador para teste',command=self.browser_restore).pack(side='left')
        tk.Label(page,text='Destino atual: '+str(self.dest.get())+'   •   Sem sobrescrever perfis originais',
                 bg=BG,fg=MUTED,font=('Segoe UI',9),anchor='w').pack(fill='x',pady=(4,12))

        section('4. Depois de reinstalar o Windows','Instale o navegador, entre na conta e aguarde a sincronização. Se necessário, use os arquivos do cofre para importar manualmente.')
        tk.Label(page,text='Atenção: a restauração NÃO garante cookies, sessões autenticadas, passkeys, licenças ou todas as extensões. '
                      'Arquivos de senha exportados exigem importação no próprio navegador. '
                      'Mantenha uma segunda cópia dos seus dados fora do SSD de backup.',
                 bg=PANEL,fg=MUTED,justify='left',wraplength=1030,padx=13,pady=12).pack(fill='x',pady=(3,10))
        ttk.Button(page, text='Restaurar navegador — assistente', style='Primary.TButton',
                   command=lambda: show_recovery(self)).pack(anchor='w', pady=8)
        self._browser_discover()

    def _mark_browser_keep(self):
        try:
            path=norm(str(self._selected_browser().path))
        except ValueError:
            return
        if self.browser_want_keep.get():self.browser_keep_paths.add(path)
        else:self.browser_keep_paths.discard(path)
        self._on_change()

    def _selected_browser(self):
        index=self.browser_picker.current()
        if index >= 0 and index < len(self.browser_profiles):
            return self.browser_profiles[index]
        raise ValueError('Selecione um perfil antes de continuar.')

    def _browser_discover(self):
        self.browser_profiles=discover_profiles()
        self.browser_picker['values']=[f'{p.browser}  ·  {p.label}  ·  {p.path}' for p in self.browser_profiles]
        if self.browser_profiles:
            self.browser_picker.current(0)
            self._browser_selected()
        else:
            self.browser_profile_name.set('')
            self.profile.set('')
            self.browser_status.set('Nenhum perfil compatível encontrado. Escolha manualmente uma pasta de perfil.')

    def _browser_selected(self,event=None):
        try:
            item=self._selected_browser()
            self.profile.set(str(item.path))
            self.browser_want_keep.set(norm(str(item.path)) in self.browser_keep_paths)
            self.browser_sync_checked.set(False)
            self.csv_path.set('')
            self.bookmarks_html.set('')
            self.refresh_browser()
        except ValueError:
            pass

    def choose_profile(self):
        chosen=filedialog.askdirectory(title='Selecione uma pasta de perfil (não a pasta inteira de instalação)')
        if not chosen:return
        browser=simpledialog.askstring('Identificar navegador',
            'Qual navegador corresponde a esta pasta?\n\n'+', '.join(BROWSERS),parent=self)
        if not browser:return
        match=next((x for x in BROWSERS if x.casefold()==browser.strip().casefold()),None)
        if not match:
            messagebox.showerror('Navegador não suportado','Escolha um nome da lista exibida.')
            return
        p=Path(chosen)
        item=BrowserProfile(match,p.name,p)
        try:
            files=profile_files(item)
            if not files:raise ValueError('Nenhum arquivo de perfil reconhecido. Escolha a pasta de perfil correta.')
        except Exception as error:
            messagebox.showerror('Perfil inválido',str(error));return
        self.browser_profiles.append(item)
        self.browser_picker['values']=[f'{x.browser}  ·  {x.label}  ·  {x.path}' for x in self.browser_profiles]
        self.browser_picker.current(len(self.browser_profiles)-1)
        self._browser_selected()

    def refresh_browser(self):
        try:
            profile=self._selected_browser()
            files=profile_files(profile,self.extended.get())
            total=sum(p.stat().st_size for p in files)
            self.browser_status.set(f'{profile.browser} / {profile.label}  •  {len(files)} arquivos locais reconhecidos ({human_size(total)})\n'
                f'Pasta: {profile.path}\n'
                'Isto NÃO indica que as senhas estejam sincronizadas ou que o cofre já exista.')
        except Exception as error:
            if hasattr(self,'browser_status'):
                self.browser_status.set(('Nenhum perfil foi encontrado automaticamente. Escolha uma pasta de perfil manualmente.'
                    if not getattr(self,'browser_profiles',[]) else 'Não foi possível conferir os arquivos locais: '+str(error)))

    def browser_official_help(self):
        try:
            browser=self._selected_browser().browser
            webbrowser.open(BROWSERS[browser]['help'])
        except ValueError as error:messagebox.showwarning('Navegador',str(error))

    def browser_copy_sync(self):
        try:
            browser=self._selected_browser().browser
            address=BROWSERS[browser]['sync']
            if not address:
                messagebox.showinfo('Sincronização','Este navegador não tem um endereço de sincronização universal conhecido. Consulte a ajuda oficial.')
                return
            self.clipboard_clear();self.clipboard_append(address)
            messagebox.showinfo('Copiado',f'Cole {address} na barra de endereços do próprio {browser}.\nConfira se a conta está sincronizada.')
        except ValueError as error:messagebox.showwarning('Navegador',str(error))

    def choose_csv(self):
        file=filedialog.askopenfilename(title='Escolha CSV que VOCÊ exportou do gerenciador de senhas',filetypes=[('Exportação CSV','*.csv')])
        if not file:return
        if messagebox.askyesno('Arquivo com senhas em texto legível',
            'Este CSV contém senhas em texto legível.\n\n'
            'O aplicativo NÃO lerá as senhas: vai somente criptografar o arquivo.\n'
            'O CSV original continuará existindo até você cuidar dele.\n\n'
            'Deseja incluí-lo como cópia adicional?'):
            self.csv_path.set(file)

    def choose_bookmarks_html(self):
        file=filedialog.askopenfilename(title='Arquivo de favoritos HTML exportado pelo navegador',
            filetypes=[('Favoritos HTML','*.html *.htm')])
        if file:self.bookmarks_html.set(file)

    def _check_browser_destination(self,profile):
        dst=Path(self.dest.get())
        if not dst.exists():
            if not messagebox.askyesno('Criar pasta de backup',f'Criar a pasta {dst}?'):
                raise ValueError('Destino não confirmado.')
            dst.mkdir(parents=True,exist_ok=True)
        fmt={system_drive} if system_drive else set()  # only current Windows volume
        if drive_of(dst) in fmt:
            raise ValueError('Destino está planejado para formatação.')
        if drive_of(dst)==drive_of(profile.path):
            raise ValueError('Escolha destino em unidade DIFERENTE da origem. Preferencialmente use armazenamento externo.')
        if not dst.is_dir():raise ValueError('Destino não é uma pasta.')
        return dst

    def _get_phrase(self,confirm=False):
        pw=simpledialog.askstring('Frase-senha do cofre','Mínimo 12 caracteres. Guarde a frase-senha FORA do computador:',show='*',parent=self)
        if not pw:return None
        if len(pw)<12:
            messagebox.showerror('Frase-senha fraca','Use no mínimo 12 caracteres.')
            return None
        if confirm:
            again=simpledialog.askstring('Confirmar frase-senha','Repita a frase-senha:',show='*',parent=self)
            if pw!=again:
                messagebox.showerror('Frases diferentes','As frases-senha não coincidem.')
                return None
        return pw

    def browser_backup(self):
        if self.busy:return
        try:
            profile=self._selected_browser()
            dst=self._check_browser_destination(profile)
        except Exception as error:
            messagebox.showerror('Cofre de navegador',str(error));return
        if browser_is_running(profile.browser):
            messagebox.showerror('Feche o navegador',f'Feche completamente {profile.browser} antes de copiar o perfil.')
            return
        if not messagebox.askyesno('Confirmar proteção',
            f'Criar cofre criptografado para {profile.browser} ({profile.label})?\n\n'
            'A sincronização de contas NÃO é verificada automaticamente.\n'
            'A cópia NÃO inclui bancos locais de senhas/cookies vinculados ao dispositivo.\n'
            'Feche o navegador e confirme que a origem está correta.'):
            return
        phrase=self._get_phrase(confirm=True)
        if not phrase:return
        csv=self.csv_path.get() or None
        bookmarks=self.bookmarks_html.get() or None
        extended=self.extended.get()
        self.pending_browser_path=norm(str(profile.path))
        self.busy=True
        self.status.set('Criando arquivo criptografado de navegador...')
        def task():
            try:
                result=create_vault(profile,dst,phrase,extended=extended,csv_path=csv,bookmarks_html=bookmarks)
                self.after(0,lambda:self._browser_done(result))
            except Exception as error:
                self.after(0,lambda desc=str(error):self._error(desc))
        threading.Thread(target=task,daemon=True).start()

    def _browser_done(self,result):
        path,count,size,has_csv,has_html=result
        self.busy=False
        if self.pending_browser_path:
            self.browser_vaults[self.pending_browser_path]=str(path)
            self.browser_keep_paths.add(self.pending_browser_path)
            try:
                if norm(str(self._selected_browser().path))==self.pending_browser_path:
                    self.browser_want_keep.set(True)
            except ValueError:
                pass
            self.pending_browser_path=None
            self._on_change()
        self.status.set('Cofre criptografado e verificado: '+str(path))
        self.browser_status.set('Cofre criptografado criado e verificado: '+str(path)+'\nGuarde a frase-senha e faça outra cópia física.')
        messagebox.showinfo('Cofre criado e verificado',
            f'{count} arquivos de perfil protegidos ({human_size(size)}).\n'
            f'Arquivo de senhas exportadas: {"incluído" if has_csv else "não incluído"}. Arquivo de favoritos: {"incluídos" if has_html else "não incluídos"}.\n\n{path}\n\n'
            'Guarde sua frase-senha e uma segunda cópia do cofre. Antes de reinstalar o Windows, TESTE a recuperação.')

    def browser_verify(self):
        path=filedialog.askopenfilename(title='Selecione seu cofre',filetypes=[('Cofre de navegadores','*.pcbrowser'),('Antigo pacote Opera GX','*.opgx')])
        if not path:return
        pw=self._get_phrase()
        if not pw:return
        try:
            result=(verify_legacy_opera(path,pw) if str(path).lower().endswith('.opgx') else verify_vault(path,pw))
            messagebox.showinfo('Integridade autenticada',f'{len(result)} arquivos íntegros. Nenhum dado foi extraído.')
        except Exception as error:messagebox.showerror('Falha de integridade',str(error))

    def browser_restore(self):
        path=filedialog.askopenfilename(title='Selecione seu cofre para teste',filetypes=[('Cofres de navegadores','*.pcbrowser *.opgx')])
        if not path:return
        dest=filedialog.askdirectory(title='Pasta existente para restauração de conferência (NUNCA o perfil ativo)')
        if not dest:return
        if not messagebox.askyesno('Arquivos confidenciais',
            'A restauração irá produzir arquivos locais, possivelmente incluindo CSV com senhas legíveis.\n'
            'Faça isso numa pasta privada e nunca envie seu conteúdo a terceiros.\n\nContinuar?'):
            return
        pw=self._get_phrase()
        if not pw:return
        try:
            out=(restore_legacy_opera(path,dest,pw) if str(path).lower().endswith('.opgx') else restore_to_staging(path,dest,pw))
            messagebox.showinfo('Restauração para conferência',
                f'Os arquivos foram autenticados e extraídos em:\n{out}\n\n'
                'Nenhuma instalação de navegador foi modificada.\n'
                'Use a sincronização ou importe os itens manualmente no próprio navegador.')
        except Exception as error:messagebox.showerror('Não foi possível restaurar',str(error))

    def _build_history(self):
        self.label(self.history,'Histórico de backups e testes',size=15,fg=ACCENT).pack(fill='x',padx=18,pady=(16,8))
        self.label(self.history,'Somente manifeste cópias verificadas; jamais formate apenas com base em uma prévia.',fg=MUTED).pack(fill='x',padx=18)
        self.backup_list=tk.Listbox(self.history,bg=PANEL,fg=TEXT,selectbackground='#235781',
                                    relief='flat',font=('Consolas',11))
        self.backup_list.pack(fill='both',expand=True,padx=18,pady=16)
        ttk.Button(self.history, text='Central de recuperação', style='Primary.TButton',
                   command=self.open_recovery_center).pack(anchor='w', padx=18, pady=4)
        ttk.Button(self.history, text='Ver conteúdo: programas, jogos, saves e arquivos', command=self.show_backup_contents).pack(anchor='w', padx=18, pady=4)
        ttk.Button(self.history, text='Auditar este backup + dados + EFI (sem formatar)',
                   command=self.open_selected_backup_completeness_audit).pack(anchor='w', padx=18, pady=4)
        controls=ttk.Frame(self.history);controls.pack(fill='x',padx=18,pady=(0,14))
        ttk.Button(controls,text='Atualizar histórico',command=self.refresh_history).pack(side='left',padx=(0,9))
        ttk.Button(controls,text='Testar restauração de arquivo pequeno',command=self.test_restore).pack(side='left',padx=(0,9))
        ttk.Button(controls,text='Abrir pasta do backup',command=self.open_backup).pack(side='left',padx=(0,9))
        ttk.Button(controls,text='Renomear rótulo',command=self.rename_backup).pack(side='left',padx=(0,9))
        ttk.Button(controls,text='Escolher arquivo para testar',command=self.restore_chosen).pack(side='left')

    def show_backup_contents(self):
        path = self.selected_manifest()
        if not path:
            messagebox.showinfo('Conteúdo do backup', 'Selecione um backup no histórico.')
            return
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            dlg = tk.Toplevel(self); dlg.title('O que este backup preserva'); dlg.geometry('950x620')
            box = tk.Text(dlg, wrap='word'); box.pack(fill='both', expand=True)
            box.insert('1.0', inventory_text(data)); box.configure(state='disabled')
        except Exception as exc:
            messagebox.showerror('Não foi possível ler o conteúdo', str(exc))

    def refresh_history(self):
        self.backup_list.delete(0,'end');self.backup_manifests=[]
        root=Path(self.dest.get())
        try:
            manifests=sorted(root.glob('backup-*/manifest.json'),reverse=True)
            labels=backup_labels(root)
            for m in manifests[:50]:
                try:
                    j=json.loads(m.read_text(encoding='utf-8'))
                    title=friendly_backup_name(m,j,labels)
                    self.backup_list.insert('end',f"{title} | {j.get('status')} | {j.get('file_count_expected')} arquivos | {human_size(j.get('bytes_verified',0))}")
                    self.backup_manifests.append(m)
                except Exception:pass
        except OSError:pass

    def selected_manifest(self):
        ids=self.backup_list.curselection()
        return self.backup_manifests[ids[0]] if ids else None

    def open_selected_backup_completeness_audit(self):
        """Reuse the existing v0.6.9 auditor with the selected history backup.

        Opening is read-only. SHA-256 of the manifest must be initiated
        explicitly in the audit dialog; no copy, restore or format is run.
        """
        manifest=self.selected_manifest()
        if manifest is None:
            messagebox.showinfo('Auditoria de preservação',
                                'Selecione primeiro um backup em Histórico e relatórios.')
            return
        from completeness_audit_ui_v068 import show_completeness_audit
        show_completeness_audit(self, {}, history_manifest=manifest)

    def test_restore(self):
        manifest=self.selected_manifest()
        if manifest:show_restore(self,manifest,small=True)

    def open_backup(self):
        m=self.selected_manifest()
        if m:open_dir(m.parent)

    def rename_backup(self):
        manifest = self.selected_manifest()
        if not manifest:
            messagebox.showinfo('Histórico', 'Selecione um backup na lista.')
            return
        current = friendly_backup_name(manifest, {}, backup_labels(manifest.parent.parent))
        name = simpledialog.askstring('Nome do backup', 'Novo nome de exibição (não renomeia pastas técnicas):', initialvalue=current)
        if name:
            try:
                set_backup_label(manifest, name)
                self.refresh_history()
            except Exception as exc:
                messagebox.showerror('Não foi possível salvar', str(exc))

    def restore_chosen(self):
        manifest=self.selected_manifest()
        if not manifest:
            messagebox.showinfo('Restauração','Selecione um backup no histórico.')
            return
        show_restore(self,manifest)

    def _build_catalog(self):
        self.label(self.catalog,'Catálogo avançado: clique em Pesquisar para consultar jogos/apps em todas as unidades.\nEsta pesquisa global é independente da varredura seletiva em Meu Computador. Marcar Manter não é backup.',fg=MUTED).pack(fill='x',padx=18,pady=(3,8))
        top=ttk.Frame(self.catalog);top.pack(fill='x',padx=18,pady=6)
        self.catalog_top=top
        ttk.Button(top,text='Pesquisar jogos e apps (todas as unidades)',style='Primary.TButton',command=self.refresh_catalog).pack(side='left',padx=(0,8))
        ttk.Button(top,text='Varredura detalhada',command=lambda:self.navigate(self.home)).pack(side='left',padx=(0,8))
        ttk.Button(top,text='Exportar escolhas',command=self.export_catalog).pack(side='left',padx=(0,8))
        ttk.Button(top,text='+ Arquivo ou pasta',command=lambda:self.navigate(self.inventory)).pack(side='left',padx=(0,8))
        ttk.Button(top,text='Navegadores  →',command=lambda:self.navigate(self.browsers)).pack(side='left',padx=(0,10))
        ttk.Button(top,text='Otimização  →',style='Subtle.TButton',
                   command=lambda:self.navigate(self.optimization)).pack(side='left')
        self.catalog_filter = tk.StringVar()
        searchrow = ttk.Frame(self.catalog)
        self.catalog_searchrow = searchrow
        searchrow.pack(fill='x',padx=18,pady=(0,8))
        self.label(searchrow, 'Filtrar por nome ou origem: ', fg=MUTED).pack(side='left',padx=(0,9))
        ttk.Entry(searchrow, textvariable=self.catalog_filter).pack(side='left',fill='x',expand=True)
        ttk.Button(searchrow,text='Limpar filtro', command=lambda:self.catalog_filter.set('')).pack(side='left',padx=(8,0))
        self.catalog_filter.trace_add('write',lambda *_:self._filter_catalog())
        self.catalog_status = tk.StringVar(value='Aguardando descoberta...')
        self.catalog_section_title=tk.StringVar(value='Jogos e aplicativos identificados')
        self.catalog_status_label=tk.Label(self.catalog,textvariable=self.catalog_status,bg=BG,fg=MUTED,anchor='w')
        self.catalog_status_label.pack(fill='x',padx=18,pady=5)
        panes=self.catalog_tabs;panes.pack(fill='both',expand=True,padx=18,pady=(4,12))
        games=ttk.Frame(panes);apps=ttk.Frame(panes)
        panes.add(games,text='Jogos');panes.add(apps,text='Aplicativos')
        panes.add(self.inventory,text='Arquivos pessoais')
        panes.add(self.browsers,text='Navegadores')
        self.catalog_games_tab=games;self.catalog_apps_tab=apps
        panes.bind('<<NotebookTabChanged>>',self._catalog_tab_changed)
        game_scroll = ttk.Frame(games)
        game_scroll.pack(fill='both',expand=True,pady=8)
        self.games_tree=ttk.Treeview(game_scroll,columns=('source','save','decision'),show='headings',height=2)
        for col,title,width in [('source','Jogo identificado / origem',270),('save','Saves/configurações locais',290),('decision','Escolha',140)]:
            self.games_tree.heading(col,text=title);self.games_tree.column(col,width=width,anchor='w')
        gx = ttk.Scrollbar(game_scroll,orient='horizontal',command=self.games_tree.xview)
        gy = ttk.Scrollbar(game_scroll,orient='vertical',command=self.games_tree.yview)
        self.games_tree.configure(xscrollcommand=gx.set,yscrollcommand=gy.set)
        gx.pack(side='bottom',fill='x')
        gy.pack(side='right',fill='y')
        self.games_tree.pack(side='left',fill='both',expand=True)
        grow=ttk.Frame(games);grow.pack(fill='x',pady=8)
        ttk.Button(grow,text='Manter + saves',command=lambda:self.mark_catalog('game','keep')).pack(side='left',padx=(0,8))
        ttk.Button(grow,text='Não manter',command=lambda:self.mark_catalog('game','skip')).pack(side='left',padx=(0,8))
        ttk.Button(grow,text='Pendente',command=lambda:self.mark_catalog('game','pending')).pack(side='left',padx=(0,8))
        ttk.Button(grow,text='Revisar locais',command=lambda:self.inspect_catalog_paths('game')).pack(side='left')
        self.label(games,'Sem saves encontrados? A escolha ficará registrada, mas o app avisará que o backup do progresso não está garantido.',fg=MUTED).pack(fill='x',pady=6)
        app_scroll = ttk.Frame(apps)
        app_scroll.pack(fill='both',expand=True,pady=8)
        self.apps_tree=ttk.Treeview(app_scroll,columns=('name','category','origin','data','choice'),show='headings',height=2)
        for col,title,width in [('name','Aplicativo / atalho',330),('category','Categoria',160),('origin','Origem / evidência',250),('data','Dados/configs',240),('choice','Escolha',160)]:
            self.apps_tree.heading(col,text=title);self.apps_tree.column(col,width=width,anchor='w')
        ax = ttk.Scrollbar(app_scroll,orient='horizontal',command=self.apps_tree.xview)
        ay = ttk.Scrollbar(app_scroll,orient='vertical',command=self.apps_tree.yview)
        self.apps_tree.configure(xscrollcommand=ax.set,yscrollcommand=ay.set)
        ax.pack(side='bottom',fill='x')
        ay.pack(side='right',fill='y')
        self.apps_tree.pack(side='left',fill='both',expand=True)
        arow=ttk.Frame(apps);arow.pack(fill='x',pady=8)
        ttk.Button(arow,text='Manter + dados',command=lambda:self.mark_catalog('app','keep')).pack(side='left',padx=(0,8))
        ttk.Button(arow,text='Não manter',command=lambda:self.mark_catalog('app','skip')).pack(side='left',padx=(0,8))
        ttk.Button(arow,text='Pendente',command=lambda:self.mark_catalog('app','pending')).pack(side='left',padx=(0,8))
        ttk.Button(arow,text='Revisar locais',command=lambda:self.inspect_catalog_paths('app')).pack(side='left')
        self.label(apps,'Apps de teclado, mouse e headset também precisam de instaladores/drivers compatíveis. Configurações localizadas são candidatos para revisão; não basta reinstalar para recuperá-las.',fg=MUTED).pack(fill='x',pady=6)

    def _catalog_tab_changed(self, event=None):
        if not hasattr(self,'catalog_tabs') or not hasattr(self,'catalog_top'):
            return
        current=self.catalog_tabs.select()
        is_list=current in (str(self.catalog_games_tab),str(self.catalog_apps_tab))
        if is_list:
            if not self.catalog_top.winfo_manager():
                self.catalog_top.pack(fill='x',padx=18,pady=6,before=self.catalog_tabs)
            if not self.catalog_searchrow.winfo_manager():
                self.catalog_searchrow.pack(fill='x',padx=18,pady=(0,8),before=self.catalog_tabs)
            if not self.catalog_status_label.winfo_manager():
                self.catalog_status_label.pack(fill='x',padx=18,pady=5,before=self.catalog_tabs)
        else:
            self.catalog_top.pack_forget()
            self.catalog_searchrow.pack_forget()
            self.catalog_status_label.pack_forget()

    def _filter_catalog(self):
        """Filtro visual reversível: não muda escolhas nem caminhos armazenados."""
        if not hasattr(self, 'catalog_filter') or not hasattr(self, 'catalog_items'):
            return
        needle = self.catalog_filter.get().strip().casefold()
        for key, item in self.catalog_items.items():
            tree = self.games_tree if item.get('kind')=='game' else self.apps_tree
            if not tree.exists(key):
                continue
            text = ' '.join(str(v) for v in tree.item(key,'values')).casefold()
            if not needle or needle in text:
                tree.move(key, '', 'end')
            else:
                tree.detach(key)

    def refresh_catalog(self):
        if not hasattr(self,'games_tree'):
            return
        self.catalog_status.set('Pesquisando saves, arquivos de configuração de jogos, perfis de aplicativos e atalhos...')
        def worker():
            try:
                games=find_installed_games()
                saves=find_game_saves(games)
                apps=discover_apps()
                shortcuts=catalog_summary(apps,find_desktop_shortcuts())
                app_locations=find_app_data(apps)
                self.after(0,lambda:self._catalog_ready(games,saves,apps,shortcuts,app_locations))
            except Exception as exc:
                self.after(0,lambda error=str(exc):self.catalog_status.set('Falha de descoberta: '+error))
        threading.Thread(target=worker,daemon=True).start()

    def _catalog_ready(self,games,saves,apps,shortcuts,app_locations=None):
        import unicodedata
        def matching(value):
            return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if c.isalnum() and not unicodedata.combining(c))
        # Treeview.detach oculta itens; é preciso apagar também os nós desconectados.
        for key in list(self.catalog_items):
            for tree in (self.games_tree, self.apps_tree):
                if tree.exists(key):
                    tree.delete(key)
        self.games_tree.delete(*self.games_tree.get_children())
        self.apps_tree.delete(*self.apps_tree.get_children())
        self.catalog_items.clear();self.game_saves.clear();self.app_data_paths.clear()
        associated_paths=set()
        kind_by_path={s['path']:s.get('data_kind','save') for s in saves}
        for game in games:
            launcher=game.get('launcher','Steam')
            key=launcher.casefold()+':'+str(game['appid'])
            trusted, candidates=associate_saves(game,saves)
            associated_paths.update(trusted+candidates)
            self._catalog_game(key,game['game'],launcher,trusted,candidates,kind_by_path)
            self.catalog_items[key]['install_location'] = game.get('library') or ''
        # Também listar saves conhecidos quando a instalação do jogo não foi identificada.
        # Não confundir uma pasta possivelmente relacionada com um backup confirmado.
        listed=set()
        for item in saves:
            if item['path'] in associated_paths:
                continue
            canonical=matching(item['game'])
            if canonical in listed:
                continue
            listed.add(canonical)
            relevant=[s for s in saves if matching(s['game'])==canonical and s['path'] not in associated_paths]
            trusted=[s['path'] for s in relevant if s.get('confidence')=='alta']
            candidates=[s['path'] for s in relevant if s.get('confidence')!='alta']
            self._catalog_game('savelocal:'+canonical,item['game'],
                'Save local detectado (instalação não confirmada)',trusted,candidates,kind_by_path)
        for item in apps:
            key='app:'+matching(item['name']+' '+item.get('publisher',''))
            self._catalog_app(key,item['name'],item['category'],item['source'],
                              possible=associate_app_data(item,app_locations or []))
            self.catalog_items[key].update(registry_id=item.get('id'), publisher=item.get('publisher'), version=item.get('version'), install_location=item.get('install_location'))
        for item in shortcuts:
            key='shortcut:'+matching(item['name'])
            if key not in self.catalog_items:
                self._catalog_app(key,item['name'],item['category'],'Atalho: instalação não confirmada')
        for saved_key,saved_item in self.retained_discoveries.items():
            if saved_key not in self.catalog_items:
                self._catalog_app(saved_key,saved_item.get('name',saved_key),'Descoberta preservada',saved_item.get('source','Varredura detalhada'))
            self.catalog_items[saved_key].update({k:saved_item.get(k) for k in ('registry_id','edition','publisher','version','install_location','observed_volumes')})
        # Reattach reviewed discoveries using stable source identities, including portable apps.
        report=getattr(self,'deep_scan_report',None)
        if report is None:
            try:
                report=json.loads((Path(__file__).parent/'deteccao-detalhada-v0514.json').read_text(encoding='utf-8'))
                if report.get('schema')!='pcro-discovery-v1':report=None
            except (OSError,ValueError,AttributeError):report=None
            self.deep_scan_report=report
        if report:
            for record in report.get('records',[]):
                candidates=[k for k,i in self.catalog_items.items() if i.get('registry_id')==record['app_id'] or k==record['app_id']]
                key=candidates[0] if candidates else 'deep:'+record['app_id']
                if key not in self.catalog_items:
                    self._catalog_app(key,record['app'],'Identificado na varredura',record['evidence'])
                target=self.catalog_items[key]
                target['registry_id']=record['app_id']
                if record.get('edition'):target['edition']=record['edition']
                path=record['path']
                if path not in target['paths'] and path not in target['possible_paths']:
                    target['possible_paths'].append(path)
                if self.apps_tree.exists(key):
                    vals=list(self.apps_tree.item(key,'values'));vals[-2]=f"{len(target['paths'])} revisado(s), {len(target['possible_paths'])} candidato(s)";self.apps_tree.item(key,values=vals)
        trusted_n=sum(s.get('confidence')=='alta' for s in saves)
        possible_n=len(saves)-trusted_n
        self.catalog_status.set(
            f'{len(games)} jogos · {trusted_n} saves conhecidos · {possible_n} a conferir · '
            f'{len(apps)} aplicativos · {len(shortcuts)} atalhos. '
            'Dados incertos exigem aprovação.')
        self._sync_trusted_catalog_paths()
        self._filter_catalog()
        self._refresh_home_metrics()

    def _catalog_game(self,key,name,source,paths,possible=None,kind_by_path=None):
        possible=list(possible or [])
        kind_by_path=kind_by_path or {}
        prior=[p for p in self.approved_catalog_paths.get(key,[]) if os.path.isfile(p) or os.path.isdir(p)]
        manual_paths=[p for p in prior if p not in paths]
        paths=list(dict.fromkeys([*paths,*prior]))
        possible=[p for p in possible if p not in paths]
        decision=self.catalog_choices.get(key,'pending')
        self.catalog_items[key]=dict(kind='game',name=name,source=source,paths=paths,
                                     possible_paths=possible,manual_paths=manual_paths, path_kinds=dict(kind_by_path))
        self.game_saves[key]=paths
        if paths:
            conf_n=sum(kind_by_path.get(p)=='config' for p in paths)
            save_n=len(paths)-conf_n
            pieces=[]
            if save_n: pieces.append(f'{save_n} local(is) de save')
            if conf_n: pieces.append(f'{conf_n} config(s)')
            status='Conhecidos: '+', '.join(pieces)
            if manual_paths:status+=f' + {len(manual_paths)} incluído(s) manualmente'
            if possible:
                status+=f' + {len(possible)} a conferir'
        elif possible:
            status=f'{len(possible)} possível(is) — CONFERIR'
        else:
            status=('Progresso online; configs a conferir' if progress_is_online(name)
                    else 'Não encontrado / conferir')
        self.games_tree.insert('', 'end',iid=key,values=(name+' — '+source,status,self._choice_label(decision)))

    def _catalog_app(self,key,name,category,source,paths=None,possible=None):
        decision=self.catalog_choices.get(key,'pending')
        if key in self.catalog_items:
            return
        paths,possible=list(paths or []),list(possible or [])
        prior=[p for p in self.approved_catalog_paths.get(key,[]) if os.path.isfile(p) or os.path.isdir(p)]
        manual_paths=[p for p in prior if p not in paths]
        paths=list(dict.fromkeys([*paths,*prior]))
        possible=[p for p in possible if p not in paths]
        self.catalog_items[key]=dict(kind='app',name=name,source=source,category=category,
                                     paths=paths,possible_paths=possible,manual_paths=manual_paths)
        self.app_data_paths[key]=paths
        status=(f'{len(paths)} selecionado(s) + {len(possible)} a conferir' if paths else
                f'{len(possible)} possível(is) — CONFERIR' if possible else 'Dados não localizados — usar varredura detalhada')
        self.apps_tree.insert('','end',iid=key,
                              values=(name,category,source,status,self._choice_label(decision)))

    def _sync_trusted_catalog_paths(self):
        # Mantém escolhas de Manter sem alterar decisões explícitas ou candidatos.
        for key,item in self.catalog_items.items():
            if self.catalog_choices.get(key)!='keep':
                continue
            for path in item.get('paths',[]):
                if (os.path.isdir(path) or os.path.isfile(path)) and norm(path) not in self.choices:
                    self.choices[norm(path)]='keep'
                    self.auto_save_paths.add(norm(path))
        self._on_change()

    def inspect_catalog_paths(self,kind):
        # Confirmação humana de candidatos; não inicia cópia.
        tree=self.games_tree if kind=='game' else self.apps_tree
        keys=tree.selection()
        if len(keys)!=1:
            messagebox.showinfo('Locais de dados','Selecione apenas um jogo ou aplicativo para conferir.')
            return
        key=keys[0]
        item=self.catalog_items.get(key,{})
        trusted=list(item.get('paths',[]))
        possible=list(item.get('possible_paths',[]))
        dlg=tk.Toplevel(self)
        dlg.title('Localizações de dados — '+item.get('name',key))
        dlg.configure(bg=BG)
        dlg.geometry('970x530');dlg.transient(self)
        self.label(dlg,'Locais identificados para '+item.get('name',key),size=13,fg=ACCENT).pack(fill='x',padx=12,pady=(12,5))
        self.label(dlg,'Conhecido = caminho documentado e com arquivos; não garante que todo progresso esteja presente. '
                   'Possível = associação não confirmada; exige sua revisão antes do backup.',fg=MUTED,
                   wraplength=920).pack(fill='x',padx=12,pady=4)
        paths=[('REVISADO' if p in item.get('manual_paths',[]) else 'CONHECIDO',p) for p in trusted]+[('CONFERIR',p) for p in possible]
        box=tk.Listbox(dlg,selectmode='extended',bg=PANEL,fg=TEXT,font=('Consolas',10))
        box.pack(fill='both',expand=True,padx=12,pady=8)
        for status,path in paths:
            box.insert('end',f'[{status}] {path}')
        self.label(dlg,'Nenhum dado encontrado não significa que não exista. Dados em nuvem, '
                   'configurações protegidas e licenças podem exigir login/reinstalação.',fg=MUTED,
                   wraplength=920).pack(fill='x',padx=12,pady=5)
        actions=ttk.Frame(dlg);actions.pack(fill='x',padx=12,pady=10)
        def open_location():
            if not box.curselection():
                return
            path=Path(paths[box.curselection()[0]][1])
            try: open_dir(path if path.is_dir() else path.parent)
            except OSError as error: messagebox.showerror('Abrir',str(error),parent=dlg)
        def approve():
            if self.catalog_choices.get(key)!='keep':
                messagebox.showwarning('Seleção','Primeiro marque Manter para este item.',parent=dlg)
                return
            indices=box.curselection()
            chosen=[paths[i][1] for i in indices if paths[i][0]=='CONFERIR']
            chosen=[p for p in chosen if os.path.isfile(p) or os.path.isdir(p)]
            if not chosen:
                messagebox.showinfo('Confirmação','Selecione um ou mais candidatos [CONFERIR].',parent=dlg)
                return
            if not messagebox.askyesno('Revisar dados candidatos',
                'Você conferiu estes caminhos e quer INCLUÍ-LOS na próxima prévia de backup?\n\n'
                +'\n'.join(chosen[:7])
                +'\n\nAlguns perfis podem conter dados pessoais, tokens ou arquivos grandes. '
                 'Esta ação NÃO copia nem altera os originais.',parent=dlg):
                return
            for path in chosen:
                normalized=norm(path)
                self.choices[normalized]='keep'
                self.auto_save_paths.add(normalized)
                if path not in item['paths']:
                    item['paths'].append(path)
                self.approved_catalog_paths.setdefault(key,[])
                if path not in self.approved_catalog_paths[key]:
                    self.approved_catalog_paths[key].append(path)
            if kind=='game':self.game_saves[key]=item['paths']
            else:self.app_data_paths[key]=item['paths']
            self._on_change()
            dlg.destroy()
            self.refresh_catalog()
            messagebox.showinfo('Caminhos aprovados',
                                'Adicionados à seleção. Vá até Revisão do plano e confira os arquivos e o tamanho '
                                'antes de iniciar qualquer backup.')
        ttk.Button(actions,text='Abrir pasta do caminho',command=open_location).pack(side='left',padx=(0,9))
        ttk.Button(actions,text='Incluir candidatos selecionados (após conferir)',command=approve).pack(side='left',padx=(0,9))
        def add_manual():
            if self.catalog_choices.get(key)!='keep':
                messagebox.showwarning('Seleção','Primeiro marque Manter para este item.',parent=dlg)
                return
            typ=messagebox.askyesnocancel('Selecionar caminho',
                 'Sim = escolher um ARQUIVO.\nNão = escolher uma PASTA.\nCancelar = voltar.',parent=dlg)
            if typ is None:
                return
            chosen=(filedialog.askopenfilename(title='Arquivo de dados deste item',parent=dlg)
                    if typ else filedialog.askdirectory(title='Pasta de dados deste item',parent=dlg))
            if not chosen:
                return
            path=Path(chosen)
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                messagebox.showwarning('Caminho inseguro','Selecione um caminho local válido, não um atalho.',parent=dlg)
                return
            if not messagebox.askyesno('Incluir caminho manual',
                  'Você confirma que este arquivo/pasta pertence ao item '+item.get('name','')
                  +'?\n\n'+str(path)
                  +'\n\nO conteúdo não é inspecionado. Verifique tamanho e privacidade na prévia.',parent=dlg):
                return
            p=str(path)
            self.approved_catalog_paths.setdefault(key,[])
            if p not in self.approved_catalog_paths[key]:
                self.approved_catalog_paths[key].append(p)
            if p not in item['paths']:
                item['paths'].append(p)
            self.choices[norm(p)]='keep'
            self.auto_save_paths.add(norm(p))
            if kind=='game':self.game_saves[key]=item['paths']
            else:self.app_data_paths[key]=item['paths']
            self._on_change()
            dlg.destroy()
            self.refresh_catalog()
            messagebox.showinfo('Caminho adicionado','Caminho incluído na próxima prévia. Nenhum backup foi iniciado.')
        ttk.Button(actions,text='Adicionar arquivo/pasta manualmente',command=add_manual).pack(side='left',padx=(0,9))
        ttk.Button(actions,text='Fechar',command=dlg.destroy).pack(side='right')


    @staticmethod
    def _choice_label(status):
        return {'keep':'Manter / reinstalar','skip':'Não reinstalar','pending':'Pendente'}.get(status,'Pendente')

    def _rehydrate_selected_catalog(self):
        """Show past choices without rescanning unselected units on startup."""
        for key, item in self.catalog_snapshots.items():
            if key not in self.catalog_choices or key in self.catalog_items:
                continue
            kind = item.get('kind')
            if kind == 'game':
                self._catalog_game(key, item.get('name', key),
                                   'Inventário salvo — conferir novamente',
                                   list(item.get('paths', [])), item.get('possible_paths', []))
            else:
                self._catalog_app(key, item.get('name', key),
                                  item.get('category', 'Aplicativo'),
                                  'Inventário salvo — conferir novamente',
                                  list(item.get('paths', [])), item.get('possible_paths', []))
            self.catalog_items[key].update({name: item.get(name) for name in
                 ('install_location', 'registry_id', 'edition', 'publisher', 'version', 'observed_volumes') if item.get(name)})
            self.catalog_items[key]['stale_snapshot'] = True

    def set_unified_entity_choice(self, key, decision, *, name=None, kind='app',
                                  install_location='', possible_paths=(), observed_volume='', notify=True):
        """The sole writer for a game/app intent, regardless of which view calls it.

        A possible save is NOT a confirmed save. A game selected on D: may
        already have verified C: data; those verified paths are kept, never
        relocated or copied merely by marking the game.
        """
        if decision not in ('keep', 'skip', 'pending'):
            raise ValueError('Escolha desconhecida')
        if key not in self.catalog_items:
            if kind == 'game':
                self._catalog_game(key, name or key, 'Varredura por unidade', [], list(possible_paths))
            else:
                self._catalog_app(key, name or key, 'Aplicativo', 'Varredura por unidade',
                                  [], list(possible_paths))
        item = self.catalog_items[key]
        if install_location and not item.get('install_location'):
            item['install_location'] = install_location
        for path in possible_paths:
            if path and path not in item['paths'] and path not in item['possible_paths']:
                item['possible_paths'].append(path)
        self.catalog_choices[key] = decision
        # A unidade onde o usuário marcou o item é evidência de localização,
        # mas não prova em qual disco o programa realmente está instalado.
        if observed_volume and observed_volume not in item.get('observed_volumes', []):
            item.setdefault('observed_volumes', []).append(observed_volume)
        if key.startswith('deep:') or item.get('edition'):
            self.retained_discoveries[key] = dict(item)
        if decision == 'keep':
            for path in item.get('paths', []):
                if os.path.isfile(path) or os.path.isdir(path):
                    canonical = norm(path)
                    self.auto_save_paths.add(canonical)
                    self.choices[canonical] = 'keep'
        else:
            remaining = {norm(path) for other, val in self.catalog_choices.items()
                         if val == 'keep' for path in self.catalog_items.get(other, {}).get('paths', [])}
            stale = self.auto_save_paths - remaining
            for path in stale:
                if self.choices.get(path) == 'keep' and path not in self.personal_paths:
                    self.choices.pop(path, None)
            self.auto_save_paths.intersection_update(remaining)
        target = self.games_tree if item.get('kind') == 'game' else self.apps_tree
        if target.exists(key):
            target.set(key, 'decision' if item.get('kind') == 'game' else 'choice', self._choice_label(decision))
        if notify:
            self._on_change()

    def mark_catalog(self,kind,decision):
        """Legacy list delegates to the same decision writer as Meu Computador."""
        tree=self.games_tree if kind=='game' else self.apps_tree
        selected=tree.selection()
        if not selected:
            messagebox.showinfo('Seleção','Selecione uma linha da lista primeiro.')
            return
        unmatched=[]
        for key in selected:
            self.set_unified_entity_choice(key, decision)
            item=self.catalog_items.get(key,{})
            if decision=='keep' and not item.get('paths'):
                unmatched.append(item.get('name',key))
        if unmatched:
            messagebox.showwarning('Dados ainda não confirmados',
                'Jogos/aplicativos foram marcados para manter, mas os dados locais NÃO estão '
                'automaticamente protegidos:\n'+'\n'.join(unmatched[:12])+
                '\n\nAbra a ficha do item em Meu Computador e confirme seus dados antes de reinstalar.')
        else:
            self.catalog_status.set('Escolhas sincronizadas com Preservação e Meu Computador.')

    def export_catalog(self):
        selected=[(self.catalog_items[key],status) for key,status in self.catalog_choices.items() if key in self.catalog_items and status!='pending']
        if not selected:
            messagebox.showinfo('Exportação','Escolha pelo menos um jogo ou aplicativo primeiro.')
            return
        target=filedialog.asksaveasfilename(title='Salvar plano de reinstalação',defaultextension='.txt',filetypes=[('Texto','*.txt')])
        if not target:
            return
        lines=['PC Restore & Optimizer v0.5.6 — Plano de reinstalação (não é backup de executáveis)','',
               'Escolher Manter registra intenção de reinstalar. Jogos precisam de saves conferidos; aplicativos precisam de instaladores oficiais.','']
        for item,status in sorted(selected,key=lambda v:(v[0]['kind'],v[0]['name'].casefold())):
            lines.append(f"{item['kind'].upper()} | {item['name']} | {self._choice_label(status)} | {item.get('source','')}")
            if item['kind']=='game':
                lines.append('    Saves/configs selecionados: '+(', '.join(item.get('paths',[])) or 'NENHUM — REQUER VERIFICAÇÃO'))
            else:
                lines.append('    Configs/dados selecionados: '+(', '.join(item.get('paths',[])) or 'NENHUM — REQUER VERIFICAÇÃO'))
            if item.get('possible_paths'):
                lines.append('    Candidatos não confirmados: '+', '.join(item['possible_paths']))
        try:
            Path(target).write_text('\n'.join(lines),encoding='utf-8')
            messagebox.showinfo('Plano exportado','Lista de reinstalação salva. Não contém programas nem saves copiados.')
        except OSError as exc:
            messagebox.showerror('Exportação',str(exc))

    def _build_diagnostic(self):
        self.label(self.diagnostic, 'Verificação de hardware e discos',size=14,fg=ACCENT).pack(fill='x',padx=18,pady=(15,7))
        self.label(self.diagnostic, 'Coleta SOMENTE leitura. A letra do volume não identifica o SSD físico; discos dinâmicos/EFI/pools exigem checagem independente.\nNenhum ajuste de BIOS, serviço, registro, Windows ou disco será executado.',fg=MUTED).pack(fill='x',padx=18,pady=6)
        actions=ttk.Frame(self.diagnostic);actions.pack(fill='x',padx=18,pady=8)
        ttk.Button(actions,text='Analisar computador e discos',command=self.run_diagnostics).pack(side='left',padx=(0,8))
        ttk.Button(actions,text='Simular destino de backup (somente leitura)',
                   command=lambda: show_backup_preflight_scenario(self)).pack(side='left',padx=(0,8))
        ttk.Button(actions,text='Exportar relatório JSON',command=self.export_diagnostics).pack(side='left',padx=(0,8))
        ttk.Button(self.diagnostic,text='Conferir origens e destinos (somente leitura)',
                   command=lambda: show_drive_safety_dialog(self)).pack(anchor='w',padx=18,pady=(0,6))
        self.diagnostic_data=None
        self.diagnostic_text=tk.Text(self.diagnostic,bg=PANEL,fg=TEXT,wrap='word',font=('Consolas',10),relief='flat')
        self.diagnostic_text.pack(fill='both',expand=True,padx=18,pady=12)
        self._write_text(self.diagnostic_text,'Clique em Analisar.\n\nEste módulo oferece recomendações, não executa otimizações.\n' )

    @staticmethod
    def _write_text(widget,txt):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('end',txt);widget.configure(state='disabled')

    def run_diagnostics(self):
        if self.busy:return
        self.busy=True
        self.status.set('Coletando dados locais somente leitura...')
        def worker():
            try:
                disks=disk_inventory()
                hardware=system_inventory()
                report=dict(disks=disks,hardware=hardware,recommendations=make_recommendations(disks,hardware))
                self.after(0,lambda:self._diagnostics_ready(report))
            except Exception as exc:
                self.after(0,lambda e=str(exc):self._error('Diagnóstico: '+e))
        threading.Thread(target=worker,daemon=True).start()

    def _diagnostics_ready(self,report):
        self.busy=False;self.diagnostic_data=report
        hw=report.get('hardware',{});d=report.get('disks',{})
        cpu=hw.get('cpu') or {}
        if isinstance(cpu,list): cpu=cpu[0] if cpu else {}
        text=['INVENTÁRIO — consultas de leitura',
              'CPU: '+str(cpu.get('Name','indisponível')),
              'Sistema: '+str((hw.get('memory') or {}).get('Caption','indisponível') if isinstance(hw.get('memory'),dict) else 'indisponível'),
              '', 'DISCOS / DISPOSITIVOS (inclui virtuais):']
        for disk in d.get('disks',[]):
            text.append('  #'+str(disk.get('Number'))+' | '+str(disk.get('FriendlyName'))+' | '+str(disk.get('BusType'))+' | '+str(disk.get('Size'))+' bytes | Boot='+str(disk.get('IsBoot'))+' | System='+str(disk.get('IsSystem')))
        text.append('');text.append('VOLUMES:')
        for v in d.get('volumes',[]):
            text.append('  '+str(v.get('DriveLetter') or '?')+': | '+str(v.get('FileSystemLabel') or '')+' | '+str(v.get('SizeRemaining'))+' livres de '+str(v.get('Size'))+' bytes')
        text.append('')
        text.append('ASSOCIAÇÕES INFORMADAS POR GET-PARTITION (NÃO CONFIRMAM DISCO FÍSICO):')
        mappings = d.get('storage_mapping') or {}
        for item in mappings.get('letter_mapping', []):
            disk_numbers = item.get('disk_numbers') or []
            disks_label = ', '.join('Disco '+str(n) for n in disk_numbers) if disk_numbers else 'NÃO IDENTIFICADO'
            text.append('  '+str(item.get('letter'))+': -> '+disks_label+' | '+str(item.get('status')))
        text.append('  Conferir separadamente EFI, discos dinâmicos, pools e volumes sem letra.')
        extents = d.get('extent_mapping') or {}
        text.extend(['', 'EXTENSÕES DE VOLUME (IOCTL — SOMENTE LEITURA):'])
        for row in extents.get('volumes', []):
            label = ', '.join(x+':' for x in row.get('letters', [])) or 'Sem letra'
            numbers = row.get('disk_numbers') or []
            number_text = ', '.join('Disco '+str(n) for n in numbers) if numbers else 'NÃO IDENTIFICADO'
            text.append('  '+label+' -> '+number_text+' | '+str(row.get('status')))
            text.append('     '+str(row.get('reason', '')))
        text.append('  IMPORTANTE: disco lógico != disco físico; Spaces e discos dinâmicos exigem conferência adicional.')
        cross = d.get('cross_source') or {}
        text.extend(['', 'CONFERÊNCIA ENTRE FONTES (SEM ALTERAÇÕES NO ARMAZENAMENTO):'])
        for number in cross.get('unlisted_extent_disks', []):
            text.append('  Disco '+str(number)+': presente em extents; ausente de Get-Disk. REVISÃO OBRIGATÓRIA.')
        for number, count in cross.get('unmounted_volumes_on_unlisted_disks', {}).items():
            text.append('  Disco '+str(number)+': '+str(count)+' volume(s) sem letra.')
        text.append('  EFI ativa: NÃO COMPROVADA; destino de backup: NÃO VERIFICADO.')
        physical = d.get('physical_evidence') or {}
        text.extend(['', 'EVIDÊNCIA COMPLEMENTAR DE DISCOS (WIN32_DISKDRIVE):'])
        text.append('  Quantidade retornada pela WMI: '+str(physical.get('wmi_device_count', 'desconhecida')))
        for item in physical.get('disagreements', []):
            text.append('  Disco '+str(item.get('disk_number'))+': WMI='+
                        ('PRESENTE' if item.get('present_in_wmi') else 'NÃO LOCALIZADO'))
            if item.get('present_in_wmi'):
                text.append('     Modelo informado: '+str(item.get('wmi_model', '')))
        part_evidence = d.get('partition_evidence') or {}
        text.extend(['', 'PARTIÇÕES COMPLEMENTARES (WIN32_DISKPARTITION — SOMENTE LEITURA):'])
        for group in part_evidence.get('disks_of_interest', []):
            text.append('  Disco '+str(group.get('disk_index'))+' | '+str(group.get('status')))
            for item in group.get('partitions', []):
                size = str(item.get('bytes')) if item.get('bytes') is not None else '?'
                text.append('    Partição '+str(item.get('partition_index'))+
                            ' | '+str(item.get('type'))+' | '+size+' bytes')
                if item.get('efi_type_candidate'):
                    text.append('      POSSÍVEL TIPO EFI (não comprova EFI ativa)')
        boot = d.get('boot_evidence') or {}
        text.extend(['', 'GERENCIADOR DE BOOT (BCDEDIT /ENUM — SOMENTE LEITURA):'])
        text.append('  Estado da consulta: '+str(boot.get('status', 'indisponível')))
        if boot.get('status') == 'unavailable':
            reason = {
                'permission_denied': 'Acesso negado. Pode exigir executar diagnóstico como administrador.',
                'timeout': 'Tempo limite excedido.',
                'tool_missing': 'BCDEdit não encontrado.',
                'query_failed': 'Consulta falhou por motivo ainda não determinado.',
                'unsupported_os': 'Sistema não suportado.'
            }.get(boot.get('reason'), 'Motivo desconhecido.')
            text.append('  Motivo: '+reason)
        for path in boot.get('nt_volume_devices', []):
            text.append('  Dispositivo NT informado: '+str(path))
        text.append('  EFI ativa: NÃO VERIFICADA. Este relatório NÃO autoriza alterações.')
        nt = d.get('nt_volume_mapping') or {}
        text.extend(['', 'CORRELAÇÃO DE NOMES NT (QUERYDOSDEVICE — SOMENTE LEITURA):'])
        for item in nt.get('volumes', []):
            letters = ', '.join(x+':' for x in item.get('letters', [])) or 'Sem letra'
            disks = ', '.join('Disco '+str(n) for n in item.get('disk_numbers', [])) or 'Disco desconhecido'
            device = str(item.get('nt_device') or 'NÃO IDENTIFICADO')
            text.append('  '+device+' | '+letters+' | '+disks+
                        ' | '+str(item.get('status')))
            if item.get('bootmgr_device_match'):
                text.append('    Corresponde ao dispositivo reportado por BCDEdit; EFI ativa não comprovada.')
        text.append('  Identificador HarddiskVolume NÃO equivale a número de disco físico.')
        dependency = d.get('boot_dependency') or {}
        text.extend(['', 'DEPENDÊNCIA DO BOOT MANAGER (METADADOS — SOMENTE LEITURA):'])
        windows = dependency.get('windows_disk_numbers') or []
        manager = dependency.get('bootmgr_disk_numbers') or []
        text.append('  Windows em uso: '+(', '.join('Disco '+str(n) for n in windows) if windows else 'NÃO VERIFICADO'))
        text.append('  BOOTMGR registrado: '+(', '.join('Disco '+str(n) for n in manager) if manager else 'NÃO VERIFICADO'))
        text.append('  Situação: '+str(dependency.get('status', 'unverified')))
        text.append('  Entrada UEFI realmente utilizada: NÃO VERIFICADA.')
        if dependency.get('status') == 'separate_disks_reported':
            text.append('  ALERTA: BOOTMGR e Windows em discos diferentes. NÃO alterar, desconectar ou formatar partições.')
        text.append('  Backup e prontidão de reinstalação: NÃO VERIFICADOS.')
        firmware = d.get('firmware_order') or {}
        text.extend(['', 'ORDEM DE BOOT REGISTRADA NO UEFI (BCDEDIT — SOMENTE LEITURA):'])
        text.append('  Estado da consulta: '+str(firmware.get('status', 'unavailable')))
        if firmware.get('reason') not in ('none', None):
            text.append('  Motivo: '+str(firmware.get('reason')))
        count = firmware.get('order_entry_count')
        if count is not None:
            text.append('  Entradas registradas na ordem: '+str(count))
        if firmware.get('bootmgr_in_order') is True:
            text.append('  Windows Boot Manager: PRESENTE na ordem de firmware.')
            device = firmware.get('bootmgr_nt_device')
            if device:
                text.append('  Dispositivo registrado: '+str(device))
        registered = firmware.get('bootmgr_disks') or []
        if registered:
            text.append('  Disco(s) informado(s): '+', '.join('Disco '+str(x) for x in registered))
        if firmware.get('status') == 'registered_bootmgr_cross_disk':
            text.append('  ALERTA: BOOTMGR registrado em disco diferente do Windows.')
        text.append('  UEFI BootCurrent: NÃO VERIFICADO; EFI ativa: NÃO COMPROVADA.')
        text.append('  Este diagnóstico NÃO autoriza formatação, desconexão nem reinstalação.')
        spaces = d.get('spaces_membership') or {}
        text.extend(['', 'ESPAÇOS DE ARMAZENAMENTO — MEMBROS FÍSICOS (SOMENTE LEITURA):'])
        text.append('  Estado: '+str(spaces.get('status', 'não consultado')))
        for vd in spaces.get('virtual_disks', []):
            name = str(vd.get('virtual_name', 'disco virtual'))
            nums = vd.get('logical_disk_numbers') or []
            label = ', '.join('Disco lógico '+str(n) for n in nums) if nums else 'Disco lógico não identificado'
            text.append('  '+name+' | '+label+' | '+str(vd.get('status')))
            text.append('    Resiliência informada: '+str(vd.get('resiliency_reported', 'desconhecida')))
            text.append('    Membros físicos informados: '+str(vd.get('member_count', 0)))
            for m in vd.get('members', []):
                text.append('      '+str(m.get('model', 'Modelo desconhecido'))+
                            ' | DeviceId '+str(m.get('device_id', '?'))+
                            ' | Saúde '+str(m.get('health', 'desconhecida')))
        text.append('  Membros do pool NÃO garantem backup em hardware independente.')
        candidates = d.get('backup_candidates') or []
        text.extend(['', 'PRÉ-CHECAGEM DE DESTINOS DE BACKUP (SOMENTE LEITURA):'])
        text.append('  Unidades listadas são candidatas para análise, NÃO destinos aprovados.')
        for item in candidates:
            letter = str(item.get('target_letter', '?'))
            numbers = item.get('destination_logical_disks') or []
            disks_label = ', '.join('Disco '+str(n) for n in numbers) if numbers else 'DISCO NÃO CONFIRMADO'
            free_bytes = item.get('free_bytes_reported')
            free_label = (f'{free_bytes / 1024**3:.1f} GiB ({free_bytes} bytes)'
                          if type(free_bytes) is int and free_bytes >= 0 else 'desconhecido')
            text.append('  '+letter+': | '+disks_label+' | livres informados: '+free_label+
                        ' | '+str(item.get('status', 'requires_review')))
            for risk in item.get('risk_details', []):
                text.append('    ATENÇÃO: '+str(risk))
            for pool in item.get('storage_spaces_membership', []):
                text.append('    Pool: '+str(pool.get('virtual_name','desconhecido'))+
                            ' | membros relatados: '+str(pool.get('member_count_reported','?'))+
                            ' | resiliência: '+str(pool.get('resiliency_reported','?')))
            for blocker in item.get('blockers', []):
                text.append('    BLOQUEIO: '+str(blocker))
        text.append('  Espaço livre em GiB é informativo; não representa espaço reservado para backup.')
        text.append('  BOOTMGR registrado NÃO comprova entrada UEFI efetivamente usada (BootCurrent).')
        text.append('  requires_review é esperado enquanto origem, tamanho e independência não forem validados.')
        text.append('  Origem e tamanho do backup não selecionados neste diagnóstico.')
        text.append('  Independência física, espaço para plano real e SHA-256: NÃO VERIFICADOS.')
        text.append('  Nenhuma unidade foi aprovada automaticamente para backup/reinstalação.')
        text.extend(['','ALERTAS E RECOMENDAÇÕES:'])
        text.extend('  • '+a for a in report.get('recommendations',[]))
        text.extend(['','Sem teste SMART aprofundado, sem temperatura e sem prova de que o backup está em unidade física independente.',
                     'ANTES DE REINSTALAR: cópia extra, verificação de saves e identificação manual dos discos por modelo/serial.'])
        self._write_text(self.diagnostic_text,'\n'.join(text))
        self.status.set('Relatório coletado. Não foi aplicado qualquer ajuste.')

    def export_diagnostics(self):
        if not self.diagnostic_data:
            messagebox.showinfo('Diagnóstico','Analise o computador primeiro.')
            return
        target=filedialog.asksaveasfilename(title='Salvar relatório de diagnóstico (pode conter modelo e serial de disco)',defaultextension='.json',filetypes=[('JSON','*.json')])
        if not target:return
        try:
            save_report(target,self.diagnostic_data)
            messagebox.showinfo('Diagnóstico','Relatório salvo. Revise dados de identificação antes de compartilhá-lo.')
        except Exception as exc:messagebox.showerror('Erro',str(exc))

    def _build_recovery(self):
        self.label(self.recovery,'Plano de continuidade após o Windows',size=14,fg=ACCENT).pack(fill='x',padx=18,pady=(15,7))
        self.label(self.recovery, 'Antes: selecione jogos/apps, confira saves e valide backups; exporte o plano em uma unidade que NÃO será formatada.\nDepois: abra o app novamente, importe seu plano, reinstale apps de fontes oficiais e restaure arquivos em pasta de conferência.',fg=MUTED).pack(fill='x',padx=18,pady=6)
        ttk.Button(self.recovery, text='Recuperar aplicativos, jogos e saves — assistente', style='Primary.TButton', command=lambda: show_app_recovery(self)).pack(anchor='w', padx=18, pady=5)
        buttons=ttk.Frame(self.recovery);buttons.pack(fill='x',padx=18,pady=12)
        ttk.Button(buttons,text='1. Exportar plano para usar depois',command=self.make_recovery_kit).pack(side='left',padx=(0,9))
        ttk.Button(buttons,text='2. Abrir plano após reinstalar',command=self.read_recovery_kit).pack(side='left',padx=(0,9))
        ttk.Button(buttons,text='3. Ir para restauração de backup',command=lambda:self.tabs.select(self.history)).pack(side='left',padx=(0,9))
        audit_controls=ttk.Frame(self.recovery); audit_controls.pack(fill='x',padx=18,pady=(0,4))
        ttk.Button(audit_controls,text='4. Restaurar saves do jogo',command=self.restore_game_from_plan).pack(side='left',padx=(0,9))
        ttk.Button(audit_controls,text='5. Conferir TODO o backup (SHA-256)',command=self.audit_selected_backup).pack(side='left',padx=(0,10))
        self.audit_cancel=ttk.Button(audit_controls,text='Cancelar auditoria',command=self.cancel_audit,state='disabled')
        self.audit_cancel.pack(side='left')
        self.audit_cancel_event=threading.Event()
        self.audit_last_report=None
        ttk.Button(audit_controls,text='Salvar relatório de auditoria',command=self.export_audit).pack(side='left',padx=(9,0))
        self.recovery_text=tk.Text(self.recovery,bg=PANEL,fg=TEXT,wrap='word',font=('Consolas',10),relief='flat')
        self.recovery_text.pack(fill='both',expand=True,padx=18,pady=10)
        self._write_text(self.recovery_text, 'Segurança antes de formatar:\n\n'
          '  [ ] Testar restauração de saves e arquivos essenciais.\n'
          '  [ ] Fazer segunda cópia em outro dispositivo físico.\n'
          '  [ ] Guardar senhas, contas, licenças e chaves de recuperação (não compartilhe).\n'
          '  [ ] Conferir disco físico de destino e EFI/boot (o Windows pode depender de 2 SSDs).\n'
          '  [ ] Manter a pasta do aplicativo e o plano em disco preservado.\n'
          '  [ ] Preparar mídia oficial de instalação do Windows.\n\n'
          'v0.5.13: reinstalação assistida de aplicativos pelo WinGet. Não formata nem instala o Windows.\n'
          'A auditoria integral exige selecionar um backup concluído em Backups e testes.\n')

    def audit_selected_backup(self):
        """Full read-only hash audit. Deliberately does not authorize formatting."""
        m=self.selected_manifest()
        if not m:
            messagebox.showinfo('Auditoria','Selecione primeiro o backup desejado em Backups e testes.\n'
                                'Depois volte a Após reinstalar Windows para fazer a auditoria integral.')
            self.navigate(self.history)
            return
        if not messagebox.askyesno('Auditoria integral',
            'Calcular novamente SHA-256 de TODOS os arquivos do backup selecionado?\n'
            'Pode demorar horas em grandes backups. A operação apenas LÊ os dados.'):
            return
        self.audit_cancel_event.clear()
        self.audit_cancel.configure(state='normal')
        self.status.set('Conferindo a integridade integral do backup. Não feche o aplicativo.')
        self._write_text(self.recovery_text,'Auditoria de todos os arquivos em andamento...\n'
                                           'Isso não autoriza a formatação. Aguarde a conferência.')
        def worker():
            try:
                def progress(done,total):
                    if done % 10 == 0 or done == total:
                        self.after(0,lambda d=done,t=total:self.status.set(f"Auditoria SHA-256: {d}/{t} arquivos conferidos"))
                result=audit_backup(m,on_progress=progress,cancelled=self.audit_cancel_event)
                self.after(0, lambda r=result:self._audit_result(r))
            except Exception as exc:
                self.after(0, lambda error=str(exc):self._audit_error(error))
        threading.Thread(target=worker,daemon=True).start()

    def cancel_audit(self):
        self.audit_cancel_event.set()
        self.status.set('Cancelando auditoria; aguarde o fim da leitura atual.')

    def _audit_result(self, result):
        self.audit_cancel.configure(state='disabled')
        self.audit_last_report=result
        self._write_text(self.recovery_text, audit_text(result))
        self.status.set('Auditoria concluída: '+result['summary'])
        if not result['integrity_ok']:
            messagebox.showwarning('Backup com problemas',result['summary']+'\nNão inicie uma reinstalação.')
        else:
            messagebox.showinfo('Integridade conferida',
                'Todos os arquivos do manifesto conferem. Ainda é necessário testar a restauração, '
                'validar os cofres de navegador, fazer segunda cópia e conferir boot/EFI.\n'
                'O aplicativo NÃO autoriza a formatação.')

    def export_audit(self):
        if not self.audit_last_report:
            messagebox.showinfo('Auditoria','Execute a conferência de integridade antes de exportar o relatório.')
            return
        target=filedialog.asksaveasfilename(title='Salvar auditoria em unidade preservada',
                  initialfile='AUDITORIA-BACKUP-v0510.json', defaultextension='.json',
                  filetypes=[('Relatório JSON','*.json')])
        if not target:return
        try:
            atomic_json(target,self.audit_last_report)
            messagebox.showinfo('Relatório salvo', 'Auditoria salva em:\n'+target+'\n\n'
                'O resultado não é uma autorização para excluir partições.')
        except (OSError,ValueError) as e:
            messagebox.showerror('Salvar auditoria',str(e))

    def _audit_error(self, error):
        self.audit_cancel.configure(state='disabled')
        self.status.set('Auditoria falhou: '+error)
        self._write_text(self.recovery_text,'Auditoria não concluída. Nenhuma autorização para formatar.\n'+error)
        messagebox.showerror('Auditoria interrompida',error)

    def make_recovery_kit(self):
        dest=filedialog.asksaveasfilename(title='Salvar plano em unidade que permanecerá intacta na reinstalação',
              initialdir=self.dest.get() if Path(self.dest.get()).exists() else None,
              initialfile='PLANO-POS-WINDOWS-v05.json',defaultextension='.json',filetypes=[('Plano de recuperação','*.json')])
        if not dest:return
        fmt={d+':' for d in DISKS if self.format_vars[d].get()}
        if drive_of(dest) in fmt:
            messagebox.showerror('Destino bloqueado','Esse local está planejado para formatação; escolha outra unidade.')
            return
        alerts=self.diagnostic_data['disks']['alerts'] if self.diagnostic_data else ['Diagnóstico físico não executado nesta sessão.']
        try:
            count=create_plan(dest,self.catalog_items,self.catalog_choices,
                              sorted(p for p,c in self.choices.items() if c=='keep'),self.dest.get(),alerts,
                              browsers=sorted(self.browser_keep_paths),browser_vaults=self.browser_vaults)
            self.loaded_recovery_plan=load_plan(dest)
            self.status.set('Plano pós-Windows exportado para: '+dest)
            messagebox.showinfo('Plano criado',f'{count} escolhas registradas em: \n{dest}\n\nEste JSON NÃO contém aplicativos, instaladores nem saves. Guarde também seus backups e a pasta da v0.5.')
        except Exception as exc:messagebox.showerror('Erro',str(exc))

    def read_recovery_kit(self):
        file=filedialog.askopenfilename(title='Abrir plano de recuperação v0.5',filetypes=[('Plano v0.5','*.json')])
        if not file:return
        try:
            plan=load_plan(file)
            self.loaded_recovery_plan=plan
            self._write_text(self.recovery_text,summarize_plan(plan))
            messagebox.showinfo('Plano carregado','Consulte o resumo. A importação NÃO executou instalações nem alterou arquivos.\nNa aba Histórico, escolha o backup e teste a restauração.')
        except Exception as exc:messagebox.showerror('Plano inválido',str(exc))

    def restore_game_from_plan(self):
        """Vincula jogo + saves pelo manifesto. Nunca copia para o caminho original."""
        plan=self.loaded_recovery_plan
        if plan is None:
            messagebox.showinfo('Recuperação','Abra ou exporte um plano de recuperação primeiro.')
            return
        manifest=self.selected_manifest()
        if manifest is None:
            messagebox.showinfo('Recuperação','Na aba Histórico, selecione o backup com os saves e volte aqui.')
            self.tabs.select(self.history)
            return
        games=[i for i in plan.get('items',[]) if i.get('decision')=='keep'
               and i.get('kind')=='game' and i.get('save_paths')]
        if not games:
            messagebox.showwarning('Recuperação','Não há jogos com saves locais identificados no plano.')
            return
        dlg=tk.Toplevel(self);dlg.title('Recuperação de saves por jogo');dlg.configure(bg=BG)
        dlg.geometry('700x420');dlg.transient(self)
        self.label(dlg,'Escolha o jogo. Os arquivos serão copiados somente para uma pasta NOVA de conferência.').pack(fill='x',padx=12,pady=10)
        box=tk.Listbox(dlg,bg=PANEL,fg=TEXT,selectbackground='#235781',font=('Segoe UI',11))
        box.pack(fill='both',expand=True,padx=12,pady=8)
        for i in games:box.insert('end',i.get('name','Jogo'))
        def start():
            if is_process_elevated():
                messagebox.showerror('Restauração bloqueada',str(ElevatedRestoreRefused()),parent=dlg)
                return
            selection=box.curselection()
            if not selection:return
            game=games[selection[0]]
            prefixes=[ntpath.normcase(ntpath.normpath(q)).rstrip('\\')
                      for q in game.get('save_paths',[]) if isinstance(q,str)]
            try:
                files=verified_entries(manifest)
                chosen=[]
                for key,item in files.items():
                    src=ntpath.normcase(ntpath.normpath(str(item.get('source',''))))
                    if any(src==pre or src.startswith(pre+'\\') for pre in prefixes):
                        chosen.append(key)
                if not chosen:
                    raise ValueError('Nenhum arquivo deste jogo foi encontrado no backup selecionado. Escolha outro backup ou confira os caminhos salvos.')
                target=filedialog.askdirectory(parent=dlg,title='Pasta onde criar o teste de restauração (não substitui originais)')
                if not target:return
                if not messagebox.askyesno('Confirmar restauração isolada',
                     f'{game.get("name")} — {len(chosen)} arquivo(s).\n\nCriar uma pasta NOVA e conferir SHA-256 sem substituir originais?',parent=dlg):
                    return
                restored,count=guarded_restore_selected(manifest,chosen,target)
                dlg.destroy()
                messagebox.showinfo('Saves conferidos',f'{count} arquivo(s) de {game.get("name")} restaurados:\n{restored}\n\nNão foram aplicados automaticamente ao jogo.')
            except Exception as exc:
                messagebox.showerror('Restauração não concluída',str(exc),parent=dlg)
        ttk.Button(dlg,text='Recuperar saves em pasta de conferência',command=start).pack(padx=12,pady=12)

    def _migrate_choices_if_needed(self):
        # Copia as preferências da 0.4 UMA VEZ para arquivo separado;
        # jamais modifica a 0.4, sua pasta, nem os backups existentes.
        old=self.local_state.with_name('preferencias-v04.json')
        if self.local_state.exists() or not old.exists():
            return
        try:
            data=json.loads(old.read_text(encoding='utf-8'))
            if isinstance(data,dict):
                self.local_state.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        except (OSError,ValueError):
            pass

    def _error(self,error):
        self.busy=False;self.status.set('Falha: '+error)
        messagebox.showerror('Operação interrompida',error)

    def _choices_doc(self):
        """Estado de escolhas desta janela, como vai para o arquivo (cópia solta)."""
        doc={'choices':self.choices,'format_disks':[d for d in DISKS if self.format_vars[d].get()],
             'destination':self.dest.get(), 'catalog_choices':self.catalog_choices,
             'auto_save_paths':sorted(self.auto_save_paths),
             'approved_catalog_paths':self.approved_catalog_paths,
             'personal_paths':sorted(self.personal_paths),
             'browser_keep_paths':sorted(self.browser_keep_paths),
             'browser_vaults':self.browser_vaults, 'retained_discoveries':self.retained_discoveries,
             'cleanup_candidates':sorted(self.cleanup_candidates),
             'catalog_snapshots':{key:{field: item.get(field) for field in
                 ('kind','name','category','paths','possible_paths','install_location',
                  'registry_id','edition','publisher','version','observed_volumes')}
                 for key, item in self.catalog_items.items()
                 if self.catalog_choices.get(key) in ('keep','skip')}}
        # cópia solta: a base não pode mudar junto com os dicionários da janela
        return json.loads(json.dumps(doc))

    def _save_choices(self):
        """Salva juntando com o que outra janela gravou (FIX-P3-06-09).

        Devolve None quando salvou, ou um aviso curto (sem caminhos) para a
        barra de status quando não salvou ou quando houve conflito em decisões
        do usuário (FIX-P3-06-10). O aviso de "não salvou" fica guardado em
        `_choices_last_warning` para a pergunta ao fechar o app."""
        name=self.local_state.name
        try:
            mine=self._choices_doc()
            base=getattr(self,'_choices_base',None)
            status,_merged,conflicts=choices_store.save_merged(self.local_state, mine, base, lock_timeout=0)
        except OSError:
            warning=f'Não foi possível salvar as escolhas em {name} agora. Elas serão salvas na próxima mudança.'
            status=None
        if status=='ocupado':
            # mantém a base: a próxima gravação leva esta diferença junto
            warning='Escolhas não salvas agora: outra janela está gravando. Serão salvas na próxima mudança.'
        elif status=='ilegivel':
            # o app nunca conserta, apaga, troca ou renomeia esse arquivo sozinho
            # FIX-P3-06-11: 'ilegivel' junta JSON estragado, link simbólico e erro de
            # leitura (arquivo bom preso por antivírus/OneDrive): texto neutro (R-37)
            # FIX-P3-06-12: texto final; a perda das escolhas ao fechar vem primeiro
            warning=('As escolhas desta janela não estão sendo salvas e se perdem ao fechar o app. '
                     f'O arquivo {name} não pôde ser lido agora (pode estar danificado ou em uso) '
                     'e não foi alterado. Tente de novo mais tarde (feche e abra o app); se o aviso '
                     'continuar, peça ajuda ou renomeie esse arquivo para o app criar um novo.')
        if status!='ok':
            self._choices_unsaved=True
            self._choices_last_warning=warning
            return warning
        self._choices_base=mine
        self._choices_unsaved=False
        self._choices_last_warning=None
        decisions=choices_store.decision_conflicts(conflicts)
        if decisions:
            return (f'Escolhas salvas junto com as de outra janela. Em {len(decisions)} item(ns) '
                    'as janelas discordavam: o arquivo guardou a opção mais segura, mas esta '
                    'janela continua com as suas escolhas. Feche e abra o app para ver tudo junto.')
        return None

    def import_previous_choices(self):
        """Import a user's old choices, not backups or destructive disk settings."""
        if self.busy or getattr(self, 'deep_scan_running', False):
            messagebox.showwarning('Aguarde', 'Finalize a operação antes de importar escolhas.')
            return
        source = filedialog.askopenfilename(
            title='Selecione preferencias-v05.json da pasta anterior',
            filetypes=[('Preferências JSON', '*.json')], parent=self)
        if not source:
            return
        try:
            data = json.loads(Path(source).read_text(encoding='utf-8'))
            if not isinstance(data, dict) or not isinstance(data.get('choices'), dict):
                raise ValueError('Este arquivo não contém um plano de escolhas reconhecido.')
        except (OSError, ValueError, UnicodeError) as exc:
            messagebox.showerror('Preferências inválidas', str(exc), parent=self)
            return
        if not messagebox.askyesno('Importar escolhas antigas',
            'Importar as decisões de Manter / Não preservar da versão anterior?\n\n'
            'As escolhas importadas prevalecerão quando houver conflito. '
            'Não serão importadas opções de formatação nem caminhos de destino. '
            'Nenhum arquivo do computador será apagado ou copiado.', parent=self):
            return
        try:
            paths, catalog = merge_preferences(self, data)
            self._rehydrate_selected_catalog()
            self._on_change()
            self._refresh_home_metrics()
            if hasattr(self, 'update_preservation_preview'):
                self.update_preservation_preview()
            messagebox.showinfo('Escolhas importadas',
                f'{paths} caminho(s) e {catalog} jogos/apps marcados para manter '
                'foram importados. Reveja locais e saves pendentes antes da reinstalação.', parent=self)
        except (ValueError, TypeError) as exc:
            messagebox.showerror('Importação interrompida', str(exc), parent=self)

    def _restore_choices(self):
        try:
            data=json.loads(self.local_state.read_text(encoding='utf-8'))
            retained=data.get('retained_discoveries',{})
            self.retained_discoveries={k:v for k,v in retained.items() if isinstance(k,str) and isinstance(v,dict)} if isinstance(retained,dict) else {}
            self.choices={norm(k):v for k,v in data.get('choices',{}).items() if v in ('keep','skip')}
            self.cleanup_candidates = {norm(k) for k in data.get('cleanup_candidates',[]) if isinstance(k,str)}
            self.catalog_choices={str(k):v for k,v in data.get('catalog_choices',{}).items() if v in ('keep','skip','pending')}
            snapshots=data.get('catalog_snapshots',{})
            self.catalog_snapshots={str(k):v for k,v in snapshots.items() if isinstance(v,dict)} if isinstance(snapshots,dict) else {}
            self.auto_save_paths={norm(v) for v in data.get('auto_save_paths',[]) if isinstance(v,str)}
            self.approved_catalog_paths={str(k):[v for v in vals if isinstance(v,str)] for k,vals in data.get('approved_catalog_paths',{}).items() if isinstance(vals,list)}
            self.personal_paths={norm(v) for v in data.get('personal_paths',[]) if isinstance(v,str)}
            if not self.personal_paths:
                self.personal_paths={p for p in self.choices if p not in self.auto_save_paths}
            self.browser_keep_paths={norm(v) for v in data.get('browser_keep_paths',[]) if isinstance(v,str)}
            self.browser_vaults={norm(k):v for k,v in data.get('browser_vaults',{}).items() if isinstance(v,str)}
            self.dest.set(data.get('destination',self.dest.get()))
            for d in DISKS: self.format_vars[d].set(False)  # seleção destrutiva nunca é recuperada automaticamente
        except (OSError,ValueError):pass

    def _quit(self):
        if getattr(self,'deep_scan_running',False):
            messagebox.showwarning('Varredura em andamento','Cancele a busca e aguarde o relatório parcial antes de fechar.');return
        if self.busy:
            messagebox.showwarning('Operação em andamento','Não feche enquanto um backup está em andamento.')
            return
        if self.optimizer_panel.mon_running:
            if not messagebox.askyesno('Sessão em andamento',
                    'Encerrar e salvar a sessão de temperatura antes de fechar o aplicativo?'):
                return
            if not self.optimizer_panel.shutdown_monitor():
                messagebox.showerror('Monitoramento',
                                     'Não foi possível finalizar a sessão com segurança. Tente Parar e salvar sessão.')
                return
        self.optimizer_panel.shutdown_capture()
        self._save_choices()
        if getattr(self,'_choices_unsaved',False):
            warning=(getattr(self,'_choices_last_warning',None)
                     or 'As últimas escolhas não foram salvas.')
            question=(f'{warning}\n\nSe fechar agora, essas últimas escolhas não serão salvas. '
                      'Fechar mesmo assim?')
            if not messagebox.askyesno('Escolhas não salvas', question,
                                       default='no', parent=self):
                return
        self.destroy()


if __name__=='__main__':
    App().mainloop()
