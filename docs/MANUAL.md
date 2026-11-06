# Manual curto do PC Restore & Optimizer

Este manual explica, em poucas palavras, como usar o app. Os nomes entre aspas são
exatamente os nomes dos menus, abas e botões que aparecem na tela.

## O que o app faz

O PC Restore & Optimizer ajuda você a trocar de Windows sem perder nada e, depois,
a deixar o computador mais rápido com segurança. Ele:

- mostra os discos e o que existe em cada um (só olha, não muda nada);
- deixa você escolher o que guardar: pastas, arquivos, jogos, saves e navegadores;
- faz um backup conferido (cada arquivo copiado é conferido com SHA-256);
- testa se o backup consegue ser restaurado antes de você formatar;
- orienta a reinstalação do Windows e a volta dos seus dados depois;
- mede o computador e aplica ajustes de desempenho que podem ser desfeitos.

O menu da esquerda tem: "Visão geral", "Meu computador", "Preservação",
"Instalar Windows", "Recuperação", "Depois de formatar", "Central de recuperação",
"Cópia protegida para outro disco", "Otimização", "Diagnóstico" e
"Histórico e relatórios".

O item "Cópia protegida para outro disco" é um recurso protegido, ainda em teste.
Por enquanto, use o backup normal descrito abaixo.

## Instalar e abrir

1. Instale o Python 3.13 (site oficial python.org). Na instalação, marque a opção que
   coloca o Python no PATH.
2. Baixe a pasta do app e abra-a.
3. Dê dois cliques em `INICIAR.bat`. Ele abre o app com o Python instalado.

**Abra do jeito normal (sem administrador) quase sempre.** Backup, restauração e
diagnóstico funcionam assim. O app recusa restaurar arquivos e fazer a cópia para
outro disco quando está aberto como administrador, porque os arquivos ficariam com
permissões erradas e a sua conta normal poderia não conseguir abri-los.

**Só abra como administrador para aplicar ajustes de otimização** (abas
"4  Energia reversível", "8  Ajustes seguros" e "9  Ajustes avançados"). Antes de
mudar algo, o app cria um ponto de restauração do Windows, e isso exige
administrador. O app nunca pede isso sozinho. Para abrir assim: feche o app, clique
com o botão direito no atalho dele, escolha "Executar como administrador" e entre
com a **sua própria conta**. Se o Windows pedir a senha de outra conta, os ajustes
valeriam para aquela outra conta; por isso o app confere a conta e, se não for a
sua, não lê nem muda nada.

Terminou os ajustes? Feche e abra o app de novo do jeito normal para fazer backup ou
restaurar. "Desfazer tudo" funciona sem administrador.

## Diagnóstico de discos (só leitura)

No menu, clique em "Diagnóstico".

- "Analisar computador e discos": mostra os discos físicos, as partições, a EFI e
  outros detalhes. Só lê, não muda nada.
- "Simular destino de backup (somente leitura)": confere se um disco serve para
  receber o backup, sem copiar nada.
- "Conferir origens e destinos (somente leitura)": confere de onde os arquivos vão
  sair e para onde vão.
- "Exportar relatório JSON": salva o resultado num arquivo, se você quiser guardar.

Dica: o disco que vai receber o backup deve ser **outro disco físico**, que não vai
ser formatado. Uma partição no mesmo disco do Windows não protege seus dados.

## Backup

1. **Escolha o que procurar.** Em "Meu computador", marque as unidades e clique em
   "Examinar unidades marcadas". O app lista jogos, aplicativos e arquivos. Ele só olha.
2. **Escolha o que manter.** Em "Preservação", revise a lista. Em cada item você pode
   marcar "Manter", "Não incluir no backup" ou "Pendente".
   - "Não incluir no backup" quer dizer só **não copiar**. O app **nunca apaga** o
     arquivo do seu disco por causa disso.
   - "Retirar do backup (não apaga)" também só tira a marcação.
3. **Navegadores.** Na tela "Navegadores", o app ajuda a guardar favoritos e
   preferências numa cópia protegida ("Criar backup protegido do navegador").
4. **Faça o backup.** Na revisão do backup, clique em "Escolher destino" e escolha
   uma pasta no outro disco. Clique em "1. Recalcular plano e espaço" para ver se cabe.
   Depois clique em "2. Iniciar backup (confirmação dupla)". O app pergunta duas vezes
   antes de começar.
5. **Caiu a energia ou o PC travou?** Clique em "Retomar backup interrompido" e
   escolha o arquivo `manifest.json` do backup que parou. O app continua esse backup.

Os arquivos originais nunca são mexidos: o backup só lê e copia.

## Testar e restaurar

**Antes de formatar, teste o backup.** Um backup que nunca foi testado pode esconder
um problema.

1. No menu, clique em "Histórico e relatórios". Escolha o backup e clique em
   "Testar restauração de arquivo pequeno". O app traz um arquivo de volta para uma
   pasta nova de conferência e confere se ele é igual ao original.
2. Na tela "Recuperação", clique em "5. Conferir TODO o backup (SHA-256)". O app
   confere cada arquivo do backup. Pode demorar; se precisar, use "Cancelar auditoria".
   No fim, você pode clicar em "Salvar relatório de auditoria".
3. Para o navegador, na tela "Navegadores", clique em
   "Restaurar navegador — assistente" e siga os passos. Senhas e favoritos voltam
   pelo próprio navegador (importação).

A restauração sempre vai para uma pasta nova. O app nunca sobrescreve nem apaga o
que já existe. Lembre: o app recusa restaurar se estiver aberto como administrador.

## Reinstalação guiada

O app **não formata e não instala o Windows**. Quem formata e instala é o
**instalador oficial da Microsoft**, operado por você. O app prepara e orienta.

**Antes de formatar** ("Instalar Windows"):

- siga a lista de preparação da tela: backup do C: conferido, mídia oficial do
  Windows, edição e ativação, drivers, disco físico certo e plano de recuperação;
- os botões "Revisar preservação", "Diagnóstico dos discos" e
  "Recuperação depois do Windows" levam às telas de cada etapa;
- na tela "Recuperação", clique em "1. Exportar plano para usar depois" e guarde o
  arquivo no disco do backup.

Na hora de instalar, escolha com muito cuidado o disco do Windows no instalador:
confira pelo tamanho e nunca escolha o disco onde está o backup.

**Depois de formatar** ("Depois de formatar"):

1. abra o app no Windows novo e escolha o backup;
2. siga as cinco etapas: "Conferir discos e letras", "Restaurar os arquivos",
   "Reinstalar os programas", "Religar os launchers de jogos" e
   "Navegador e senhas";
3. em cada etapa use "Abrir", e no fim marque "Feito" ou "Pular".

Se a letra de uma unidade mudou, o app mostra como trocá-la à mão no
"Gerenciamento de Disco". Ele nunca troca letras sozinho.

## Otimização

No menu, clique em "Otimização". As abas são numeradas.

1. **Conheça o PC.** Na aba "1  Diagnóstico", clique em "Analisar este PC". Só lê.
2. **Meça antes.** Feche os programas e clique em "Medir ANTES (1 min)". Não use o
   PC durante a medição.
3. **Aplique os ajustes seguros.** Abra o app como administrador (veja a seção
   Instalar e abrir). Na aba "8  Ajustes seguros", clique em "Ver estado atual"
   e depois em "Aplicar ajustes seguros". O app mostra o que vai mudar, pergunta antes
   e cria um ponto de restauração.
4. **Ajustes avançados (opcional).** Na aba "9  Ajustes avançados", cada ajuste é
   aplicado um de cada vez. A pergunta mostra o lado ruim do ajuste e vem com "Não"
   marcado: apertar Enter não aplica nada. Só responda "Sim" se entendeu o aviso.
5. **Meça depois.** Feche os mesmos programas e clique em "Medir DEPOIS (1 min)".
   O app compara processador, memória, processos, programas que abrem com o Windows
   e plano de energia.

Também existe "Medir uso parado (2 min)", que mostra o que usa o PC quando você não
está mexendo nele.

## Desfazer

Tudo o que o app muda fica anotado e pode ser desfeito.

- Na aba "7  Alterações feitas", veja a lista do que foi mudado.
- "Desfazer tudo" volta cada ajuste para como estava antes. Funciona sem
  administrador.
- "Conferir de novo" lê de novo o estado real do Windows, para confirmar o que está
  aplicado.

Alguns ajustes só valem depois de sair da conta e entrar de novo, ou de reiniciar.
O app avisa quando for assim e nunca reinicia o PC sozinho. Se algo der muito errado,
você também pode usar o ponto de restauração do Windows criado antes da mudança.

## Check-up

- "Analisar este PC" (aba "1  Diagnóstico"): mostra Windows, processador, placa de
  vídeo, memória, discos, placa-mãe e versão da BIOS. Só lê.
- "Check-up de segurança": olha os programas que abrem com o Windows, os processos
  e o Defender, e aponta o que merece atenção. Nada é mudado, encerrado ou tirado do
  lugar, e não precisa de administrador.

## BIOS e drivers

Na aba "6  BIOS e drivers", o app explica o que pode ser melhorado (por exemplo,
perfil de memória XMP/EXPO e Resizable BAR).

Depois de "Analisar este PC", o botão "Ver passo a passo" mostra as instruções para
o seu caso. **O app só orienta.** Ele nunca muda a BIOS: se você quiser mudar algo,
é você quem entra na BIOS e faz, seguindo o manual da sua placa-mãe.

## O que o app NUNCA faz

- Nunca formata nem particiona discos.
- Nunca apaga seus arquivos. "Não incluir no backup" só quer dizer não copiar.
- Nunca mexe na EFI nem no BCD (a parte que dá a partida no Windows).
- Nunca instala o Windows: quem instala é o instalador oficial da Microsoft, com você.
- Nunca desliga o Defender nem o Windows Update.
- Nunca faz debloat agressivo (arrancar partes do Windows).
- Nunca muda a BIOS: só mostra o passo a passo.
- Nunca troca letras de unidades sozinho e nunca reinicia o PC sozinho.
