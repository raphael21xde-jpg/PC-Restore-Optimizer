"""Task-oriented Optimization page integrated into PC Restore & Optimizer.

No system mutation happens during construction, scanning or CSV import.
Only the Power tab can request a reversible power-plan change after confirmation.
"""
from __future__ import annotations
import json
import ntpath
import os
from pathlib import Path
import threading
import queue
import time
import re
import subprocess
from datetime import datetime, timezone
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from optimization_engine import (inspect_pc, available_power_plans, active_power_guid,
                                 revert_power_plan, export_snapshot,
                                 OptimizationError, PowerPlanAdapter, create_restore_point,
                                 legacy_power_pending, POWER_KIND, POWER_KEY)
from change_journal import ChangeJournal, JournalError, BatchRefused
from elevation_guard import is_process_elevated
from restore_jobs import Job
from ui_timers import WindowTimers
from hardware_profile import profile_lines, SCAN_CONFIRMATION
from bios_guidance import bios_guidance_lines, bios_steps_text
import security_checkup as checkup_engine
from security_checkup import CHECKUP_CONFIRMATION, IDLE_CONFIRMATION
import pc_measure
from pc_measure import MEASURE_CONFIRMATION
from atomic_write import atomic_write_text
from optimization_bench import parse_csv_file, insert_run, summarize, read_history
from stutter_analysis import analyze_file, correlate_with_session, summary_text, analyze_sampled_fps_session
from stutter_deep import study_csv, study_text
from optimization_monitor import (KEYS, LABELS, read_afterburner_log, find_afterburner_logs,
                                  poll_nvidia, combine, summarized, new_session, append_sample,
                                  finish_session, session_comparison)

# ---------- P3-07 fatia 1: check-up de segurança (só leitura) ----------
CHECKUP_FAILED_TEXT = ('O check-up de segurança não pôde ser concluído. Nada foi mudado, '
                       'encerrado ou tirado do lugar. Tente de novo mais tarde.')
# P3-07 fatia 4: uso de CPU e GPU com o PC parado (botão à parte; o check-up continua rápido).
IDLE_BUTTON_TEXT='Medir uso parado (2 min)'
IDLE_RUNNING_TEXT='Medindo... (2 min)'
IDLE_FAILED_TEXT=('A medição do uso com o PC parado não pôde ser concluída. Nada foi mudado '
                  'nem encerrado. Tente de novo mais tarde.')
# P3-02: medição antes e depois (só leitura, ~1 minuto).
MEASURE_TITLE='Medição antes e depois'
MEASURE_HELP=('Meça ANTES de aplicar os ajustes e DEPOIS deles, com os mesmos programas abertos. '
              'Só lê: nada é mudado.')
MEASURE_BEFORE_TEXT='Medir ANTES (1 min)'
MEASURE_AFTER_TEXT='Medir DEPOIS (1 min)'
MEASURE_RUNNING_TEXT='Medindo... (1 min)'
MEASURE_FAILED_TEXT=('A medição do PC não pôde ser concluída ou guardada. Nada foi mudado no Windows. '
                     'Tente de novo mais tarde.')
MEASURE_HISTORY_UNREADABLE=('Não foi possível ler as medições guardadas. Uma medição nova não '
                            'apaga nada: ela só é guardada quando o arquivo puder ser lido.')

# ---------- P3-03 fatia 2a: textos da troca de plano (sem caminhos, R-07) ----------
POWER_ADMIN_TEXT = (
    'Para trocar o plano de energia, o app cria antes um ponto de restauração do Windows, '
    'e isso só funciona com o app aberto como administrador. O app nunca pede isso sozinho. '
    'Se quiser trocar o plano: feche o app, clique com o botão direito no atalho dele e '
    'escolha "Executar como administrador". Depois, para fazer backup ou restaurar, abra o '
    'app de novo do jeito normal. Desfazer uma troca funciona sem administrador.')
POWER_RESTORE_POINT_HELP = (
    'Possíveis motivos: a Proteção do sistema está desligada no disco do Windows, ou o '
    'Windows já criou um ponto de restauração nas últimas 24 horas (ele não cria outro '
    'antes disso). O app não liga a Proteção do sistema sozinho.')
POWER_LEGACY_TEXT = (
    'Existe uma troca de plano feita por uma versão antiga do app. Por segurança, novas '
    'trocas ficam bloqueadas até ela ser desfeita. Use "Desfazer alteração antiga".')
POWER_LEGACY_PENDING_TEXT = (
    'A troca de plano feita por uma versão antiga do app ficou interrompida, e o app não '
    'sabe com certeza qual plano ficou ativo. Confira o plano de energia nas Configurações '
    'do Windows. Por segurança, o app não troca mais o plano sozinho.')
POWER_LEGACY_UNREADABLE_TEXT = (
    'O registro de uma troca de plano feita por uma versão antiga do app não pôde ser lido. '
    'Confira o plano de energia nas Configurações do Windows. Por segurança, o app não troca '
    'mais o plano sozinho.')
POWER_JOURNAL_OFF_TEXT = 'Por segurança, as trocas de plano e o Desfazer ficam desligados.'
POWER_GENERIC_FAIL = ('O Windows não confirmou a operação. Confira o plano de energia nas '
                      'Configurações do Windows.')
# ---------- P3-03 fatia 2b-1: aba "Alterações feitas" (textos fixos, R-07) ----------
CHANGES_UNKNOWN_TEXT = ('{n} ajuste(s) com estado desconhecido. Confira o plano de energia nas '
                        'Configurações do Windows. Por segurança, novas trocas ficam bloqueadas.')
CHANGES_EMPTY_TEXT = 'Não há alteração aplicada pelo app para desfazer.'
CHANGES_LEGACY_BLOCKED_TEXT = 'Por isso, o bloqueio continua: o app não libera novas trocas sozinho.'
CHANGES_INTRO_TEXT = ('Aqui aparece tudo o que o app mudou no Windows, com o estado de cada '
                      'alteração. Abrir esta aba só lê o diário: nenhum comando é executado.')
CHANGES_ALL_UNDONE_TEXT = 'Todas as {n} alterações foram desfeitas.'
# FIX-P3-03-03 (revisão da PR #131): singular, erro inesperado e onde fica o botão antigo.
# FIX-P3-03-04: o texto do erro inesperado é genérico (vale para qualquer tipo de ajuste).
# FIX-P3-03-05: o texto é completo (a janela não junta POWER_JOURNAL_OFF_TEXT) e aponta a aba 7.
# FIX-P3-03-06: "aplicar e desfazer ajustes" (todos esses botões ficam desligados, R-30).
CHANGES_TAB_LABEL = '7  Alterações feitas'
CHANGES_ONE_UNDONE_TEXT = 'A alteração foi desfeita.'
CHANGES_UNEXPECTED_ERROR_TEXT = (
    'Ocorreu um erro inesperado ao desfazer. Algumas alterações podem já ter sido desfeitas. '
    'O diário e os botões de aplicar e desfazer ajustes ficam desligados até você fechar e abrir '
    'o app de novo. Depois disso, confira na aba "' + CHANGES_TAB_LABEL + '" o que '
    'continua aplicado.')
CHANGES_LEGACY_WHERE_TEXT = 'O botão "Desfazer alteração antiga" fica na aba "4  Energia reversível".'
CHANGES_STOPPED_TEXT = '{done} desfeita(s); {pending} continuam como estavam. Motivo: {reason}'
CHANGES_DONE_BEFORE_ERROR_TEXT = '{n} alteração(ões) já foram desfeitas antes do erro. '
CHANGES_CONFIRM_TEXT = (
    'Desfazer {n} alteração(ões) feitas pelo app?\n\n'
    'O app desfaz da mais nova para a mais antiga; não cria ponto de restauração; '
    'se uma não puder ser desfeita, o app para ali.')
# ---------- P3-03 fatia 2b-2: "Conferir de novo" (textos fixos, R-07) ----------
CHANGES_RECHECK_TITLE = 'Conferir de novo'
CHANGES_RECHECK_RUNNING_TEXT = 'Conferindo o valor atual de cada alteração (somente leitura)…'
CHANGES_RECHECK_NOTHING_TEXT = 'Não há alteração aplicada ou sem confirmação para conferir.'
CHANGES_RECHECK_FIXED_TEXT = ('Conferência concluída: {n} alteração(ões) tiveram o estado acertado '
                              'no diário. Nada foi mudado no Windows.')
CHANGES_RECHECK_SAME_TEXT = ('Conferência concluída: o diário já estava certo. '
                             'Nada foi mudado no Windows.')
# FIX-P3-03-09 (R-33): frase neutra quando algum item ficou ilegível ou foi mudado por fora.
CHANGES_RECHECK_NONE_CHANGED_TEXT = ('Conferência concluída: nenhum estado precisou mudar. '
                                     'Nada foi mudado no Windows.')
CHANGES_RECHECK_OUTSIDE_TEXT = (' {n} ajuste(s) foram mudados por outro programa; '
                                'o app não vai sobrescrever.')
CHANGES_RECHECK_UNREADABLE_TEXT = (' Não foi possível ler o valor atual de {n} ajuste(s); '
                                   'eles continuam como estavam.')
CHANGES_RECHECK_ERROR_TEXT = (
    'Ocorreu um erro inesperado ao conferir. Nada foi mudado no Windows. '
    'O diário e os botões de aplicar e desfazer ajustes ficam desligados até você fechar e abrir '
    'o app de novo.')
_NOTHING_SAVED = ' Nada foi gravado.'
_LEGACY_KNOWN_MESSAGES = {
    'Nenhuma alteração anterior registrada neste aplicativo.',
    'Registro de reversão está ilegível.',
    'Não há ajuste aplicado para reverter.',
    'Plano original não existe mais. Nenhuma alteração feita.',
    'O plano foi alterado por outro programa. Não sobrescrevi a escolha atual.',
    'Windows não confirmou a reversão. Verifique o plano ativo.',
}

BG='#0C1220'; PANEL='#192438'; TEXT='#EFF4FF'; MUTED='#9CAAC0'; ACCENT='#9C85FF';
GREEN='#5DDEB1'; AMBER='#F3BE67'; BORDER='#2B3952'


def _error_text(exc):
    """FIX-P3-06-08: texto de erro para a tela, sem caminhos pessoais.

    OSError vira "nome-do-arquivo: TipoDoErro" (só o nome, nunca a pasta, que
    pode ter o nome do usuário); ValueError é texto escrito pelo próprio app e
    aparece inteiro; qualquer outro erro mostra só o tipo.
    """
    if isinstance(exc, OSError):
        name = ntpath.basename(str(exc.filename)) if exc.filename else ''
        return (name or 'arquivo') + ': ' + type(exc).__name__
    if isinstance(exc, ValueError):
        return str(exc)
    return type(exc).__name__


def looks_like_presentmon_installer(path):
    """Recognize known PresentMon installer naming, not arbitrary executables."""
    filename=Path(path).name.lower()
    if 'presentmon' not in filename:
        return False
    if any(token in filename for token in ('setup', 'installer', 'install-', '-install')):
        return True
    return bool(re.fullmatch(r'presentmon[-_ ]v?\d+(?:\.\d+){1,3}\.exe',filename))


def presentmon_capture_explanation(exit_code, diagnostic, csv_found=False):
    """Turn an actual CLI log into a bounded, user-facing failure hint."""
    details=' '.join((diagnostic or '').split())
    low=details.lower()
    if 'access denied' in low or '0x80070005' in low or 'acesso negado' in low:
        hint='A captura ETW parece ter sido negada por permissão. Verifique os privilégios exigidos pelo PresentMon; não altere políticas do Windows automaticamente.'
    elif 'unknown option' in low or 'unrecognized' in low or 'invalid argument' in low or 'unknown argument' in low:
        hint='O executável não reconheceu um dos argumentos; pode não ser a CLI correta ou ter outra versão.'
    elif 'already running' in low or 'already exists' in low or 'session already' in low:
        hint='Já pode existir outra sessão de captura PresentMon ativa; encerre-a antes de repetir o teste.'
    elif 'no matching' in low or 'process not found' in low:
        hint='Confira o nome do processo e deixe o CS2 aberto antes de iniciar a captura.'
    elif exit_code == 6:
        hint=('Código 6: não foi possível iniciar a sessão de eventos (ETW) do PresentMon. '
              'As possibilidades incluem conflito com outra sessão e falta de permissão. '
              'O PC Restore usa agora um nome exclusivo de sessão para evitar conflitos. '
              'Se persistir, verifique as permissões de captura do PresentMon.')
    elif exit_code is not None and exit_code != 0:
        hint=f'O executável encerrou com código {exit_code}. Consulte a mensagem original abaixo.'
    elif not csv_found:
        hint='Nenhum CSV válido foi criado. Confirme que selecionou a CLI x64 oficial e que cs2.exe estava aberto.'
    else:
        hint='Arquivo de captura encontrado.'
    return hint+(('\nÚltimas mensagens da CLI: '+details[-700:]) if details else '')



def build_presentmon_args(executable, process, output_file, seconds, session_name):
    """Use ETW session unique to this capture; do not terminate other sessions."""
    if not re.fullmatch(r'PCRO_[a-f0-9]{12}', session_name):
        raise ValueError('Nome de sessão de captura inválido.')
    return [str(executable), '--process_name', process,
            '--output_file', str(output_file), '--session_name', session_name,
            '--timed', str(seconds), '--terminate_after_timed']


class OptimizationPanel(tk.Frame):
    def __init__(self, master, app_dir, *, state_dir=None, power_adapter=None,
                 restore_point=None, elevated_probe=None, ask=None, show=None):
        super().__init__(master, bg=BG)
        self.app_dir=Path(app_dir)
        if state_dir is not None:
            self.state_dir = Path(state_dir)
        else:
            self.state_dir = (Path(os.environ['LOCALAPPDATA']) / 'PC-Restore-Optimizer'
                              if os.name == 'nt' and os.environ.get('LOCALAPPDATA')
                              else self.app_dir)
        self.power_journal=self.state_dir/'otimizacao-energia-reversao.json'
        # P3-03 fatia 2a: toda troca de plano passa pelo diário de alterações.
        self.change_journal_path=self.state_dir/'otimizacao-diario.json'
        self.power_adapter=power_adapter or PowerPlanAdapter()
        self._restore_point=restore_point or create_restore_point
        self._elevated_probe=elevated_probe
        self._ask=ask or (lambda title, text: messagebox.askyesno(title, text))
        self._show=show or self._messagebox
        self._timers=WindowTimers(self)
        self.power_busy=False
        self._power_job=None
        self.journal=None
        self.journal_error=''
        # FIX-P3-03-06: frase de "desligado" que acompanha journal_error (None: o erro já diz).
        self.journal_off_text=POWER_JOURNAL_OFF_TEXT
        self.legacy_state='none'
        self._load_change_journal()
        self.bench_journal=self.state_dir/'otimizacao-benchmarks.json'
        self.monitor_dir=self.state_dir/'sessoes-monitoramento'
        self.afterburner_config=self.state_dir/'afterburner-fonte.json'
        self.afterburner_path=tk.StringVar(value='')
        self.presentmon_exe=tk.StringVar(value='')
        self.capture_process=tk.StringVar(value='cs2.exe')
        self.capture_seconds=tk.StringVar(value='90')
        self.capture_status=tk.StringVar(value='Pronto. Nenhuma captura automática em execução.')
        self.capture_proc=None
        self.capture_output=None
        self.capture_anchor=None
        self.capture_requested_stop=False
        self.capture_log_path=None
        self.capture_last_diagnostic=''
        self.stutter_last=None
        self.stutter_source=None
        self.monitor_status=tk.StringVar(value='Pronto para iniciar; nenhuma medição ativa.')
        self.mon_running=False
        self.mon_session=None
        self.mon_stop=threading.Event()
        self.mon_thread=None
        self.mon_updates=queue.Queue()
        self.mon_last={}
        self.mon_recent=[]
        self.mon_error=''
        self._load_monitor_source()
        self.report=None
        self.plans=[]
        self.running=False
        # P3-07: consulta do check-up em andamento (Job) e janela aberta.
        self._checkup_job=None
        self._checkup_window=None
        # P3-07 fatia 4: medição do uso parado (Job) e os últimos resultados mostrados juntos.
        self._idle_job=None
        self._idle_result=None
        self._checkup_result=None
        # P3-02: medição antes e depois (Job) e o arquivo com as medições.
        self._measure_job=None
        self.measure_path=self.state_dir/pc_measure.MEASURE_FILE
        self.scenario=tk.StringVar(value='Counter-Strike 2 | mesmo mapa, resolução e ajustes')
        self.phase=tk.StringVar(value='antes')
        self.plan_choice=tk.StringVar(value='')
        self.note=tk.StringVar(value='Nenhuma alteração aplicada. Faça primeiro o diagnóstico.')
        self._build()

    def _label(self, parent, content, size=10, fg=TEXT, bold=False, wrap=None):
        kwargs={'wraplength':wrap} if wrap else {}
        return tk.Label(parent,text=content,bg=BG,fg=fg,justify='left',anchor='w',
                        font=('Segoe UI',size,'bold' if bold else 'normal'), **kwargs)

    def _paragraph(self, parent, title, detail):
        box=tk.Frame(parent,bg=PANEL,highlightbackground=BORDER,highlightthickness=1)
        box.pack(fill='x',pady=(0,10))
        tk.Label(box,text=title,bg=PANEL,fg=TEXT,font=('Segoe UI',11,'bold'),anchor='w').pack(fill='x',padx=16,pady=(13,5))
        tk.Label(box,text=detail,bg=PANEL,fg=MUTED,font=('Segoe UI',10),justify='left',wraplength=830,
                 anchor='w').pack(fill='x',padx=16,pady=(0,14))
        return box

    def _text_area(self, parent):
        holder=tk.Frame(parent,bg=PANEL)
        holder.pack(fill='both',expand=True,pady=(8,0))
        txt=tk.Text(holder,bg=PANEL,fg=TEXT,insertbackground=TEXT,relief='flat',bd=0,
                    wrap='word',font=('Consolas',10),padx=16,pady=13,height=14)
        scroll=ttk.Scrollbar(holder,orient='vertical',command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');txt.pack(side='left',fill='both',expand=True)
        return txt

    @staticmethod
    def _write(widget, text):
        widget.configure(state='normal')
        widget.delete('1.0','end')
        widget.insert('1.0',text)
        widget.configure(state='disabled')

    def _build(self):
        outer=tk.Frame(self,bg=BG)
        outer.pack(fill='both',expand=True,padx=(15,5),pady=(3,5))
        header=tk.Frame(outer,bg=BG)
        header.pack(fill='x',pady=(0,10))
        tk.Label(header,text='OTIMIZAÇÃO CONSCIENTE',bg=BG,fg=ACCENT,
                 font=('Segoe UI',12,'bold')).pack(anchor='w')
        tk.Label(header,text='Diagnostique • compare • aplique somente ajustes compatíveis • reverta',
                 bg=BG,fg=MUTED,font=('Segoe UI',10)).pack(anchor='w',pady=(4,0))
        self.tabs=ttk.Notebook(outer)
        self.tabs.pack(fill='both',expand=True)
        diagnose=ttk.Frame(self.tabs)
        monitor=ttk.Frame(self.tabs)
        power=ttk.Frame(self.tabs)
        compare=ttk.Frame(self.tabs)
        firmware=ttk.Frame(self.tabs)
        stutters=ttk.Frame(self.tabs)
        changes=ttk.Frame(self.tabs)
        for frame,name in ((diagnose,'1  Diagnóstico'),(monitor,'2  Temperaturas e sessões'),
                           (stutters,'3  Stutters / quadros'),(power,'4  Energia reversível'),
                           (compare,'5  Benchmarks'),(firmware,'6  BIOS e drivers'),
                           (changes,CHANGES_TAB_LABEL)):
            self.tabs.add(frame,text=name)
        self._build_diagnostics(diagnose)
        self._build_monitor(monitor)
        self._build_stutters(stutters)
        self._build_power(power)
        self._build_benchmarks(compare)
        self._build_firmware(firmware)
        self._build_changes(changes)
        tk.Label(outer,textvariable=self.note,bg=BG,fg=GREEN,anchor='w',
                 wraplength=900,justify='left',font=('Segoe UI',9)).pack(fill='x',pady=(10,1))

    def _build_diagnostics(self, parent):
        area=tk.Frame(parent,bg=BG);area.pack(fill='both',expand=True,padx=12,pady=11)
        self._paragraph(area,'Etapa 1: conhecer o seu computador',
                        'Consulta somente leitura: Windows, CPU, GPU e driver, RAM, discos, gabinete e bateria, placa-mãe, versão da BIOS e planos de energia, e inclui um perfil do PC. '
                        'Temperaturas e utilização são medidas na próxima aba, usando sensores disponíveis; não confirma XMP/EXPO ativo.')
        actions=tk.Frame(area,bg=BG);actions.pack(fill='x',pady=(3,5))
        self.btn_scan=ttk.Button(actions,text='Analisar este PC',style='Primary.TButton',command=self.scan)
        self.btn_scan.pack(side='left',padx=(0,9))
        ttk.Button(actions,text='Exportar diagnóstico JSON',command=self.export_report).pack(side='left')
        # P3-06 fatia 2: só abre uma janela de leitura; liga depois do primeiro diagnóstico.
        self.btn_bios_steps=ttk.Button(actions,text='Ver passo a passo',command=self.show_bios_steps)
        self.btn_bios_steps.pack(side='left',padx=(9,0))
        self.btn_bios_steps.configure(state='disabled')
        # P3-07 fatia 1: check-up só de leitura (inicialização e processos), em janela própria.
        self.btn_checkup=ttk.Button(actions,text='Check-up de segurança',command=self.security_checkup)
        self.btn_checkup.pack(side='left',padx=(9,0))
        # P3-07 fatia 4: mede 2 minutos (só leitura), em botão à parte.
        self.btn_idle=ttk.Button(actions,text=IDLE_BUTTON_TEXT,command=self.measure_idle)
        self.btn_idle.pack(side='left',padx=(9,0))
        # P3-02: medição antes e depois (só leitura), com a comparação logo abaixo.
        box=tk.Frame(area,bg=PANEL,highlightbackground=BORDER,highlightthickness=1)
        box.pack(fill='x',pady=(6,0))
        tk.Label(box,text=MEASURE_TITLE,bg=PANEL,fg=TEXT,font=('Segoe UI',11,'bold'),
                 anchor='w').pack(fill='x',padx=16,pady=(10,3))
        tk.Label(box,text=MEASURE_HELP,bg=PANEL,fg=MUTED,font=('Segoe UI',10),justify='left',
                 wraplength=830,anchor='w').pack(fill='x',padx=16)
        measure_row=tk.Frame(box,bg=PANEL);measure_row.pack(fill='x',padx=16,pady=(6,4))
        self.btn_measure_before=ttk.Button(measure_row,text=MEASURE_BEFORE_TEXT,
                                           command=lambda:self.measure_pc('antes'))
        self.btn_measure_before.pack(side='left')
        self.btn_measure_after=ttk.Button(measure_row,text=MEASURE_AFTER_TEXT,
                                          command=lambda:self.measure_pc('depois'))
        self.btn_measure_after.pack(side='left',padx=(9,0))
        self.measure_text=tk.Text(box,bg=PANEL,fg=TEXT,relief='flat',bd=0,wrap='word',
                                  font=('Consolas',10),padx=16,pady=6,height=9)
        self.measure_text.pack(fill='x',padx=(0,4),pady=(0,8))
        self._render_measures()
        self.report_text=self._text_area(area)
        self._write(self.report_text,'Nenhuma análise executada. Clique em “Analisar este PC”.\n\n'
                    'Princípio do estudo Honest: avaliar Windows, GPU, firmware e resultados com benchmarks.\n'
                    'Modo seguro: nenhuma mudança é feita pela análise.')

    def _build_monitor(self,parent):
        area=tk.Frame(parent,bg=BG);area.pack(fill='both',expand=True,padx=12,pady=8)
        self._paragraph(area,'Monitoramento real: leituras do MSI Afterburner + driver NVIDIA',
                        'O app acompanha o histórico .hml gerado pelo Afterburner e consulta a GPU NVIDIA diretamente. '
                        'Se algum sensor, como a temperatura da CPU, não estiver disponível, aparecerá — (não disponível). '
                        'A captura é periódica: FPS/frametime amostrados NÃO geram 1% low por quadro.')
        scenario_row=tk.Frame(area,bg=BG);scenario_row.pack(fill='x',pady=(0,5))
        self._label(scenario_row,'Cenário:').pack(side='left',padx=(0,6))
        ttk.Entry(scenario_row,textvariable=self.scenario).pack(side='left',fill='x',expand=True,padx=(0,8))
        for phase in ('antes','depois'):
            ttk.Radiobutton(scenario_row,text=phase.upper(),value=phase,variable=self.phase).pack(side='left',padx=(0,7))
        row=tk.Frame(area,bg=BG);row.pack(fill='x',pady=(0,5))
        self._label(row,'Log Afterburner:').pack(side='left',padx=(0,7))
        ttk.Entry(row,textvariable=self.afterburner_path).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Localizar',command=self.find_monitor_source).pack(side='left',padx=(8,0))
        ttk.Button(row,text='Escolher .hml',command=self.select_monitor_source).pack(side='left',padx=(7,0))
        details=tk.Frame(area,bg=BG);details.pack(fill='x',pady=(1,4))
        self._label(details,'Afterburner → Configurações → Monitoramento → “Registrar histórico em arquivo”. '
                    'Habilite CPU/GPU temperatura, uso e FPS se disponíveis. Deixe o Afterburner aberto.',
                    size=9,fg=MUTED,wrap=850).pack(anchor='w')
        actions=tk.Frame(area,bg=BG);actions.pack(fill='x',pady=(5,7))
        self.btn_mon_start=ttk.Button(actions,text='▶ Iniciar medição',style='Primary.TButton',command=self.start_monitor)
        self.btn_mon_start.pack(side='left',padx=(0,8))
        self.btn_mon_stop=ttk.Button(actions,text='■ Parar e salvar sessão',command=self.stop_monitor)
        self.btn_mon_stop.pack(side='left',padx=(0,8))
        self.btn_mon_stop.configure(state='disabled')
        ttk.Button(actions,text='Comparar sessões',command=self.compare_monitor).pack(side='left',padx=(0,8))
        ttk.Button(actions,text='Abrir relatórios',command=self.open_monitor_folder).pack(side='left')
        tk.Label(area,textvariable=self.monitor_status,bg=BG,fg=AMBER,font=('Segoe UI',9),
                 anchor='w',justify='left',wraplength=950).pack(fill='x',pady=(2,7))
        # Periodic time-series diagram (not a synthetic benchmark).
        self.monitor_graph=tk.Canvas(area,bg=PANEL,height=125,highlightthickness=1,
                                     highlightbackground=BORDER)
        self.monitor_graph.pack(fill='x',pady=(0,5))
        self.monitor_graph.bind('<Configure>',lambda event:self._draw_monitor_graph())
        self.monitor_text=self._text_area(area)
        self._write(self.monitor_text,'Ainda não há medições. Inicie uma sessão para registrar temperatura e uso.\n'
                    'O app NÃO altera clocks, voltagens, ventiladores, drivers nem arquivos de jogo.')

    def _load_monitor_source(self):
        try:
            value=json.loads(self.afterburner_config.read_text(encoding='utf-8'))
            if isinstance(value.get('hml'),str) and len(value['hml'])<1000:
                self.afterburner_path.set(value['hml'])
        except (OSError,ValueError,TypeError):
            pass

    def _save_monitor_source(self):
        self.state_dir.mkdir(parents=True,exist_ok=True)
        src=self.afterburner_path.get().strip()
        if not src:
            return
        # FIX-P3-06-07: temporário de nome único, apagado se a gravação falhar.
        atomic_write_text(self.afterburner_config, json.dumps({'hml':src},ensure_ascii=False))

    def find_monitor_source(self):
        found=find_afterburner_logs()
        if not found:
            messagebox.showinfo('MSI Afterburner','Não encontrei histórico .hml nos locais padrão.\n'
                'No Afterburner, vá a Configurações → Monitoramento → Registrar histórico em arquivo; '
                'depois use Escolher .hml.')
            return
        self.afterburner_path.set(str(found[0]))
        self._save_monitor_source()
        self.monitor_status.set(f'Histórico encontrado: {found[0].name}. Verifique se é o arquivo que está sendo atualizado.')

    def select_monitor_source(self):
        selected=filedialog.askopenfilename(title='Escolha o log do MSI Afterburner',
                    filetypes=[('Histórico Afterburner','*.hml'),('Outros arquivos de log','*.txt *.csv')])
        if selected:
            self.afterburner_path.set(selected)
            self._save_monitor_source()
            self.monitor_status.set('Fonte selecionada. Inicie medição e veja se aparecem amostras de CPU e GPU.')

    def start_monitor(self):
        if self.mon_running:
            return
        scenario=' '.join(self.scenario.get().split())
        try:
            session=new_session(scenario,self.phase.get())
        except ValueError as exc:
            messagebox.showwarning('Monitoramento',str(exc));return
        path=self.afterburner_path.get().strip()
        if path and not Path(path).is_file():
            messagebox.showwarning('Afterburner','O caminho .hml selecionado não existe. Selecione um válido ou limpe o campo.')
            return
        self._save_monitor_source()
        self.mon_session=session
        self.mon_running=True
        self.mon_recent=[];self.mon_last={}
        self.mon_stop.clear()
        self.mon_error=''
        self.btn_mon_start.configure(state='disabled')
        self.btn_mon_stop.configure(state='normal')
        self.monitor_status.set('Monitorando... abra seu jogo. Os dados são registrados somente no seu PC.')
        self.mon_thread=threading.Thread(target=self._monitor_worker,args=(path,),daemon=True)
        self.mon_thread.start()
        self.after(250,self._drain_monitor)

    def _monitor_worker(self,path):
        token=None
        stale=0
        while not self.mon_stop.is_set():
            readings={};source=[];messages=[]
            if path:
                try:
                    data,current=read_afterburner_log(path)
                    if time.time()-Path(path).stat().st_mtime > 12:
                        messages.append('Afterburner não atualiza o log há mais de 12 segundos. Ative o registro.')
                        data={}
                        token=current
                    elif current != token:
                        token=current
                        readings.update(data)
                        if data:source.append('Afterburner')
                        stale=0
                    else:
                        stale+=1
                        if stale>2:messages.append('Afterburner sem novos registros; ative Registrar histórico em arquivo.')
                except (OSError,ValueError) as err:
                    messages.append('Afterburner: '+str(err))
            gpu,err=poll_nvidia()
            if gpu:source.append('NVIDIA')
            if err and not readings:
                messages.append(err)
            merged=combine(gpu,readings)
            if merged and self.mon_session is not None:
                append_sample(self.mon_session,merged,source)
            self.mon_updates.put((merged,messages,source))
            if self.mon_stop.wait(2.0):
                break

    def _drain_monitor(self):
        got=False
        while True:
            try:
                values,messages,sources=self.mon_updates.get_nowait()
            except queue.Empty:
                break
            got=True
            if values:
                self.mon_last=values
                self.mon_recent.append(values)
                self.mon_recent=self.mon_recent[-120:]
            if messages:
                self.mon_error=' | '.join(messages)[:280]
            elif values:
                self.mon_error=''
        if got:
            self._render_monitor()
        if self.mon_running:
            self.after(450,self._drain_monitor)

    def _render_monitor(self):
        rows=self.mon_session['rows'] if self.mon_session else []
        if not rows and not self.mon_error:
            return
        summary=summarized(rows)
        lines=['MONITORAMENTO EM TEMPO REAL — SENSORES PERIÓDICOS',
               f'Sessão: {self.phase.get()} | {self.scenario.get()}',
               f'Amostras registradas: {len(rows)}', '']
        for key in ('cpu_temp_c','gpu_temp_c','cpu_usage_pct','gpu_usage_pct','gpu_power_w','cpu_power_w','vram_used_mb','fps_sampled','frametime_sampled_ms'):
            value=self.mon_last.get(key)
            stats=summary.get(key)
            live='— indisponível' if value is None else f'{value:.1f}'
            extra='' if not stats else f' | média {stats["mean"]:.1f} | pico {stats["max"]:.1f}'
            lines.append(f'{LABELS[key]:<24} {live:>14}{extra}')
        cpu_now=self.mon_last.get('cpu_temp_c')
        if cpu_now is not None and cpu_now>=85:
            lines.extend(['', f'ATENÇÃO TÉRMICA: CPU {cpu_now:.1f} °C. Compare com Tjmax OFICIAL do seu modelo.',
                          'Evite testes pesados contínuos se estiver próximo do limite. Investigue refrigeração.'])
        lines.extend(['','O FPS do Afterburner é AMOSTRADO e não substitui benchmark por quadro.',
                      'Não calcular 1% low, 0,2% low ou frametime real com estas amostras.'])
        if self.mon_error:
            lines.extend(['','FONTE: '+self.mon_error])
        if not self.mon_last.get('cpu_temp_c'):
            lines.append('Para temperatura de CPU, habilite CPU temperature no Afterburner + Log history to file.')
        self._write(self.monitor_text,'\n'.join(lines))
        metrics_text=' • '.join(f'{LABELS[key]} {self.mon_last[key]:.1f}'
                              for key in ('cpu_temp_c','gpu_temp_c','gpu_usage_pct','gpu_power_w','fps_sampled')
                              if key in self.mon_last)
        self.monitor_status.set(f'{len(rows)} amostras • '+
                                (metrics_text or 'Aguardando sensores')+
                                (' | '+self.mon_error if self.mon_error else ''))
        self._draw_monitor_graph()

    def _draw_monitor_graph(self):
        c=self.monitor_graph
        if not c.winfo_exists():return
        c.delete('all')
        w=max(c.winfo_width(),360);h=max(c.winfo_height(),110)
        pad=27
        def yy(temp):return (h-17)-(temp-20)/90*(h-28)
        for yval in (40,60,80,100):
            y=yy(yval)
            c.create_line(pad,y,w-10,y,fill='#314052')
            c.create_text(19,y,text=str(yval),fill=MUTED,font=('Segoe UI',8))
        c.create_text(65,12,text='CPU °C',fill=ACCENT,font=('Segoe UI',9))
        c.create_text(147,12,text='GPU °C',fill=GREEN,font=('Segoe UI',9))
        if not self.mon_recent:
            c.create_text(w/2,h/2,text='Aguardando temperaturas reais dos sensores',fill=MUTED,
                          font=('Segoe UI',11))
            return
        n=len(self.mon_recent)
        for key,color in (('cpu_temp_c',ACCENT),('gpu_temp_c',GREEN)):
            last=None
            for i,row in enumerate(self.mon_recent):
                v=row.get(key)
                if v is None:
                    last=None
                    continue
                x=pad+i/(max(1,n-1))*(w-pad-15)
                y=yy(max(20,min(v,110)))
                if last:c.create_line(last[0],last[1],x,y,fill=color,width=2)
                else:c.create_oval(x-2,y-2,x+2,y+2,fill=color,outline='')
                last=(x,y)

    def stop_monitor(self):
        if not self.mon_running:
            return
        self.mon_running=False
        self.mon_stop.set()
        self.btn_mon_stop.configure(state='disabled')
        self.monitor_status.set('Finalizando e salvando sessão...')
        self.after(150,self._finish_monitor)

    def _finish_monitor(self):
        if self.mon_thread and self.mon_thread.is_alive():
            self.after(150,self._finish_monitor)
            return
        self._drain_monitor()
        self.btn_mon_start.configure(state='normal')
        session=self.mon_session
        self.mon_session=None
        if not session or not session['rows']:
            self.monitor_status.set('Nenhuma amostra capturada. Verifique se NVIDIA/Afterburner estão fornecendo dados.')
            return
        try:
            paths=finish_session(session,self.monitor_dir)
            self.monitor_status.set(f'Sessão salva: {len(session["rows"])} amostras em {paths[0].name} e CSV correspondente.')
            self.note.set('Sessão térmica registrada. Nenhuma otimização foi aplicada.')
        except OSError as exc:
            messagebox.showerror('Salvar monitoramento',f'Não foi possível guardar sessão: {exc}')

    def shutdown_monitor(self):
        """Called when application exits: save an active session before closing."""
        if not self.mon_running:
            return True
        self.mon_running=False
        self.mon_stop.set()
        if self.mon_thread:
            self.mon_thread.join(timeout=6)
            if self.mon_thread.is_alive():
                return False
        session=self.mon_session
        self.mon_session=None
        if session and session['rows']:
            try:
                finish_session(session,self.monitor_dir)
            except OSError:
                return False
        return True

    def compare_monitor(self):
        scenario=' '.join(self.scenario.get().split())
        result=session_comparison(self.monitor_dir,scenario)
        lines=['SESSÕES REGISTRADAS — '+scenario,'',
               f"ANTES: {result['count']['antes']} sessões | DEPOIS: {result['count']['depois']} sessões",'']
        for key in ('cpu_temp_c','gpu_temp_c','gpu_usage_pct','gpu_power_w','fps_sampled'):
            pre=result['median']['antes'].get(key)
            post=result['median']['depois'].get(key)
            change=result['delta_pct'].get(key)
            lines.append(f'{LABELS[key]}: '+
                         ('—' if pre is None else f'{pre:.1f}')+' → '+
                         ('—' if post is None else f'{post:.1f}')+
                         (f' ({change:+.1f}%)' if change is not None else ''))
        lines.extend(['','Recomendado: três sessões por fase, cenário idêntico.',
                      'FPS aqui é amostrado; 1% lows exigem captura por quadro na aba Benchmarks.'])
        self._write(self.monitor_text,'\n'.join(lines))
        self.monitor_status.set('Comparação de sessões exibida.')

    def open_monitor_folder(self):
        self.monitor_dir.mkdir(parents=True,exist_ok=True)
        if os.name=='nt':
            os.startfile(str(self.monitor_dir))
        else:
            messagebox.showinfo('Relatórios',str(self.monitor_dir))

    def _build_stutters(self,parent):
        area=tk.Frame(parent,bg=BG);area.pack(fill='both',expand=True,padx=12,pady=9)
        self._paragraph(area,'Quadros reais, sem FPS inventado',
            'O Intel PresentMon (console oficial, instalado separadamente) pode registrar os quadros do jogo. '
            'Nosso aplicativo analisa o CSV e calcula 1% low, 0,2% low e travadas. '
            'Não injeta código nem modifica CS2, clocks, BIOS, serviços ou drivers.')
        source=tk.Frame(area,bg=BG);source.pack(fill='x',pady=(0,5))
        self._label(source,'PresentMon CLI:').pack(side='left',padx=(0,8))
        ttk.Entry(source,textvariable=self.presentmon_exe).pack(side='left',fill='x',expand=True)
        ttk.Button(source,text='Selecionar .exe',command=self.select_presentmon).pack(side='left',padx=(8,0))
        options=tk.Frame(area,bg=BG);options.pack(fill='x',pady=(2,6))
        self._label(options,'Jogo (.exe):').pack(side='left',padx=(0,6))
        ttk.Entry(options,textvariable=self.capture_process,width=16).pack(side='left',padx=(0,12))
        self._label(options,'Duração (s):').pack(side='left',padx=(0,6))
        ttk.Entry(options,textvariable=self.capture_seconds,width=6).pack(side='left',padx=(0,10))
        self.btn_capture=ttk.Button(options,text='Capturar quadros',style='Primary.TButton',command=self.start_capture)
        self.btn_capture.pack(side='left',padx=(0,8))
        self.btn_capture_stop=ttk.Button(options,text='Parar captura',command=self.stop_capture,state='disabled')
        self.btn_capture_stop.pack(side='left',padx=(0,8))
        ttk.Button(options,text='Analisar CSV existente',command=self.import_stutter_csv).pack(side='left')
        ttk.Button(area,text='Análise aprofundada: microstutters e recorte inicial',
                   command=self.study_current_csv).pack(anchor='w',pady=(0,3))
        tk.Label(area,textvariable=self.capture_status,bg=BG,fg=AMBER,justify='left',anchor='w',
                 wraplength=900,font=('Segoe UI',9)).pack(fill='x',pady=(3,4))
        ttk.Button(area,text='Ver diagnóstico da captura',command=self.show_capture_diagnostic).pack(anchor='w',pady=(0,4))
        ttk.Button(area,text='Analisar uma sessão anterior (.json) - quedas observadas',
                   command=self.import_old_monitor_log).pack(anchor='w',pady=(0,4))
        self._label(area,'Use junto com a medição térmica se quiser relacionar temperatura e quadros. '
                    'Durante a captura, jogue normalmente sem Alt-Tab. O app não cria/baixa a ferramenta PresentMon.',
                    size=9,fg=MUTED,wrap=850).pack(anchor='w',pady=(0,5))
        controls=tk.Frame(area,bg=BG);controls.pack(fill='x',pady=(1,3))
        self.btn_register_frames=ttk.Button(controls,text='Registrar no comparador ANTES/DEPOIS',
                                            command=self.register_stutter_bench,state='disabled')
        self.btn_register_frames.pack(side='left')
        self.stutter_text=self._text_area(area)
        self._write(self.stutter_text,
            'O FPS de 188 para 55.9 no seu log mostrou uma queda real pontual.\n'
            'Agora vamos registrar TODOS os quadros para entender duração, repetição e gravidade.\n\n'
            '1) Selecione uma versão oficial do PresentMon CLI, quando disponível.\n'
            '2) Abra o jogo e clique em Capturar quadros.\n'
            '3) O CSV será analisado ao fim da captura.\n\n'
            'Alternativa: importe CSV por quadro exportado por PresentMon / CapFrameX / OCAT.')

    def select_presentmon(self):
        path=filedialog.askopenfilename(title='PresentMon console CLI oficial (.exe)',
            filetypes=[('Executáveis Windows','*.exe')])
        if path:self.presentmon_exe.set(path)

    def start_capture(self):
        if self.capture_proc is not None:return
        executable=Path(self.presentmon_exe.get().strip())
        if os.name!='nt':
            messagebox.showwarning('Captura','Execução automática de PresentMon disponível apenas no Windows. Importação de CSV funciona aqui.')
            return
        if executable.suffix.lower()!='.exe' or not executable.is_file():
            messagebox.showwarning('PresentMon','Selecione o .exe do PresentMon CLI oficial. Ele não está embutido neste aplicativo.')
            return
        if looks_like_presentmon_installer(executable):
            messagebox.showwarning('PresentMon - instalador selecionado',
                'Este arquivo parece ser o instalador, não a versão CONSOLE.\n\n'
                'Baixe PresentMon-2.6.0-x64.exe em:\n'
                'https://github.com/GameTechDev/PresentMon/releases/tag/v2.6.0\n\n'
                'Selecione esse executável no campo PresentMon CLI.')
            return
        process=self.capture_process.get().strip()
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+\.exe',process):
            messagebox.showwarning('Jogo','Use somente o nome do processo do jogo, como cs2.exe.')
            return
        try:duration=int(self.capture_seconds.get())
        except ValueError:duration=0
        if not 20<=duration<=600:
            messagebox.showwarning('Duração','Escolha entre 20 e 600 segundos.');return
        self.monitor_dir.mkdir(parents=True,exist_ok=True)
        import uuid
        path=self.monitor_dir/f'quadros-{datetime.now().strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:5]}.csv'
        args=build_presentmon_args(executable,process,path,duration,'PCRO_'+uuid.uuid4().hex[:12])
        # Capture console errors instead of discarding stdout/stderr, so an
        # invalid EXE or an ETW permission failure can be diagnosed by the user.
        log_path=path.with_suffix('.presentmon.log')
        self.capture_last_diagnostic=''
        try:
            with log_path.open('wb') as log_file:
                self.capture_proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,
                    stdout=log_file,stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError,ValueError) as exc:
            self.capture_last_diagnostic=f'Falha ao iniciar: {exc}'
            messagebox.showerror('PresentMon',self.capture_last_diagnostic);return
        self.capture_log_path=log_path
        self.capture_output=path
        self.capture_anchor=datetime.now(timezone.utc).isoformat()
        self.capture_requested_stop=False
        self.btn_capture.configure(state='disabled')
        self.btn_capture_stop.configure(state='normal')
        self.capture_status.set(f'Capturando quadros de {process}, até {duration}s. Jogue normalmente.')
        self.after(850,self._check_capture)

    def _check_capture(self):
        proc=self.capture_proc
        if proc is None:return
        code=proc.poll()
        if code is None:
            self.after(850,self._check_capture);return
        self.capture_proc=None
        self.btn_capture.configure(state='normal')
        self.btn_capture_stop.configure(state='disabled')
        csv_path=self.capture_output
        if csv_path and csv_path.is_file() and csv_path.stat().st_size>100:
            self._analyze_stutter_async(csv_path,self.capture_process.get().strip(),self.capture_anchor)
        else:
            tail=''
            if self.capture_log_path and self.capture_log_path.is_file():
                try:
                    # Read only the end of the log: bounded memory consumption.
                    with self.capture_log_path.open('rb') as stream:
                        stream.seek(0,os.SEEK_END)
                        stream.seek(max(0,stream.tell()-8192))
                        tail=stream.read().decode('utf-8',errors='replace')
                except OSError as exc:
                    tail=f'Não foi possível ler o registro: {exc}'
            self.capture_last_diagnostic=presentmon_capture_explanation(code,tail)
            self.capture_status.set('Captura sem CSV utilizável: '+self.capture_last_diagnostic[:400])

    def show_capture_diagnostic(self):
        detail=self.capture_last_diagnostic or ('Ainda não houve uma falha de captura registrada. '
            'Se você selecionou um arquivo PresentMon-2.6.0.exe sem -x64, provavelmente é o instalador. '
            'Use PresentMon-2.6.0-x64.exe, da página oficial.')
        if self.capture_log_path and self.capture_log_path.is_file():
            detail+='\n\nLog local: '+str(self.capture_log_path)
        messagebox.showinfo('Diagnóstico do PresentMon',detail)

    def stop_capture(self):
        if self.capture_proc is None:return
        self.capture_requested_stop=True
        try:self.capture_proc.terminate()
        except OSError:pass
        self.capture_status.set('Parando captura... o CSV parcial será analisado se tiver quadros suficientes.')

    def shutdown_capture(self):
        """Terminate ONLY child process launched by this app; never touch game."""
        proc=self.capture_proc
        if proc and proc.poll() is None:
            try:proc.terminate();proc.wait(timeout=3)
            except (OSError,subprocess.TimeoutExpired):
                try:proc.kill()
                except OSError:pass
        self.capture_proc=None

    def import_stutter_csv(self):
        path=filedialog.askopenfilename(title='CSV por quadro do PresentMon / CapFrameX / OCAT',
                                        filetypes=[('CSV','*.csv'),('Texto','*.txt')])
        if path:
            self._analyze_stutter_async(Path(path),self.capture_process.get().strip(),None)

    def import_old_monitor_log(self):
        path=filedialog.askopenfilename(title='Uma sessão JSON anterior do PC Restore',
                                        filetypes=[('Sessão JSON','*.json')])
        if not path:return
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8'))
            result=analyze_sampled_fps_session(data)
        except (OSError,ValueError,TypeError) as exc:
            messagebox.showerror('Leitura de sessão',str(exc));return
        lines=['FPS AMOSTRADO — sessão anterior','',
               f"Amostras: {result['samples']} | Mínimo observado: {result['observed_min']} FPS",
               f"Quedas >= 40% entre leituras: {len(result['drops'])}",'']
        for ev in result['drops'][:24]:
            lines.append(f"{ev['timestamp']} | {ev['from_fps']} → {ev['to_fps']} FPS ({ev['drop_pct']}% queda) | "
                         f"CPU {ev['cpu_temp_c']} °C, {ev['cpu_usage_pct']}% | GPU {ev['gpu_temp_c']} °C, {ev['gpu_usage_pct']}%")
        lines.extend(['',result['caution']])
        self._write(self.stutter_text,'\n'.join(lines))
        self.capture_status.set('Sessão anterior analisada; para capturar quadros de verdade, use PresentMon CLI.')

    def _analyze_stutter_async(self,path,process,anchor):
        self.capture_status.set('Analisando intervalos de quadros...')
        def worker():
            try:
                report=analyze_file(path,process)
                if anchor and self.mon_session is not None:
                    report['sensor_matches']=correlate_with_session(report,self.mon_session,anchor)
                else:report['sensor_matches']=[]
                self.after(0,lambda r=report:self._render_stutters(r,path))
            except Exception as exc:
                self.after(0,lambda error=str(exc):self.capture_status.set('Não foi possível analisar: '+error))
        threading.Thread(target=worker,daemon=True).start()

    def _render_stutters(self,report,path):
        self.stutter_last=report
        self.stutter_source=Path(path)
        self.btn_register_frames.configure(state='normal')
        lines=[f'ARQUIVO: {Path(path).name}',f'CENÁRIO: {self.scenario.get()} | FASE: {self.phase.get()}', '',
               summary_text(report)]
        if report.get('sensor_matches'):
            lines.extend(['','SENSORES PRÓXIMOS ÀS MAIORES TRAVADAS (CORRELAÇÃO APROXIMADA):'])
            for row in report['sensor_matches'][:6]:
                m=row['sensor_readings']
                lines.append(f"{row['t_s']}s | {row['frametime_ms']}ms | CPU {m.get('cpu_temp_c','?')}°C / {m.get('cpu_usage_pct','?')}% | GPU {m.get('gpu_temp_c','?')}°C / {m.get('gpu_usage_pct','?')}%")
        else:
            lines.extend(['','Sem sincronização comprovada com sensores (CSV importado isoladamente ou medição não iniciada).'])
        try:
            report['scenario']=self.scenario.get().strip();report['phase']=self.phase.get()
            report['captured_utc']=self.capture_anchor if path==self.capture_output else None
            report_file=Path(path).with_suffix('.stutters.json')
            report_file.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            lines.extend(['',f'Relatório gerado: {report_file.name}'])
        except OSError as exc:
            lines.extend(['',f'Aviso: não foi possível salvar relatório: {exc}'])
        self._write(self.stutter_text,'\n'.join(lines))
        self.capture_status.set(f'Análise pronta: {report["count"]} quadros, {report["event_count"]} candidatos a travada.')
        self.note.set('Stutters analisados; nenhuma configuração do Windows foi alterada.')

    def study_current_csv(self):
        source=self.stutter_source
        if source is None or not source.is_file():
            messagebox.showinfo('Análise aprofundada','Primeiro capture quadros ou importe um CSV válido.')
            return
        self.capture_status.set('Analisando recorte inicial, janelas e microstutters...')
        def worker():
            try:
                study=study_csv(source,self.capture_process.get().strip(),5.0)
                self.after(0,lambda r=study:self._study_ready(r))
            except Exception as exc:
                self.after(0,lambda error=str(exc):self.capture_status.set('Erro na análise: '+error))
        threading.Thread(target=worker,daemon=True).start()

    def _study_ready(self,r):
        self._write(self.stutter_text,study_text(r))
        self.capture_status.set('Comparação da captura inteira com o trecho após os primeiros cinco segundos concluída.')
        self.note.set('O CSV permanece intacto; nenhuma configuração foi alterada.')

    def register_stutter_bench(self):
        result=self.stutter_last
        if not result:return
        scenario=' '.join(self.scenario.get().split())
        phase=self.phase.get()
        if not scenario:
            messagebox.showwarning('Benchmark','Indique o cenário.');return
        if not messagebox.askyesno('Comparar stutters',
             f'Registrar este conjunto de {result["count"]} quadros como {phase.upper()}\n'
             f'Cenário: {scenario}\nFPS médio: {result["avg_fps"]:.1f}, 1% low: {result["low_1"]:.1f}\n\n'
             'Compare depois em Benchmarks; sem mudar configurações?'):
            return
        metrics={'samples':result['count'],'column':result['metadata'].get('column','frametime'),
                 'source':'stutter_analysis_per_frame','avg_fps':result['avg_fps'],
                 'low_1':result['low_1'],'low_02':result['low_02'],
                 'min_fps':round(1000/result['worst_ms'],2),'max_fps':round(1000/result['median_frametime_ms'],2)}
        try:insert_run(self.bench_journal,scenario,phase,metrics)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Comparador','Falha ao registrar: '+_error_text(exc));return
        self.note.set('Benchmark de quadros incluído; confira o comparador de FPS e 1% low.')
        self.capture_status.set('Registrado como '+phase.upper()+' no comparador de benchmarks.')

    def _build_power(self,parent):
        area=tk.Frame(parent,bg=BG);area.pack(fill='both',expand=True,padx=12,pady=11)
        self._paragraph(area,'Etapa 2: escolher um plano de energia do Windows',
                        'Este é o único ajuste de sistema executável desta versão. Escolha um plano já disponível no Windows, '
                        'confirme a alteração e use Desfazer para recuperar o plano original. Alto desempenho pode aumentar calor, '
                        'consumo e ruído; não garante mais FPS. Em notebooks, dê preferência às configurações do fabricante.')
        control=tk.Frame(area,bg=BG);control.pack(fill='x',pady=(7,9))
        self._label(control,'Planos reconhecidos pelo Windows',bold=True).pack(anchor='w',pady=(0,5))
        self.plan_box=ttk.Combobox(control,state='readonly',textvariable=self.plan_choice,width=78)
        self.plan_box.pack(side='left',fill='x',expand=True,padx=(0,8))
        self.btn_refresh=ttk.Button(control,text='Atualizar',command=self.load_plans)
        self.btn_refresh.pack(side='left')
        buttons=tk.Frame(area,bg=BG);buttons.pack(fill='x',pady=(2,8))
        self.btn_apply=ttk.Button(buttons,text='Aplicar plano selecionado',style='Primary.TButton',command=self.apply_plan)
        self.btn_apply.pack(side='left',padx=(0,9))
        self.btn_revert=ttk.Button(buttons,text='Desfazer minha última mudança',command=self.revert_plan)
        self.btn_revert.pack(side='left')
        # Só aparece quando existe uma troca feita por uma versão antiga do app.
        self.btn_legacy=ttk.Button(buttons,text='Desfazer alteração antiga',command=self.undo_legacy_plan)
        self.power_status=tk.StringVar(value='')
        tk.Label(area,textvariable=self.power_status,bg=BG,fg=AMBER,anchor='w',justify='left',
                 wraplength=900,font=('Segoe UI',9)).pack(fill='x',pady=(0,4))
        # FIX-P3-03-03: aviso de bloqueio separado, para não esconder o resultado acima.
        self.power_block=tk.StringVar(value='')
        tk.Label(area,textvariable=self.power_block,bg=BG,fg=AMBER,anchor='w',justify='left',
                 wraplength=900,font=('Segoe UI',9)).pack(fill='x',pady=(0,4))
        self.power_text=self._text_area(area)
        intro=['Nenhum plano consultado. Clique em Atualizar.',
               'Ao aplicar: o app cria antes um ponto de restauração do Windows e anota a troca no diário de alterações.',
               'Se um programa externo mudar o plano depois, o Desfazer não sobrescreve a escolha dele.']
        if self.journal_error:
            intro=[self._journal_error_text()]
        self._write(self.power_text,'\n'.join(intro))
        self._update_power_buttons()

    def _build_changes(self,parent):
        """P3-03 fatia 2b-1: lista do diário e "Desfazer tudo". Montar só lê a memória."""
        area=tk.Frame(parent,bg=BG);area.pack(fill='both',expand=True,padx=12,pady=11)
        self.changes_frame=area
        self._paragraph(area,'Alterações feitas pelo app',CHANGES_INTRO_TEXT)
        buttons=tk.Frame(area,bg=BG);buttons.pack(fill='x',pady=(2,8))
        self.btn_undo_all=ttk.Button(buttons,text='Desfazer tudo',command=self.undo_all_changes)
        self.btn_undo_all.pack(side='left')
        # P3-03 fatia 2b-2: só lê o valor atual de cada item e acerta o diário.
        self.btn_recheck=ttk.Button(buttons,text='Conferir de novo',command=self.recheck_changes)
        self.btn_recheck.pack(side='left',padx=(9,0))
        self.changes_status=tk.StringVar(value='')
        tk.Label(area,textvariable=self.changes_status,bg=BG,fg=AMBER,anchor='w',justify='left',
                 wraplength=900,font=('Segoe UI',9)).pack(fill='x',pady=(0,4))
        self.changes_text=self._text_area(area)
        self._update_power_buttons()

    def _build_benchmarks(self,parent):
        area=tk.Frame(parent,bg=BG);area.pack(fill='both',expand=True,padx=12,pady=11)
        self._paragraph(area,'Etapa 3: medir ganhos reais, sem promessas de FPS',
                        'Importe dados CSV com FPS por quadro ou frametime em ms (por exemplo, de OCAT/CapFrameX). '
                        'Grave 3 execuções ANTES e 3 DEPOIS, mantendo jogo, mapa, resolução, cenário e drivers iguais. '
                        'O app compara medianas. Valores de 1% e 0,2% low são estimados dos percentis por quadro.')
        row=tk.Frame(area,bg=BG);row.pack(fill='x',pady=(0,5))
        self._label(row,'Cenário:').pack(side='left',padx=(0,8))
        ttk.Entry(row,textvariable=self.scenario).pack(side='left',fill='x',expand=True)
        phase_row=tk.Frame(area,bg=BG);phase_row.pack(fill='x',pady=(8,9))
        for name in ('antes','depois'):
            ttk.Radiobutton(phase_row,text=name.upper(),value=name,variable=self.phase).pack(side='left',padx=(0,16))
        ttk.Button(phase_row,text='Importar CSV e registrar execução',style='Primary.TButton',
                   command=self.import_csv).pack(side='left',padx=(0,8))
        ttk.Button(phase_row,text='Atualizar comparação',command=self.refresh_bench).pack(side='left')
        self.bench_text=self._text_area(area)
        self._write(self.bench_text,'Sem benchmarks importados.\n\n'
                    'CSV esperado: coluna FPS / FrameRate ou FrameTime(ms) / MsBetweenPresents.\n'
                    'Captura deve medir quadros individuais; relatórios apenas resumidos não são comparáveis aqui.')

    def _build_firmware(self,parent):
        wrapper=tk.Frame(parent,bg=BG);wrapper.pack(fill='both',expand=True,padx=12,pady=11)
        canvas=tk.Canvas(wrapper,bg=BG,highlightthickness=0)
        bar=ttk.Scrollbar(wrapper,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        content=tk.Frame(canvas,bg=BG)
        win=canvas.create_window((0,0),window=content,anchor='nw')
        content.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(win,width=e.width))
        entries=[
          ('Memória: XMP / EXPO / DOCP', 'O artigo aborda XMP. A ferramenta mostra a velocidade relatada pelo Windows, '
           'mas não lê com segurança o perfil efetivo da BIOS. Só habilitar um perfil compatível, depois de conferir manual '
           'e memória suportadas; teste estabilidade. Não será ativado por software.'),
          ('CPU: SMT, Hyper-Threading e Boost', 'O estudo trata de Hyper-Threading e Turbo Boost. '
           'Desligar SMT pode piorar multitarefa; AMD e Intel têm opções diferentes. Não mudar automaticamente. '
           'Temperatura e estabilidade precisam ser medidas.'),
          ('Placa de vídeo: NVIDIA / AMD / Intel', 'O artigo relata NVAPI e ADL, mas não publica parâmetros completos de '
           'alteração. O programa apenas mostra modelo/driver e orienta a atualizar por canais oficiais e comparar benchmarks.'),
          ('Windows: serviços, Registro e prioridades', 'O estudo cita “lopagelocklimit”, Auto Debloat e FSE, sem receitas '
           'exatas e suficientemente testadas. Não reproduzimos Registro obscuro, priorização agressiva, desativação em massa '
           'de serviços, Windows Update, antivírus nem integridade de memória.'),
          ('Limites da pesquisa', 'Resultados de dois PCs (Ryzen 5 5600X/RTX 2070 SUPER e i5-12500H/RTX 3050). '
           '136% é aumento do FPS máximo do DWM em um cenário, não de FPS nos jogos. O CS2 chegou a +28,4% no FPS médio '
           'do desktop testado. Não são previsões de ganho no seu hardware.'),
          ('Proteção de dados e boot', 'Nesta instalação, G: deve ser preservado e F: contém a partição EFI do Windows. '
           'Esta ferramenta não executa formatação, reparticionamento, alteração de firmware, flash de BIOS ou desativação '
           'de segurança. Faça backups e teste restauração antes de manutenção maior.')]
        for title,detail in entries:
            self._paragraph(content,title,detail)

    def scan(self):
        if self.running:
            return
        if not messagebox.askyesno('Analisar este PC',SCAN_CONFIRMATION):
            self.note.set('Análise cancelada. Nada foi lido nem alterado.')
            return
        self.running=True
        self.btn_scan.configure(state='disabled')
        self.note.set('Analisando componentes do Windows em modo somente leitura...')
        def worker():
            try:
                report=inspect_pc()
                self.after(0,lambda r=report:self._scan_finished(r))
            except Exception as exc:
                self.after(0,lambda e=str(exc):self._scan_failed(e))
        threading.Thread(target=worker,daemon=True).start()

    def _scan_failed(self,error):
        self.running=False;self.btn_scan.configure(state='normal')
        self.note.set('Falha na consulta. Nenhum ajuste executado.')
        messagebox.showerror('Diagnóstico',error)

    def _scan_finished(self,report):
        self.running=False;self.btn_scan.configure(state='normal')
        self.report=report
        hw=report.get('hardware',{})
        lines=['DIAGNÓSTICO WINDOWS — LEITURA','']
        def first(key):
            value=hw.get(key)
            return (value[0] if value else {}) if isinstance(value,list) else (value or {})
        def one(key,col):
            return str(first(key).get(col) or 'não disponível')
        lines.extend(['Windows: '+one('os','Caption')+' | '+one('os','Version'),
                      'CPU: '+one('cpu','Name'),
                      'Placa-mãe: '+one('board','Manufacturer')+' '+one('board','Product'),
                      'Firmware: '+one('bios','SMBIOSBIOSVersion'),
                      'GPU(s):'])
        for gpu in (hw.get('gpu') if isinstance(hw.get('gpu'),list) else ([hw['gpu']] if hw.get('gpu') else [])):
            lines.append('  '+str(gpu.get('Name','?'))+' | driver '+str(gpu.get('DriverVersion','?')))
        lines.append('RAM:')
        for ram in (hw.get('ram') if isinstance(hw.get('ram'),list) else ([hw['ram']] if hw.get('ram') else [])):
            lines.append('  '+str(round((ram.get('Capacity') or 0)/1024**3,1))+' GiB | '+str(ram.get('ConfiguredClockSpeed','?'))+' MT/s (configurado)')
        plans=report.get('power',{})
        lines.extend(['','Plano de energia: '+str(plans.get('active_guid') or 'indisponível'),''])
        lines.extend(profile_lines(report.get('profile') or {}))
        lines.extend(bios_guidance_lines(report.get('bios_guidance') or {}))
        lines.append('OBSERVAÇÕES:')
        lines.extend('  • '+str(p['message']) for p in report.get('checks',[]))
        if report.get('errors'):
            lines.extend(['','CONSULTAS INCOMPLETAS:']+['  • '+e for e in report['errors']])
        lines.extend(['','NÃO MEDIDO: '+', '.join(report.get('unmeasured',[])),
                      '','Nenhuma configuração modificada.'])
        self._write(self.report_text,'\n'.join(lines))
        self.note.set('Diagnóstico concluído. Não foi aplicado qualquer ajuste.')
        self.btn_bios_steps.configure(state='normal')
        self.load_plans()

    def show_bios_steps(self):
        """Janela só de leitura com o passo a passo da BIOS (sem link, sem download, sem timer)."""
        if not self.report:
            return None
        old=getattr(self,'_bios_steps_window',None)
        if old is not None and old.winfo_exists():
            old.destroy()
        window=tk.Toplevel(self)
        window.title('BIOS — passo a passo (só orientação)')
        window.configure(bg=BG)
        holder=tk.Frame(window,bg=PANEL);holder.pack(fill='both',expand=True,padx=12,pady=(12,6))
        txt=tk.Text(holder,bg=PANEL,fg=TEXT,relief='flat',bd=0,wrap='word',
                    font=('Segoe UI',10),padx=14,pady=12,width=80,height=22)
        scroll=ttk.Scrollbar(holder,orient='vertical',command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');txt.pack(side='left',fill='both',expand=True)
        self._write(txt,bios_steps_text(self.report.get('bios_guidance') or {}))
        ttk.Button(window,text='Fechar',command=window.destroy).pack(anchor='e',padx=12,pady=(0,12))
        self._bios_steps_window=window
        return window

    def security_checkup(self):
        """P3-07: pergunta antes; a consulta (só leitura) roda num Job e volta por WindowTimers."""
        if self._any_measure_running():
            return
        if not self._ask('Check-up de segurança',CHECKUP_CONFIRMATION):
            self.note.set('Check-up cancelado. Nada foi lido nem alterado.')
            return
        self.btn_checkup.configure(state='disabled')
        self.btn_idle.configure(state='disabled')
        self._set_measure_buttons('disabled')
        self.note.set('Fazendo o check-up de segurança (só leitura)...')
        job=Job(lambda cancelled,progress:checkup_engine.read_checkup())
        self._checkup_job=job
        def poll():
            outcome=job.poll()
            if outcome is None:
                self._timers.after(80,poll)
                return
            self._checkup_job=None
            kind,value=outcome
            if kind=='done':
                self._checkup_finished(value)
            else:
                self._checkup_failed()
        self._timers.after(10,poll)

    def _checkup_finished(self,result):
        self.btn_checkup.configure(state='normal')
        self.btn_idle.configure(state='normal')
        self._set_measure_buttons('normal')
        self.note.set('Check-up de segurança concluído. Nada foi mudado.')
        # Revisão 2 da PR #197: a hora do check-up aparece quando ele volta na janela.
        self._checkup_result=dict(result,checked_at=time.strftime('%H:%M')) if isinstance(result,dict) else result
        self.show_checkup(self._checkup_result)

    def _checkup_failed(self):
        # R-07: nunca a mensagem original (pode ter caminho com nome de usuário).
        self.btn_checkup.configure(state='normal')
        self.btn_idle.configure(state='normal')
        self._set_measure_buttons('normal')
        self.note.set('O check-up de segurança não pôde ser concluído. Nada foi mudado.')
        self._show('warning','Check-up de segurança',CHECKUP_FAILED_TEXT)

    def show_checkup(self,result):
        """Janela só de leitura com o resultado do check-up (sem botão de mudar nada)."""
        old=getattr(self,'_checkup_window',None)
        if old is not None and old.winfo_exists():
            old.destroy()
        # P3-07 fatia 4: a última medição do uso parado aparece na mesma janela.
        idle=getattr(self,'_idle_result',None)
        if idle is not None and isinstance(result,dict) and 'idle' not in result:
            result=dict(result,idle=idle)
        window=tk.Toplevel(self)
        window.title('Check-up de segurança (só leitura)')
        window.configure(bg=BG)
        holder=tk.Frame(window,bg=PANEL);holder.pack(fill='both',expand=True,padx=12,pady=(12,6))
        txt=tk.Text(holder,bg=PANEL,fg=TEXT,relief='flat',bd=0,wrap='word',
                    font=('Segoe UI',10),padx=14,pady=12,width=90,height=26)
        scroll=ttk.Scrollbar(holder,orient='vertical',command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');txt.pack(side='left',fill='both',expand=True)
        self._write(txt,'\n'.join(checkup_engine.checkup_lines(result)))
        ttk.Button(window,text='Fechar',command=window.destroy).pack(anchor='e',padx=12,pady=(0,12))
        self._checkup_window=window
        return window

    def measure_idle(self):
        """P3-07 fatia 4: pergunta antes; mede 2 minutos (só leitura) num Job, com retorno por WindowTimers."""
        if self._any_measure_running():
            return
        if not self._ask('Medir uso parado',IDLE_CONFIRMATION):
            self.note.set('Medição cancelada. Nada foi lido nem alterado.')
            return
        # O check-up também usa o processador: fica desligado enquanto mede.
        self.btn_idle.configure(state='disabled',text=IDLE_RUNNING_TEXT)
        self.btn_checkup.configure(state='disabled')
        self._set_measure_buttons('disabled')
        self.note.set('Medindo o uso com o PC parado por 2 minutos (só leitura). Não use o PC nesse tempo.')
        job=Job(lambda cancelled,progress:checkup_engine.read_idle())
        self._idle_job=job
        def poll():
            outcome=job.poll()
            if outcome is None:
                self._timers.after(200,poll)
                return
            self._idle_job=None
            kind,value=outcome
            if kind=='done':
                self._idle_finished(value)
            else:
                self._idle_failed()
        self._timers.after(10,poll)

    def _idle_done(self):
        self.btn_idle.configure(state='normal',text=IDLE_BUTTON_TEXT)
        self.btn_checkup.configure(state='normal')
        self._set_measure_buttons('normal')

    def _idle_finished(self,idle):
        self._idle_done()
        # Revisão da PR #197: a hora da medição aparece quando ela é mostrada de novo.
        self._idle_result=dict(idle,measured_at=time.strftime('%H:%M')) if isinstance(idle,dict) else idle
        self.note.set('Medição do uso com o PC parado concluída. Nada foi mudado.')
        self.show_checkup(self._checkup_result if self._checkup_result is not None else {})

    def _idle_failed(self):
        # R-07: nunca a mensagem original (pode ter caminho com nome de usuário).
        self._idle_done()
        self.note.set('A medição do uso parado não pôde ser concluída. Nada foi mudado.')
        self._show('warning','Medir uso parado',IDLE_FAILED_TEXT)

    def _any_measure_running(self):
        # Check-up, uso parado e medição antes/depois usam o processador: um de cada vez.
        return any(getattr(self,name,None) is not None for name in ('_checkup_job','_idle_job','_measure_job'))

    def _set_measure_buttons(self,state):
        for name in ('btn_measure_before','btn_measure_after'):
            button=getattr(self,name,None)
            if button is not None:
                button.configure(state=state)

    def _render_measures(self):
        try:
            history=pc_measure.read_measures(self.measure_path)
        except ValueError:
            self._write(self.measure_text,MEASURE_HISTORY_UNREADABLE+'\n\n'+pc_measure.MEASURE_WARNING)
            return
        self._write(self.measure_text,'\n'.join(pc_measure.compare_measures(history)))

    def measure_pc(self,phase):
        """P3-02: pergunta antes; mede ~1 minuto (só leitura) num Job e guarda; retorno por WindowTimers."""
        if phase not in pc_measure.PHASES or self._any_measure_running():
            return
        if not self._ask(MEASURE_TITLE,MEASURE_CONFIRMATION):
            self.note.set('Medição cancelada. Nada foi lido nem alterado.')
            return
        self._set_measure_buttons('disabled')
        (self.btn_measure_before if phase=='antes' else self.btn_measure_after).configure(text=MEASURE_RUNNING_TEXT)
        self.btn_checkup.configure(state='disabled')
        self.btn_idle.configure(state='disabled')
        self.note.set('Medindo o PC por cerca de 1 minuto (só leitura). Não use o PC nesse tempo.')
        path=self.measure_path
        def work(cancelled,progress):
            measure=pc_measure.read_measure()
            path.parent.mkdir(parents=True,exist_ok=True)
            return pc_measure.save_measure(path,phase,measure)
        job=Job(work)
        self._measure_job=job
        def poll():
            outcome=job.poll()
            if outcome is None:
                self._timers.after(200,poll)
                return
            self._measure_job=None
            kind,_value=outcome
            self._measure_done()
            if kind=='done':
                self.note.set('Medição '+phase.upper()+' concluída e guardada. Nada foi mudado.')
                self._render_measures()
            else:
                # R-07: nunca a mensagem original (pode ter caminho com nome de usuário).
                self.note.set('A medição do PC não pôde ser concluída. Nada foi mudado.')
                self._show('warning',MEASURE_TITLE,MEASURE_FAILED_TEXT)
        self._timers.after(10,poll)

    def _measure_done(self):
        self._set_measure_buttons('normal')
        self.btn_measure_before.configure(text=MEASURE_BEFORE_TEXT)
        self.btn_measure_after.configure(text=MEASURE_AFTER_TEXT)
        self.btn_checkup.configure(state='normal')
        self.btn_idle.configure(state='normal')

    def export_report(self):
        if not self.report:
            messagebox.showinfo('Diagnóstico','Clique primeiro em Analisar este PC.')
            return
        target=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('Relatório JSON','*.json')],
                                          title='Exportar inventário (revise informações pessoais antes de compartilhar)')
        if target:
            try:
                export_snapshot(self.report,Path(target))
                self.note.set('Relatório de somente leitura exportado.')
            except Exception as exc:
                messagebox.showerror('Exportação',str(exc))

    def load_plans(self):
        """Lê os planos numa thread (R-10): o powercfg nunca roda na thread da tela."""
        if self.power_busy:
            return
        self.note.set('Consultando planos de energia (somente leitura)...')
        self._run_power_job(self._read_plans_work,self._plans_loaded)

    def _plans_loaded(self,outcome):
        plans=outcome.get('plans')
        if plans is None:
            # R-07: nunca a mensagem crua do Windows (pode ter nome de usuário).
            # A lista anterior (self.plans) fica como estava.
            self._write(self.power_text,'Não foi possível ler os planos de energia do Windows. Nada foi alterado.')
            self.note.set('Não foi possível ler os planos de energia. Nada foi alterado.')
            return
        self._render_plans(plans,outcome.get('active'),
                           ['','Antes de alterar:',' • Compare temperaturas e comportamento com sua rotina.',
                            ' • Planos da fabricante podem ser necessários para notebooks.',
                            ' • Não há promessa de aumento de FPS.',' • Alterações externas bloqueiam reversão automática.'])
        self.note.set('Planos de energia consultados; nada foi alterado.')

    # ---------- P3-03 fatia 2a: troca de plano pelo diário ----------
    @staticmethod
    def _messagebox(kind, title, text):
        {'info':messagebox.showinfo,'warning':messagebox.showwarning,
         'error':messagebox.showerror}.get(kind,messagebox.showinfo)(title,text)

    def _load_change_journal(self):
        """Só lê arquivos: abrir o painel nunca roda comando nenhum."""
        try:
            self.journal=ChangeJournal(self.change_journal_path,{POWER_KIND:self.power_adapter},
                                       self._restore_point)
            self.journal_error=''
        except JournalError as exc:
            self.journal=None
            self.journal_error=str(exc)
        # FIX-P3-03-07: ao (re)carregar, a frase de "desligado" volta ao texto padrão.
        self.journal_off_text=POWER_JOURNAL_OFF_TEXT
        self.legacy_state=legacy_power_pending(self.power_journal)

    def _is_elevated(self):
        return is_process_elevated(self._elevated_probe)

    def _count_status(self,status):
        if self.journal is None or self.journal_error:
            return 0
        return sum(e['status']==status for e in self.journal.entries())

    def _render_changes(self):
        """Só lê a memória (diário já carregado e estado do registro antigo)."""
        if not hasattr(self,'changes_text'):
            return
        if self.journal is None or self.journal_error:
            lines=[self.journal_error or 'O diário de alterações não está disponível.']
            if self.journal_off_text is not None:
                lines.append(self.journal_off_text)
        else:
            lines=list(self.journal.summary_lines())
            unknown=self._count_status('unknown')
            if unknown:
                lines+=['',CHANGES_UNKNOWN_TEXT.format(n=unknown)]
        if self.legacy_state=='pending':
            lines+=['',POWER_LEGACY_PENDING_TEXT+' '+CHANGES_LEGACY_BLOCKED_TEXT]
        elif self.legacy_state=='unreadable':
            lines+=['',POWER_LEGACY_UNREADABLE_TEXT+' '+CHANGES_LEGACY_BLOCKED_TEXT]
        elif self.legacy_state=='applied':
            lines+=['',POWER_LEGACY_TEXT+' '+CHANGES_LEGACY_WHERE_TEXT]
        self._write(self.changes_text,'\n'.join(lines))

    def _last_applied_power(self):
        if self.journal is None:
            return None
        applied=[e for e in self.journal.entries() if e['kind']==POWER_KIND and e['status']=='applied']
        return applied[-1]['id'] if applied else None

    def _update_power_buttons(self):
        if not hasattr(self,'btn_apply'):
            return
        busy=self.power_busy
        usable=self.journal is not None and not self.journal_error
        legacy=self.legacy_state!='none'
        unknown=self._count_status('unknown')
        can_apply=usable and not busy and not legacy and not unknown
        can_revert=usable and not busy and self._last_applied_power() is not None
        self.btn_apply.state(['!disabled'] if can_apply else ['disabled'])
        if hasattr(self,'btn_refresh'):
            self.btn_refresh.state(['disabled'] if busy else ['!disabled'])
        self.btn_revert.state(['!disabled'] if can_revert else ['disabled'])
        if legacy:
            if not self.btn_legacy.winfo_manager():
                self.btn_legacy.pack(side='left',padx=(9,0))
            # FIX-P3-03-06/07 (R-30): com o diário desligado ou ausente, este botão também fica desligado.
            self.btn_legacy.state(['!disabled'] if usable and not busy else ['disabled'])
        elif self.btn_legacy.winfo_manager():
            self.btn_legacy.pack_forget()
        if self.journal_error:
            self.power_status.set(self._journal_error_text())
        elif legacy:
            self.power_status.set(POWER_LEGACY_TEXT)
        self.power_block.set(CHANGES_UNKNOWN_TEXT.format(n=unknown) if unknown else '')
        if hasattr(self,'btn_undo_all'):
            can_undo_all=usable and not busy and self._count_status('applied')>0
            self.btn_undo_all.state(['!disabled'] if can_undo_all else ['disabled'])
            can_recheck=(usable and not busy
                         and self._count_status('applied')+self._count_status('unknown')>0)
            self.btn_recheck.state(['!disabled'] if can_recheck else ['disabled'])
            self._render_changes()

    def _journal_failed(self,message,title='Diário de alterações',off_text=POWER_JOURNAL_OFF_TEXT):
        # R-28: esta função já mostra a janela de erro; quem chama não abre outra.
        # off_text=None: o texto já é completo (já diz o que fica desligado).
        self.journal=None
        self.journal_error=message
        self.journal_off_text=off_text
        self._update_power_buttons()
        self._show('error',title,self._journal_error_text())

    def _journal_error_text(self):
        """Erro do diário + a frase de "desligado", só quando o erro ainda não diz isso."""
        message=self.journal_error or 'O diário de alterações não está disponível.'
        if self.journal_off_text is None:
            return message
        return message+' '+self.journal_off_text

    def _run_power_job(self,work,done):
        self.power_busy=True
        self._update_power_buttons()
        job=Job(lambda cancelled,progress:work())
        self._power_job=job
        def poll():
            result=job.poll()
            if result is None:
                self._timers.after(80,poll)
                return
            self.power_busy=False
            kind,value=result
            if kind!='done':
                value={'status':'error'}
            done(value)
            self._update_power_buttons()
        self._timers.after(10,poll)

    def _render_plans(self,plans,active,extra=()):
        self.plans=plans
        self.plan_box['values']=[p['name']+' | '+p['guid']+('  [ATUAL]' if p['guid']==active else '') for p in plans]
        idx=next((i for i,p in enumerate(plans) if p['guid']==active),0)
        if plans:
            self.plan_box.current(idx)
        text=['PLANOS DO WINDOWS — LEITURA','']
        for p in plans:
            text.append(('● ' if p['guid']==active else '  ')+p['name']+' | '+p['guid'])
        text.extend(extra)
        self._write(self.power_text,'\n'.join(text))

    def _read_plans_work(self):
        try:
            return {'plans':self.power_adapter.available(),'active':self.power_adapter.read(POWER_KEY)}
        except Exception:
            return {'plans':None,'active':None}

    def apply_plan(self):
        if self.power_busy:
            return
        if self.journal is None or self.journal_error:
            self._show('error','Plano de energia',self._journal_error_text())
            return
        if self.legacy_state!='none':
            self._show('warning','Plano de energia',POWER_LEGACY_TEXT)
            return
        unknown=self._count_status('unknown')
        if unknown:
            # Recusa antes de perguntar: um item sem confirmação bloqueia novas trocas.
            self._show('warning','Plano de energia',CHANGES_UNKNOWN_TEXT.format(n=unknown))
            return
        if not self.plans or self.plan_box.current()<0:
            self._show('info','Energia','Clique em Atualizar primeiro.');return
        target=self.plans[self.plan_box.current()]
        if not self._is_elevated():
            # O app nunca pede elevação: só explica e não roda nada.
            self.power_status.set(POWER_ADMIN_TEXT)
            self._show('warning','Plano de energia',POWER_ADMIN_TEXT)
            return
        if not self._ask('Confirmar alteração reversível',
                'Deseja selecionar o plano “'+target['name']+'” no Windows?\n\n'
                'Pode alterar temperatura, consumo e autonomia. Sem ganho de FPS garantido.\n'
                'Antes, o app cria um ponto de restauração do Windows e anota a troca no diário de alterações, '
                'para você poder desfazer.\n\n'
                'Esta é uma alteração real do sistema, não apenas um teste.'):
            return
        guid=target['guid']
        journal=self.journal
        def work():
            try:
                if journal.has_blocking():
                    journal.recover_interrupted()
                try:
                    if self.power_adapter.read(POWER_KEY)==guid:
                        outcome={'status':'unchanged'}
                        outcome.update(self._read_plans_work())
                        return outcome
                except Exception:
                    pass
                self.state_dir.mkdir(parents=True,exist_ok=True)
                journal.apply_batch([{'kind':POWER_KIND,'key':POWER_KEY,'after':guid}])
                outcome={'status':'applied'}
            except BatchRefused as exc:
                outcome={'status':'refused','message':str(exc)}
            except JournalError as exc:
                outcome={'status':'journal','message':str(exc)}
            except Exception:
                outcome={'status':'error'}
            outcome.update(self._read_plans_work())
            return outcome
        self.power_status.set('Criando o ponto de restauração e trocando o plano… Isto pode demorar um pouco.')
        self._run_power_job(work,self._apply_done)

    def _after_power_job(self,outcome):
        if outcome.get('plans'):
            self._render_plans(outcome['plans'],outcome.get('active'))

    def _apply_done(self,outcome):
        self._after_power_job(outcome)
        status=outcome.get('status')
        if status=='applied':
            self.power_status.set('Plano trocado e anotado no diário de alterações. Use Desfazer para voltar.')
            self.note.set('Plano alterado e registrado para reversão.')
        elif status=='unchanged':
            self.power_status.set('Este plano já estava ativo. Nada foi alterado.')
            self.note.set('Este plano já estava ativo.')
        elif status=='journal':
            self.power_status.set('')
            self._journal_failed(outcome.get('message',''))
        elif status=='refused':
            message=outcome.get('message','')
            if 'ponto de restauração' in message:
                message+=' '+POWER_RESTORE_POINT_HELP
            self.power_status.set(message)
            self._show('warning','Plano de energia',message)
        else:
            self.power_status.set(POWER_GENERIC_FAIL)
            self._show('error','Plano de energia',POWER_GENERIC_FAIL)

    def revert_plan(self):
        if self.power_busy:
            return
        if self.journal is None or self.journal_error:
            self._show('error','Reverter energia',self._journal_error_text())
            return
        change_id=self._last_applied_power()
        if change_id is None:
            self._show('info','Reverter energia','Não há troca de plano feita pelo app para desfazer.')
            return
        if not self._ask('Reverter plano','Restaurar o plano de energia que estava ativo antes da última troca feita por este app?'):
            return
        journal=self.journal
        def work():
            try:
                ok,reason=journal.undo(change_id)
                outcome={'status':'reverted' if ok else 'refused','message':reason}
            except JournalError as exc:
                outcome={'status':'journal','message':str(exc)}
            except Exception:
                outcome={'status':'error'}
            outcome.update(self._read_plans_work())
            return outcome
        self.power_status.set('Desfazendo a última troca de plano…')
        self._run_power_job(work,self._revert_done)

    def _revert_done(self,outcome):
        self._after_power_job(outcome)
        status=outcome.get('status')
        if status=='reverted':
            self.power_status.set('Plano de energia anterior restaurado.')
            self.note.set('Plano de energia anterior restaurado.')
        elif status=='journal':
            self.power_status.set('')
            self._journal_failed(outcome.get('message',''))
        elif status=='refused':
            message=outcome.get('message') or POWER_GENERIC_FAIL
            self.power_status.set(message)
            self._show('warning','Reverter energia',message)
        else:
            self.power_status.set(POWER_GENERIC_FAIL)
            self._show('error','Reverter energia',POWER_GENERIC_FAIL)

    # ---------- P3-03 fatia 2b-1: desfazer tudo ----------
    def undo_all_changes(self):
        """Desfaz tudo o que está aplicado, do mais novo ao mais antigo, numa thread (R-10).

        Não exige administrador e não cria ponto de restauração."""
        if self.power_busy:
            return
        if self.journal is None or self.journal_error:
            self._show('error','Desfazer tudo',self._journal_error_text())
            return
        count=self._count_status('applied')
        if not count:
            self.changes_status.set(CHANGES_EMPTY_TEXT)
            self._show('info','Desfazer tudo',CHANGES_EMPTY_TEXT)
            return
        if not self._ask('Desfazer tudo',CHANGES_CONFIRM_TEXT.format(n=count)):
            self.changes_status.set('Desfazer tudo cancelado. Nada foi desfeito.')
            return
        journal=self.journal
        def work():
            try:
                done,pending,reason=journal.undo_all()
                outcome={'status':'done','done':len(done),'pending':len(pending),'reason':reason}
            except JournalError as exc:
                outcome={'status':'journal','message':str(exc),
                         'done':len(getattr(exc,'done',None) or [])}
            except Exception:
                outcome={'status':'error'}
            outcome.update(self._read_plans_work())
            return outcome
        self.changes_status.set('Desfazendo as alterações, da mais nova para a mais antiga…')
        self._run_power_job(work,self._undo_all_done)

    def _undo_all_done(self,outcome):
        self._after_power_job(outcome)
        status=outcome.get('status')
        if status=='done':
            done,pending=outcome.get('done',0),outcome.get('pending',0)
            if pending:
                message=CHANGES_STOPPED_TEXT.format(done=done,pending=pending,
                                                    reason=outcome.get('reason') or POWER_GENERIC_FAIL)
                self.changes_status.set(message)
                self._show('warning','Desfazer tudo',message)
            elif done:
                message=(CHANGES_ONE_UNDONE_TEXT if done==1
                         else CHANGES_ALL_UNDONE_TEXT.format(n=done))
                self.changes_status.set(message)
                self.note.set(message)
            else:
                self.changes_status.set(CHANGES_EMPTY_TEXT)
        elif status=='journal':
            message=outcome.get('message','')
            done=outcome.get('done',0)
            if done:
                # R-19: algo já foi desfeito no sistema; nunca dizer "Nada foi gravado".
                message=(CHANGES_DONE_BEFORE_ERROR_TEXT.format(n=done)
                         +message.replace(_NOTHING_SAVED,'').strip())
            self.changes_status.set(message)
            self._journal_failed(message)
        else:
            # R-27: no meio do lote algo pode já ter mudado; o diário em memória não é
            # confiável, então não mostra contagem e desliga o diário até reabrir o app.
            message=CHANGES_UNEXPECTED_ERROR_TEXT
            self.changes_status.set(message)
            self._journal_failed(message,title='Desfazer tudo',off_text=None)

    # ---------- P3-03 fatia 2b-2: conferir de novo ----------
    def recheck_changes(self):
        """Lê o valor atual de cada alteração numa thread (R-10) e acerta o diário.

        Só lê: sem confirmação, sem administrador e sem ponto de restauração."""
        if self.power_busy:
            return
        if self.journal is None or self.journal_error:
            self._show('error',CHANGES_RECHECK_TITLE,self._journal_error_text())
            return
        if not self._count_status('applied')+self._count_status('unknown'):
            self.changes_status.set(CHANGES_RECHECK_NOTHING_TEXT)
            return
        journal=self.journal
        def work():
            try:
                result=journal.recheck()
                outcome={'status':'done','changed':len(result['changed']),
                         'outside':len(result['outside']),'unreadable':len(result['unreadable'])}
            except JournalError as exc:
                outcome={'status':'journal','message':str(exc)}
            except Exception:
                outcome={'status':'error'}
            outcome.update(self._read_plans_work())
            return outcome
        self.changes_status.set(CHANGES_RECHECK_RUNNING_TEXT)
        self._run_power_job(work,self._recheck_done)

    def _recheck_done(self,outcome):
        self._after_power_job(outcome)
        status=outcome.get('status')
        if status=='done':
            changed=outcome.get('changed',0)
            outside,unreadable=outcome.get('outside',0),outcome.get('unreadable',0)
            # R-33: "o diário já estava certo" só quando todos os itens foram conferidos.
            if changed:
                message=CHANGES_RECHECK_FIXED_TEXT.format(n=changed)
            elif not outside and not unreadable:
                message=CHANGES_RECHECK_SAME_TEXT
            else:
                message=CHANGES_RECHECK_NONE_CHANGED_TEXT
            if outside:
                message+=CHANGES_RECHECK_OUTSIDE_TEXT.format(n=outside)
            if unreadable:
                message+=CHANGES_RECHECK_UNREADABLE_TEXT.format(n=unreadable)
            self.changes_status.set(message)
            self.note.set(message)
            if outside or unreadable:
                self._show('warning',CHANGES_RECHECK_TITLE,message)
        elif status=='journal':
            message=outcome.get('message','')
            self.changes_status.set(message)
            self._journal_failed(message,title=CHANGES_RECHECK_TITLE)
        else:
            # Mesmo padrão do "Desfazer tudo" (R-27/R-30): o diário em memória não é
            # confiável; desliga até reabrir o app, com texto fixo (sem mensagem crua).
            message=CHANGES_RECHECK_ERROR_TEXT
            self.changes_status.set(message)
            self._journal_failed(message,title=CHANGES_RECHECK_TITLE,off_text=None)

    def undo_legacy_plan(self):
        """Desfaz a troca feita pela versão antiga (``pcro-power-1``).

        O arquivo antigo nunca é apagado nem convertido; só ``revert_power_plan``
        o atualiza, e só quando a troca antiga ainda está aplicada.
        """
        if self.power_busy:
            return
        if self.journal is None or self.journal_error:
            # FIX-P3-03-06/07: defesa dupla, mesma condição das outras três ações; o botão
            # já fica desligado com o diário desligado.
            self._show('error','Desfazer alteração antiga',self._journal_error_text())
            return
        self.legacy_state=legacy_power_pending(self.power_journal)
        if self.legacy_state=='none':
            self._update_power_buttons()
            self.power_status.set('Não há troca antiga para desfazer.')
            return
        if self.legacy_state=='pending':
            self._show('warning','Desfazer alteração antiga',POWER_LEGACY_PENDING_TEXT)
            return
        if self.legacy_state=='unreadable':
            self._show('warning','Desfazer alteração antiga',POWER_LEGACY_UNREADABLE_TEXT)
            return
        if not self._ask('Desfazer alteração antiga','Restaurar o plano de energia que estava ativo antes da troca feita pela versão antiga do app?'):
            return
        path=self.power_journal
        def work():
            try:
                revert_power_plan(path)
                outcome={'status':'reverted'}
            except OptimizationError as exc:
                text=str(exc)
                outcome={'status':'refused','message':text if text in _LEGACY_KNOWN_MESSAGES else POWER_GENERIC_FAIL}
            except Exception:
                outcome={'status':'error'}
            outcome.update(self._read_plans_work())
            return outcome
        self.power_status.set('Desfazendo a troca antiga…')
        self._run_power_job(work,self._legacy_done)

    def _legacy_done(self,outcome):
        self.legacy_state=legacy_power_pending(self.power_journal)
        self._revert_done(outcome)

    def import_csv(self):
        scenario=' '.join(self.scenario.get().strip().split())
        if not scenario:
            messagebox.showwarning('Benchmark','Dê um nome ao cenário.');return
        path=filedialog.askopenfilename(filetypes=[('Arquivos CSV','*.csv'),('Texto delimitado','*.txt')],
                                        title='Selecione amostras de FPS/frametime por quadro')
        if not path:
            return
        try:
            metrics=parse_csv_file(path)
            if not messagebox.askyesno('Confirmar importação',
                f'Cenário: {scenario}\nFase: {self.phase.get()}\nAmostras: {metrics["samples"]}\n'
                f'FPS médio: {metrics["avg_fps"]:.1f}\n1% low: {metrics["low_1"]:.1f}\n'
                'Registrar apenas essas estatísticas (sem copiar o CSV)?'):
                return
            insert_run(self.bench_journal,scenario,self.phase.get(),metrics)
            self.note.set('Benchmark incluído. Nenhum ajuste de Windows realizado.')
            self.refresh_bench()
        except Exception as exc:
            messagebox.showerror('Importar benchmark',_error_text(exc))

    def refresh_bench(self):
        scenario=' '.join(self.scenario.get().strip().split())
        try:
            data=read_history(self.bench_journal)
            result=summarize(data,scenario)
        except Exception as exc:
            messagebox.showerror('Comparação',str(exc));return
        lines=['BENCHMARKS  |  '+scenario,'',
               f"Antes: {result['count']['antes']} execução(ões)   |   Depois: {result['count']['depois']} execução(ões)",'']
        for label,key in [('ANTES','antes'),('DEPOIS','depois')]:
            if key in result['median']:
                m=result['median'][key]
                lines.append(f"{label}: FPS médio {m['avg_fps']:.1f} | 1% low {m['low_1']:.1f} | 0,2% low {m['low_02']:.1f}")
            else:
                lines.append(label+': sem dados')
        if result['delta_pct']:
            delta=result['delta_pct']
            lines.extend(['','DIFERENÇA DAS MEDIANAS:',
                          f"FPS médio {delta['avg_fps']:+.1f}% | 1% low {delta['low_1']:+.1f}% | 0,2% low {delta['low_02']:+.1f}%"])
        lines.extend(['','AMOSTRAGEM: '+('3+ por fase ✓' if result['sufficient_repeats'] else 'INCOMPLETA — recomenda-se 3 execuções por fase'),
                     'Não significa prova causal; compare jogos, condições térmicas e variabilidade.'])
        self._write(self.bench_text,'\n'.join(lines))
