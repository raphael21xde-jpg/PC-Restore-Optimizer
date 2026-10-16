import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser
from recovery_kit import load_plan
from app_recovery import selected_items, query, install, package_id, data_files, restore_data, game_help, require_equivalent_edition


def show_app_recovery(parent):
    win = tk.Toplevel(parent); win.title('Recuperar aplicativos, jogos e saves — v0.5.14'); win.geometry('1080x780')
    frame = ttk.Frame(win, padding=12); frame.pack(fill='both', expand=True)
    state = {'items': [], 'busy': False, 'reviewed': None, 'doc': None}
    search_name = tk.StringVar()
    status = tk.StringVar(value='Abra seu plano exportado ou use as escolhas atuais.')
    ttk.Label(frame, text='Recuperar aplicativos, jogos e saves', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Instalador, arquivos do jogo e saves são etapas diferentes. Nada é instalado só por abrir esta tela.', wraplength=1000).pack(anchor='w', pady=5)
    top = ttk.Frame(frame); top.pack(fill='x')
    tree = ttk.Treeview(frame, columns=('tipo','nome','dados'), show='headings', height=7)
    for col, label, width in [('tipo','Tipo',100),('nome','Item escolhido',430),('dados','Caminhos previstos no plano (não prova de backup)',430)]:
        tree.heading(col,text=label); tree.column(col,width=width)
    tree.pack(fill='x',pady=8)
    output = tk.Text(frame, height=14, wrap='word'); output.pack(fill='both',expand=True,pady=6)
    def write(text):
        output.configure(state='normal'); output.delete('1.0','end'); output.insert('1.0',text); output.configure(state='disabled')
    def item():
        sel=tree.selection()
        if not sel: raise ValueError('Selecione um item da lista.')
        return state['items'][int(sel[0])]
    def changed(_=None):
        state['reviewed']=None
        try:
            i=item(); search_name.set(i['name']); paths=i.get('save_paths' if i['kind']=='game' else 'data_paths',[])
            text=f"{i['name']}\nOrigem: {i.get('origin','não informada')}\nFabricante original: {i.get('publisher') or 'não identificado'}\nVersão original: {i.get('version') or 'não identificada'}\nEdição original: {i.get('edition') or 'não confirmada'}\n\nCaminhos previstos:\n"+'\n'.join(paths or ['Não localizados'])
            if i['kind']=='game':text+='\n\n'+game_help(i)[0]
            else:text+='\n\nBusque o programa, copie o ID exato do resultado e confira fabricante, versão e origem antes de instalar. Um nome semelhante não é confirmação. Dados do aplicativo serão recuperados separadamente.'
            write(text)
        except ValueError:pass
    tree.bind('<<TreeviewSelect>>',changed)
    def populate(doc):
        state['doc']=doc; state['items']=selected_items(doc); state['reviewed']=None
        tree.delete(*tree.get_children())
        for n,i in enumerate(state['items']):
            paths=i.get('save_paths' if i['kind']=='game' else 'data_paths',[])
            tree.insert('', 'end', iid=str(n), values=('Jogo' if i['kind']=='game' else 'Aplicativo', i.get('name','?'), f'{len(paths)} local(is)'))
        status.set(f"{len(state['items'])} itens marcados para manter. Nenhuma instalação executada.")
    def current():
        if state['busy']: return
        items=[]
        for key,i in parent.catalog_items.items():
            if parent.catalog_choices.get(key)=='keep':
                items.append(dict(id=key, decision='keep', kind=i['kind'],name=i['name'],origin=i.get('source'),edition=i.get('edition'),publisher=i.get('publisher'),version=i.get('version'),save_paths=i.get('paths',[]) if i['kind']=='game' else [],data_paths=i.get('paths',[]) if i['kind']=='app' else []))
        populate({'items':items})
    def open_plan():
        if state['busy']: return
        p=filedialog.askopenfilename(parent=win,title='Plano de recuperação exportado',filetypes=[('Plano JSON','*.json')])
        if p:
            try:populate(load_plan(p))
            except Exception as exc:messagebox.showerror('Plano inválido',str(exc),parent=win)
    ttk.Button(top,text='Usar escolhas atuais',command=current).pack(side='left',padx=4)
    ttk.Button(top,text='Abrir plano salvo antes da formatação',command=open_plan).pack(side='left',padx=4)
    def task(fn,done):
        if state['busy']: return
        state['busy']=True; status.set('Operação em andamento…')
        def finish(result=None,error=None):
            state['busy']=False
            if error: status.set('Operação não concluída.'); messagebox.showerror('Falha',error,parent=win)
            else:done(result)
        def worker():
            try:
                result=fn(); parent.after(0,lambda:finish(result=result))
            except Exception as exc:parent.after(0,lambda e=str(exc):finish(error=e))
        threading.Thread(target=worker,daemon=True).start()
    searchrow=ttk.Frame(frame); searchrow.pack(fill='x', pady=4)
    ttk.Label(searchrow, text='Nome para buscar (pode retirar o número da versão):').pack(side='left')
    ttk.Entry(searchrow, textvariable=search_name, width=45).pack(side='left', padx=6)
    row=ttk.Frame(frame);row.pack(fill='x',pady=5)
    ttk.Label(row,text='ID do pacote exibido na busca:').pack(side='left')
    pkg=tk.StringVar();ttk.Entry(row,textvariable=pkg,width=40).pack(side='left',padx=6)
    pkg.trace_add('write',lambda *_:state.update(reviewed=None))
    def app_item():
        i=item()
        if i['kind']!='app':raise ValueError('Para jogos, use Orientação do launcher. O WinGet nesta tela reinstala aplicativos.')
        return i
    def query_action(action):
        if state['busy']:return
        try:
            i=app_item(); value=search_name.get() if action=='search' else package_id(pkg.get())
            identity=i.get('id',i['name'])
        except Exception as exc:messagebox.showinfo('Seleção necessária',str(exc),parent=win);return
        state['reviewed']=None
        def done(result):
            code,text=result;write(text or 'Sem resultado.')
            status.set(f'Consulta {action}: código {code}. Leia o resultado acima.')
            if action=='show' and code==0 and pkg.get().strip()==value and tree.selection() and item().get('id',item()['name'])==identity:
                state['reviewed']=(identity,value)
        task(lambda:query(action,value),done)
    actions=ttk.Frame(frame);actions.pack(fill='x',pady=5)
    ttk.Button(actions,text='1. Buscar programa no WinGet',command=lambda:query_action('search')).pack(side='left',padx=3)
    ttk.Button(actions,text='2. Conferir pacote escolhido',command=lambda:query_action('show')).pack(side='left',padx=3)
    def do_install():
        if state['busy']:return
        try:
            i=app_item(); value=package_id(pkg.get()); identity=i.get('id',i['name'])
            if state['reviewed']!=(identity,value):raise ValueError('Confira o pacote escolhido antes de instalar.')
            require_equivalent_edition(i,value)
        except Exception as exc:messagebox.showinfo('Confira o pacote',str(exc),parent=win);return
        if not messagebox.askyesno('Confirmar instalação',f"Item do seu plano: {i['name']}\nPacote escolhido: {value}\nFonte: winget\n\nVocê conferiu que nome e fabricante correspondem ao aplicativo desejado?\n\nA instalação baixa arquivos e altera o Windows. Uma janela será aberta; leia os termos e solicitações do instalador. Continuar?",parent=win):return
        def done(code):
            status.set(f'Instalador terminou com código {code}. Use Verificar instalação e abra o programa para validar.')
            write('Código do instalador: '+str(code)+'\n\nCódigo zero indica sucesso reportado pelo instalador, não prova que todos os dados ou licenças foram recuperados. Use Verificar instalação; depois recupere os dados separadamente.')
        task(lambda:install(value),done)
    ttk.Button(actions,text='3. Instalar pacote confirmado',command=do_install).pack(side='left',padx=3)
    ttk.Button(actions,text='4. Verificar instalação',command=lambda:query_action('list')).pack(side='left',padx=3)
    lower=ttk.Frame(frame);lower.pack(fill='x',pady=7)
    def help_game():
        try:
            i=item(); text,url=game_help(i);write(text)
            if url and messagebox.askyesno('Ajuda do launcher','Abrir a orientação oficial no navegador?',parent=win):webbrowser.open(url)
        except Exception as exc:messagebox.showinfo('Selecione o jogo',str(exc),parent=win)
    def recover():
        if state['busy']:return
        try:i=dict(item())
        except ValueError as exc:messagebox.showinfo('Seleção',str(exc),parent=win);return
        manifest=filedialog.askopenfilename(parent=win,title='Escolha manifest.json do backup que contém este item',filetypes=[('Manifesto JSON','*.json')])
        if not manifest:return
        try:
            files=data_files(manifest,i)
            if not files:raise ValueError('Nenhum arquivo correspondente neste backup. Selecionar um item não significa que ele já foi copiado.')
        except Exception as exc:messagebox.showerror('Dados não localizados',str(exc),parent=win);return
        write(f"{i['name']} — {len(files)} arquivo(s) encontrados:\n\n"+'\n'.join(f.get('source','?') for f in files.values()))
        if not messagebox.askyesno('Recuperar dados verificados',f"{i['name']}: {len(files)} arquivo(s).\nRecuperar em uma pasta NOVA para conferência?\nNenhum save ou configuração instalado será substituído.",parent=win):return
        dest=filedialog.askdirectory(parent=win,title='Pasta que receberá a recuperação isolada')
        if not dest:return
        def done(result):
            path,count=result;write(f'{count} arquivo(s) recuperados e verificados:\n{path}\n\nA aplicação no perfil atual ainda é manual: inicie o jogo/aplicativo uma vez para criar os caminhos, feche-o, proteja os dados novos e confira os caminhos. Não substitua cegamente o nome do usuário antigo. Confira conflitos de nuvem antes de copiar saves.');status.set('Recuperação isolada concluída. Dados ainda não aplicados ao programa instalado.')
        task(lambda:restore_data(manifest,i,dest),done)
    ttk.Button(lower,text='Orientação do launcher / jogos',command=help_game).pack(side='left',padx=3)
    ttk.Button(lower,text='Recuperar dados / saves deste item',command=recover).pack(side='left',padx=3)
    ttk.Button(lower,text='Ajuda para instalar WinGet',command=lambda:webbrowser.open('https://learn.microsoft.com/en-us/windows/package-manager/winget/')).pack(side='left',padx=3)
    ttk.Label(frame,textvariable=status,wraplength=1000).pack(anchor='w',pady=7)
    def close():
        if state['busy']:messagebox.showinfo('Operação em andamento','Aguarde a operação terminar. Não encerre o aplicativo durante a instalação.',parent=win)
        else:win.destroy()
    win.protocol('WM_DELETE_WINDOW',close)
    current()
