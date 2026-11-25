# PC Restore & Optimizer

Programa para Windows que ajuda a **guardar uma cópia conferida** dos seus arquivos antes de
reinstalar o Windows, a **trazer tudo de volta** depois e a deixar o PC mais rápido com ajustes
seguros, que podem ser desfeitos.

O app foi feito para funcionar em qualquer PC com Windows 10 ou 11: computador fraco ou topo de
linha, de qualquer marca, com um disco ou com vários. Ele não exige nenhuma letra de unidade
específica; você escolhe de onde copiar e para onde copiar. Ele ainda não foi certificado em
muitos PCs diferentes, e o `.exe` ainda está sendo validado.

**O app nunca formata e não apaga os seus arquivos.** Deixar um arquivo de fora da cópia não quer
dizer apagar esse arquivo. Mas atenção: o que você não copiar do disco do Windows não entra no
backup e se perde quando o instalador formatar o disco do Windows. A reinstalação do Windows é
**guiada**: o app prepara e explica cada passo, mas quem formata é o instalador oficial da
Microsoft, operado por você.

Onde o app grava (veja também "Onde o app guarda as suas informações", mais abaixo):
- o backup, no disco ou na pasta que você escolher como destino;
- a pasta de dados do próprio app, `%LOCALAPPDATA%\PC-Restore-Optimizer\`;
- quando você restaura um backup: uma pasta nova dentro da pasta que você escolher (restauração,
  recuperação isolada, restauração de conferência do navegador numa pasta `CONFERIR-...` e
  teste de restauração);
- quando você abre os dados do navegador de um backup (extrair os dados ou gerar o HTML de
  favoritos): na pasta que você escolher;
- relatórios, planos e listas que você pede para salvar: no lugar que você escolher;
- quando você usa a Otimização e confirma um ajuste: configurações do Windows (registro), plano de
  energia e ponto de restauração; os ajustes ficam registrados para o Desfazer; o ponto de
  restauração é uma garantia extra;
- quando você usa "Colocar no lugar original" depois de formatar: as pastas de onde os arquivos
  vieram; se lá já houver um arquivo diferente com o mesmo nome, ele não é apagado, é renomeado
  para `<nome>.antes-pcro-AAAAMMDD`;
- os autotestes do app (os botões de teste): pastas temporárias do Windows, criadas por eles com
  arquivos inventados e apagadas no fim;
- quando você pede para reinstalar programas pelo winget: o próprio winget instala esses
  programas.

**Como usar o app:** veja o [manual curto em português](docs/MANUAL.md). Atenção: o manual ainda
descreve o jeito de abrir pelo Python (instalar o Python e abrir o `INICIAR.bat`); a parte do
`.exe` ainda vai entrar nele.

## Do que o PC precisa
- **Windows 10 ou Windows 11:** é para esses que o app foi feito. O Windows 7, 8 e 8.1 não são
  suportados pela base do app (Python 3.13, que só suporta Windows 10 ou mais novo).
- **Windows de 64 bits:** a confirmar na validação.
- **Espaço livre para o próprio app:** a confirmar na validação.
- **Memória (RAM) mínima:** a confirmar na validação.
- **Para o backup:** um disco ou pendrive com espaço livre para a cópia, que **não** seja o disco
  que você vai formatar. O app mostra o tamanho da cópia antes de começar.
- Não precisa instalar o Python nem outro programa para usar o `.exe`.
- **Administrador só quando pedido:** abra o app do jeito normal, sem administrador. Backup,
  restauração e diagnóstico funcionam assim, e o app recusa restaurar quando está aberto como
  administrador. Administrador só é preciso para aplicar ajustes da Otimização, e o app nunca
  pede isso sozinho.

## Como baixar e instalar
A **primeira versão para baixar ainda não foi publicada**; ela vem em breve. Quando sair, ela vai
aparecer na página de **Versões** (em inglês, **Releases**) do projeto no GitHub, e o link será
colocado aqui.

Quando a versão estiver lá:
1. Abra a página de Versões (Releases) e baixe o arquivo `.zip` do PC Restore & Optimizer.
2. Antes de abrir, confira se o arquivo chegou inteiro e sem alteração (veja a seção
   "Como conferir o SHA-256 do .zip", logo abaixo).
3. Clique com o botão direito no `.zip`, escolha **Extrair tudo...** e indique uma pasta sua.
4. Abra a pasta extraída e dê dois cliques em `PCRestoreOptimizer.exe`.

Não há instalador: o app roda direto da pasta extraída. Para tirar o app do PC, apague essa
pasta. Os seus backups ficam onde você escolheu e não são apagados junto. A pasta de dados do app
(`%LOCALAPPDATA%\PC-Restore-Optimizer\`) também **continua no PC**; veja o que ela guarda em
"Onde o app guarda as suas informações".

**Se você vai formatar o disco do Windows:** a pasta do app e a pasta de dados do app que estão
nesse disco somem junto. Para usar o app depois da formatação, guarde o `.zip` (ou a pasta
extraída) num disco ou pendrive que não vai ser formatado.

## Como conferir o SHA-256 do .zip
O SHA-256 é uma "impressão digital" do arquivo: um código de 64 letras e números. Se um único
pedaço do `.zip` mudar (download cortado ou arquivo trocado por outra pessoa), o código muda.
Na página da Release vai aparecer o código certo de cada `.zip`.

1. Abra a pasta onde o `.zip` foi salvo (normalmente "Downloads").
2. Abra o PowerShell já dentro dessa pasta:
   - no Windows 11: clique com o botão direito num espaço vazio da pasta e escolha
     **Abrir no Terminal**;
   - no Windows 10: segure **Shift**, clique com o botão direito num espaço vazio da pasta e
     escolha **Abrir janela do PowerShell aqui**;
   - ou abra o PowerShell e digite `cd $HOME\Downloads` (troque `Downloads` pela pasta onde
     está o `.zip`).
3. Rode **um** destes comandos, trocando o nome pelo nome exato do arquivo baixado:

   Com o PowerShell:
   ```powershell
   Get-FileHash -Algorithm SHA256 .\PCRestoreOptimizer.zip
   ```

   Ou com o `certutil` (já vem no Windows):
   ```powershell
   certutil -hashfile .\PCRestoreOptimizer.zip SHA256
   ```
4. Compare o código que apareceu com o valor publicado na Release. Não importa se as letras
   estão em maiúsculas ou minúsculas; todo o resto tem de ser igual.
   - **Igual:** o arquivo está certo e pode ser extraído.
   - **Diferente:** não abra. Apague esse `.zip` e baixe de novo pela página de Versões
     (Releases). Se continuar diferente, não use o arquivo e avise no projeto.

## Aviso: o programa não tem assinatura digital
O `PCRestoreOptimizer.exe` **não é assinado** (a assinatura digital é um certificado pago que
diz ao Windows quem fez o programa). Por isso o Windows pode avisar ou bloquear na primeira vez:

- **SmartScreen** (tela azul "O Windows protegeu o computador"): só continue se você baixou o
  `.zip` da página de Versões (Releases) do projeto **e** o SHA-256 bateu. Aí clique em
  **Mais informações** e depois em **Executar assim mesmo**. Se o código não bateu, clique em
  **Não executar**.
- **Controle Inteligente de Aplicativos** (Smart App Control, no Windows 11): ele pode bloquear o
  `.exe` sem dar a opção de abrir. **Não desligue** essa proteção para usar o app: em muitas
  versões do Windows 11, depois de desligada, ela só volta reinstalando o Windows. Se isso
  acontecer, por enquanto o app não abre nesse PC.
- **Nunca desligue** o antivírus (Microsoft Defender) nem o Windows Update para abrir o app. O
  próprio app nunca desliga essas proteções.

## Onde o app guarda as suas informações
Quando você abre o `PCRestoreOptimizer.exe`, o app guarda os dados dele em
`%LOCALAPPDATA%\PC-Restore-Optimizer\`, no seu PC:
- as suas preferências e escolhas do que copiar;
- o diário da otimização (o que foi mudado, para poder desfazer);
- o inventário detalhado, que tem **nomes de arquivos e pastas** do seu PC;
- o progresso do primeiro uso e do "Depois de formatar";
- os registros das reinstalações de programas pelo winget.

Essa pasta **continua no PC** mesmo se você apagar a pasta do app. Se quiser tirar tudo, apague
também essa pasta (ela não tem os seus backups). Os backups ficam no lugar que você escolheu como
destino.

---

## Para quem desenvolve

> **Ponto de retomada do desenvolvimento (17/10/2026):** [estado consolidado, testes já aprovados e próximos marcos](docs/ESTADO-DO-PROJETO-E-PROXIMOS-MARCOS.md). Consulte esse documento antes de criar novos testes ou repetir etapas. O próximo marco é integrar evidências de cobertura, backup e restauração por caminho, não reconstruir o motor.

Base histórica v0.6.9, preservada a partir do arquivo disponibilizado pelo autor. **Não é a versão v0.8.1.** Não executar em produção operações de disco, instalação ou restauração sem testes.

Como gerar o `.exe`: veja [docs/INSTALADOR.md](docs/INSTALADOR.md).

### Objetivo
Ferramenta para computadores Windows de diferentes configurações, com inventário de volumes, seleção explícita de preservação, backup verificável, recuperação, orientação de reinstalação do Windows e otimizações seguras.

### Princípios inegociáveis
- Examinar volumes presentes e permitir seleção de arquivos/pastas/programas/jogos/saves sem apagamentos implícitos.
- Não confundir 'não copiar' com 'apagar'. Nenhuma exclusão a partir de inventário/seleção.
- Detectar dependências entre unidades e preservar a seleção do usuário.
- Verificação de integridade SHA-256 e recuperação testável; registrar erros e progresso.
- Operações destrutivas exigem etapa independente de confirmação e auditoria; desabilitadas por padrão.
- Sem garantia de reinstalação automática de softwares licenciados, passkeys, credenciais ou programas sem instaladores.

### Estado
Código Python e testes históricos importados da v0.6.9; não certificados em hardware real. As funcionalidades descritas em `docs/ESPECIFICACAO.md` são requisitos de produto, **não** alegações de implementação.

### Executar e testar no Windows
Inspecione `requirements.txt` antes de instalar dependências. Crie um ambiente virtual e execute `python -m unittest discover -s tests` no ambiente apropriado. Confira também `INICIAR.bat` antes de executar o aplicativo. Nunca aponte os primeiros testes para dados únicos ou para o disco do Windows.
