# Manual curto do PC Restore & Optimizer

Este manual explica, em poucas palavras, como usar o app. Os nomes entre aspas são
exatamente os nomes dos menus, abas e botões que aparecem na tela (ou do Windows).

## O que o app faz

O PC Restore & Optimizer ajuda você a trocar de Windows sem perder nada e, depois,
a deixar o computador mais rápido com segurança. Ele:

- mostra os discos e o que existe em cada um (só olha, não muda nada);
- deixa você escolher o que guardar: pastas, arquivos, jogos e saves;
- faz um backup conferido do que está no disco do Windows (C:), e cada arquivo copiado
  é conferido com SHA-256; os outros discos ficam onde estão e não são formatados;
- testa se o backup consegue ser restaurado antes de você formatar;
- orienta a reinstalação do Windows e a volta dos seus dados depois;
- mede o computador e aplica ajustes de desempenho, anotando cada um para poder desfazer.

O menu da esquerda tem: "Visão geral", "Meu computador", "Preservação",
"Instalar Windows", "Recuperação", "Depois de formatar", "Central de recuperação",
"Cópia protegida para outro disco", "Otimização", "Diagnóstico" e
"Histórico e relatórios". O item "Cópia protegida para outro disco" é um recurso
protegido, ainda em teste: por enquanto, use o backup normal descrito abaixo.

## Instalar e abrir

1. Instale o Python 3.13 (site oficial python.org). Na instalação, marque a opção que
   coloca o Python no PATH.
2. Copie a pasta do app que você recebeu para o seu PC e abra-a.
3. Dê dois cliques em `INICIAR.bat`. Ele abre o app com o Python instalado.

**Abra do jeito normal (sem administrador) quase sempre.** Backup, restauração e
diagnóstico funcionam assim. O app recusa restaurar arquivos e fazer a cópia para
outro disco quando está aberto como administrador, porque os arquivos ficariam com
permissões erradas e a sua conta normal poderia não conseguir abri-los.

**Só abra como administrador para aplicar ajustes de otimização** (abas
"4  Energia reversível", "8  Ajustes seguros" e "9  Ajustes avançados"). Antes de
mudar algo, o app cria um ponto de restauração do Windows ou usa o que o próprio
app criou nas últimas 24 horas (o Windows só cria um ponto novo a cada 24 horas),
e isso exige administrador. O app nunca pede isso sozinho. Para abrir assim: feche o app, clique
com o botão direito no `INICIAR.bat` (ou no atalho dele), escolha
"Executar como administrador" e entre com a **sua própria conta**.

Nas abas "8  Ajustes seguros" e "9  Ajustes avançados", o app também confere a
conta: se o Windows pedir a senha de outra conta, os ajustes valeriam para aquela
outra conta; por isso, se não for a sua, o app não lê nem muda nada.

Terminou os ajustes? Feche e abra o app de novo do jeito normal para fazer backup ou
restaurar.

## Diagnóstico de discos (só leitura)

No menu, clique em "Diagnóstico".

- "Analisar computador e discos": mostra os discos físicos (com tamanho e modelo),
  as partições, a EFI e outros detalhes. Só lê, não muda nada.
- "Simular destino de backup (somente leitura)": confere se um disco serve para
  receber o backup, sem copiar nada.
- "Conferir origens e destinos (somente leitura)": confere de onde os arquivos vão
  sair e para onde vão.
- "Exportar relatório JSON": salva o resultado num arquivo, se você quiser guardar.

Dica: o disco que vai receber o backup deve ser **outro disco físico**, que não vai
ser formatado. Uma partição no mesmo disco do Windows não protege seus dados.

## Backup

O backup copia só o que você marcar no disco do Windows (C:), que é o disco que vai
ser formatado. Os outros discos ficam onde estão: o app não copia nem formata nada
neles. Os arquivos originais nunca são mexidos: o backup só lê e copia.

1. **Procure o que existe.** Em "Meu computador", marque as unidades e clique em
   "Examinar unidades marcadas". O app lista jogos, aplicativos e arquivos. Ele só
   olha. Na lista, use "Manter selecionados" para guardar ou "Não preservar" para
   deixar de fora.
   - "Não preservar" quer dizer só **não copiar**. O app **nunca apaga** o arquivo do
     seu disco por causa disso.
2. **Revise.** Em "Preservação", confira a lista do que vai ser guardado. O botão
   "Retirar do backup (não apaga)" só tira a marcação de um item.
3. **Faça o backup.** Ainda em "Preservação", clique em
   "Próximo: revisar backup dos arquivos escolhidos →". Nessa tela, clique em
   "Escolher destino" e escolha uma pasta no outro disco. Clique em
   "1. Recalcular plano e espaço" para ver se cabe. O botão
   "2. Iniciar backup (confirmação dupla)" só liga depois desse passo 1. Clique nele:
   o app mostra o resumo (quantos arquivos, tamanho e destino) e pergunta se pode
   começar.
4. **Caiu a energia ou o PC travou?** Abra a mesma tela, com as mesmas escolhas de
   antes, e clique primeiro em "1. Recalcular plano e espaço". Depois clique em
   "Retomar backup interrompido" e escolha o arquivo `manifest.json` do backup que
   parou. O app continua esse backup e confere com SHA-256 o que já tinha sido copiado.

**Navegadores.** A tela de backup do navegador ainda não está ligada ao menu do app.
Antes de formatar, confira se a sincronização da conta do navegador está ligada. Se
você exportar as senhas pelo próprio navegador para um arquivo CSV, lembre: ele é
texto legível. Nunca o envie por chat ou e-mail e não o deixe desprotegido. Depois
de importar as senhas no navegador novo, apague esse CSV pelo Explorador de Arquivos
(e esvazie a Lixeira).

## Testar e restaurar

**Antes de formatar, teste o backup.** Um backup que nunca foi testado pode esconder
um problema.

1. No menu, clique em "Histórico e relatórios". A lista mostra os backups da pasta
   escolhida em "Escolher destino" (na tela de revisão do backup); se a lista estiver
   vazia, escolha essa pasta lá e clique em "Atualizar histórico". Escolha o backup e
   clique em "Testar restauração de arquivo pequeno". O app traz um arquivo de volta
   para uma pasta nova de conferência.
2. Com o backup ainda selecionado em "Histórico e relatórios", vá no menu
   "Recuperação" e clique em "5. Conferir TODO o backup (SHA-256)". O app confere
   cada arquivo desse backup. Pode demorar; se precisar, use "Cancelar auditoria".
   No fim, você pode clicar em "Salvar relatório de auditoria".
3. Navegador (no Windows novo): em "Depois de formatar", na etapa
   "Navegador e senhas", o botão "Abrir" abre o assistente "Restaurar navegador".
   Hoje ele tem dois limites: só aceita um cofre do app (arquivo `.pcbrowser` ou
   `.opgx`) ou uma pasta `CONFERIR-NAVEGADOR`, que só são criados por uma tela que
   ainda não está ligada ao menu; e só orienta a importação no Opera e no Opera GX.
   Para os outros navegadores, ou se você não tem esse cofre, entre na conta do
   navegador novo e ligue a sincronização, ou importe o CSV de senhas pelo próprio
   navegador e depois apague o CSV. Cookies, sessões abertas (logins) e passkeys
   **não voltam**: você vai precisar entrar nas contas de novo.

Para restaurar de verdade, em "Histórico e relatórios" escolha o backup e clique em
"Escolher arquivo para testar". Na janela que abre, marque os arquivos, clique em
"Restaurar arquivos marcados para pasta nova" e escolha onde criar a pasta. Os
arquivos sempre vão primeiro para uma pasta nova (`TESTE-RESTAURACAO`).

Depois, se quiser, use "Colocar no lugar original" e escolha essa pasta de uma
restauração já concluída. O app mostra antes uma prévia: se já existe lá um arquivo
diferente, ele guarda o antigo com o nome terminado em `.antes-pcro-DATA` e coloca o
novo. Nada é apagado. Arquivos de Program Files e ProgramData, por padrão, não são
colocados: não marque a opção
"Incluir arquivos de Program Files/ProgramData ao colocar no lugar original", porque
eles precisam de administrador e o app recusa restaurar aberto como administrador.

## Reinstalação guiada

O app **não formata e não instala o Windows**. Quem formata e instala é o
**instalador oficial da Microsoft**, operado por você. O app prepara e orienta.

**Antes de formatar** ("Instalar Windows"):

- siga a lista de preparação da tela: backup do C: conferido, mídia oficial do
  Windows, edição e ativação, drivers, disco físico certo e plano de recuperação;
- os botões "Revisar preservação", "Diagnóstico dos discos" e
  "Recuperação depois do Windows" levam às telas de cada etapa;
- na tela "Recuperação", clique em "1. Exportar plano para usar depois" e guarde o
  arquivo no disco do backup. No Windows novo, na mesma tela, clique em
  "2. Abrir plano após reinstalar" e escolha esse arquivo: o app mostra o resumo do
  plano (não instala nada nem muda arquivos).

**Cuidado na hora de instalar.** O instalador apaga as partições que você excluir ou
formatar naquele disco, sem volta.

- **Regra principal:** desconecte o disco do backup antes de instalar, com o PC
  desligado e fora da tomada, e reconecte só depois. Se for um disco interno, é
  preciso abrir o gabinete; se você não souber fazer isso, peça ajuda a alguém que
  saiba. Ao reconectar, a letra do disco pode mudar: confira em
  "Conferir discos e letras" (no "Depois de formatar").
- Antes, em "Analisar computador e discos" (menu "Diagnóstico"), ache o disco do
  Windows: é a linha com `Boot=True` e `System=True`. Anote o número desse disco
  (`#0`, `#1`...) e o tamanho dele. O app mostra o tamanho em bytes;
  o instalador mostra *Disco 0*, *Disco 1*... (ou *Unidade 0*) e o tamanho em GB. Para
  comparar, divida os bytes por 1.073.741.824: o resultado é, de forma aproximada, o
  número de GB que o instalador mostra.
- O número do disco no app costuma ser o mesmo do instalador, mas isso não é
  garantido. Confira também o tamanho.
- Na dúvida, cancele a instalação: o que é apagado ali não volta.

**Depois de formatar** ("Depois de formatar"):

1. abra o app no Windows novo e escolha o backup;
2. siga as cinco etapas: "Conferir discos e letras", "Restaurar os arquivos",
   "Reinstalar os programas", "Religar os launchers de jogos" e "Navegador e senhas";
3. em cada etapa use "Abrir", e no fim marque "Feito" ou "Pular".

Se a letra de uma unidade mudou, o app mostra como trocá-la à mão no
"Gerenciamento de Disco". Ele nunca troca letras sozinho. Cuidado: programas e
atalhos que usam a letra antiga param de achar os arquivos até a letra voltar. Para
desfazer, troque de novo para a letra antiga, pelo mesmo caminho.

## Otimização

No menu, clique em "Otimização". As abas são numeradas.

1. **Conheça o PC.** Na aba "1  Diagnóstico", clique em "Analisar este PC". Só lê.
2. **Meça antes.** Deixe abertos só os programas de sempre e clique em
   "Medir ANTES (1 min)". Não use o PC durante a medição.
3. **Aplique os ajustes seguros.** Abra o app como administrador (veja a seção
   Instalar e abrir). Na aba "8  Ajustes seguros", clique em "Ver estado atual"
   e depois em "Aplicar ajustes seguros". O app mostra o que vai mudar, pergunta antes
   e cria um ponto de restauração ou usa o que o próprio app criou nas últimas 24 horas
   (a pergunta diz qual).
4. **Ajustes avançados (opcional).** Na aba "9  Ajustes avançados", cada ajuste é
   aplicado um de cada vez. A pergunta mostra o lado ruim do ajuste e vem com **Não**
   marcado: apertar Enter não aplica nada. Só responda **Sim** se entendeu o aviso.
5. **Meça depois.** Com os mesmos programas abertos, clique em "Medir DEPOIS (1 min)".
   O app compara processador, memória, processos, programas que abrem com o Windows
   e plano de energia.

## Desfazer

Cada ajuste que o app aplica fica anotado na aba "7  Alterações feitas".

- "Desfazer tudo" volta os ajustes anotados, do mais novo ao mais antigo, para como
  estavam antes. Os ajustes que valem só na sua conta e a troca de plano de energia
  se desfazem sem administrador. **Exceção:** os ajustes da aba
  "9  Ajustes avançados" que valem para o computador todo (todas as contas), como o
  agendamento de GPU, só se desfazem com o app aberto como administrador (com a sua
  própria conta), e o desfazer deles só vale depois de reiniciar o computador.
- Se um item não puder ser desfeito, o desfazer **para nesse item**: os mais antigos
  que ele continuam aplicados. Leia a mensagem, resolva (por exemplo, abrindo como
  administrador) e clique em "Desfazer tudo" de novo. **Exceção:** um ajuste cujo valor
  foi apagado fora do app (por exemplo, o agendamento de GPU) é pulado: ele continua na
  lista, e o desfazer segue para os mais antigos.
- "Conferir de novo" lê de novo o estado real do Windows, para confirmar o que está
  aplicado.
- Uma troca de plano de energia feita por uma versão antiga do app se desfaz pelo
  botão "Desfazer alteração antiga", na aba "4  Energia reversível".

Alguns ajustes só valem depois de sair da conta e entrar de novo, ou de reiniciar.
O app avisa quando for assim e nunca reinicia o PC sozinho. Se algo der muito errado,
você também pode usar o ponto de restauração do Windows criado antes da mudança.
Voltar a esse ponto desfaz também o que foi feito depois dele.

## Check-up

- "Analisar este PC" (aba "1  Diagnóstico"): mostra Windows, processador, placa de
  vídeo, memória, discos, placa-mãe e versão da BIOS. Só lê.
- "Check-up de segurança" (também na aba "1  Diagnóstico"): olha o que abre com o Windows,
  as tarefas agendadas, os processos e o Defender, e aponta o que merece atenção, sem mudar,
  encerrar ou tirar nada do lugar. As tarefas do próprio Windows vêm numa linha só; para ver
  cada uma, use o botão "Salvar check-up completo (.txt)", no fim da janela do check-up.

## BIOS e drivers

A aba "6  BIOS e drivers" explica o que pode ser melhorado na BIOS (por exemplo,
perfil de memória XMP/EXPO e Resizable BAR) e o que o app consegue ou não confirmar.

Na aba "1  Diagnóstico", depois de "Analisar este PC", o botão "Ver passo a passo"
mostra como entrar na BIOS do seu tipo de placa, onde procurar cada opção, o que não
mexer (CSM e modo de inicialização, que podem impedir o Windows de abrir), como sair
sem salvar e como voltar a BIOS ao padrão de fábrica se o PC não ligar.

**O app só orienta.** Ele nunca muda a BIOS. Se você decidir mudar algo, quem entra
na BIOS e faz é você, seguindo o manual da sua placa-mãe. Antes de mudar, anote (ou
fotografe) o valor antigo de cada opção. Para voltar tudo ao padrão, a BIOS costuma
ter uma opção com nome parecido com *Load Optimized Defaults*.

## O que o app NUNCA faz

- Nunca formata nem particiona discos.
- Nunca apaga seus arquivos. "Não preservar" só quer dizer não copiar.
- Nunca mexe na EFI nem no BCD (a parte que dá a partida no Windows).
- Nunca instala o Windows: quem instala é o instalador oficial da Microsoft, com você.
- Nunca desliga o Defender nem o Windows Update.
- Nunca faz debloat agressivo (arrancar partes do Windows).
- Nunca muda a BIOS: só mostra o passo a passo.
- Nunca troca letras de unidades sozinho e nunca reinicia o PC sozinho.
