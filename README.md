# PC Restore & Optimizer

Programa para Windows que ajuda a **guardar uma cópia conferida** dos seus arquivos antes de
reinstalar o Windows, a **trazer tudo de volta** depois e a deixar o PC mais rápido com ajustes
seguros, que podem ser desfeitos.

O app funciona em qualquer PC com Windows: computador fraco ou topo de linha, de qualquer marca,
com um disco ou com vários. Ele não exige nenhuma letra de unidade específica; você escolhe de
onde copiar e para onde copiar.

**O app só escreve onde você escolher, nunca formata e nunca apaga os seus arquivos.** Deixar um
arquivo de fora da cópia não quer dizer apagar esse arquivo. A reinstalação do Windows é
**guiada**: o app prepara e explica cada passo, mas quem formata é o instalador oficial da
Microsoft, operado por você.

**Como usar o app:** veja o [manual curto em português](docs/MANUAL.md).

## Do que o PC precisa
- **Windows 10 ou Windows 11.** O Windows 7, 8 e 8.1 não funcionam: a base do app (Python 3.13)
  não aceita essas versões.
- **Windows de 64 bits:** a confirmar na validação.
- **Espaço livre para o próprio app:** a confirmar na validação.
- **Memória (RAM) mínima:** a confirmar na validação.
- **Para o backup:** um disco ou pendrive com espaço livre para a cópia, que **não** seja o disco
  que você vai formatar. O app mostra o tamanho da cópia antes de começar.
- Não precisa instalar o Python nem outro programa para usar o `.exe`.

## Como baixar e instalar
A **primeira versão para baixar ainda não foi publicada**; ela vem em breve. Quando sair, ela vai
aparecer na página de **Versões** (em inglês, **Releases**) do projeto no GitHub, e o link será
colocado aqui.

Quando a versão estiver lá:
1. Abra a página de Versões (Releases) e baixe o arquivo `.zip` do PC Restore & Optimizer.
2. Antes de abrir, confira se o arquivo chegou inteiro e sem alteração (veja a seção
   "Como conferir o SHA-256 do .zip", logo abaixo).
3. Clique com o botão direito no `.zip` e escolha **Extrair tudo...**. Escolha uma pasta sua,
   por exemplo uma pasta "Programas" dentro dos seus Documentos.
4. Abra a pasta extraída e dê dois cliques em `PCRestoreOptimizer.exe`.

Não há instalador: o app roda direto da pasta extraída. Para tirar o app do PC, basta apagar
essa pasta (os seus backups ficam onde você escolheu e não são apagados junto).

## Como conferir o SHA-256 do .zip
O SHA-256 é uma "impressão digital" do arquivo: um código de 64 letras e números. Se um único
pedaço do `.zip` mudar (download cortado ou arquivo trocado por outra pessoa), o código muda.
Na página da Release vai aparecer o código certo de cada `.zip`.

1. Abra a pasta onde o `.zip` foi salvo (normalmente "Downloads").
2. Clique com o botão direito num espaço vazio da pasta e escolha **Abrir no Terminal**
   (ou abra o PowerShell e vá até essa pasta).
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
  versões do Windows 11, depois de desligada, ela só volta reinstalando o Windows. Nesse caso, espere uma versão assinada.
- Nunca desligue o antivírus (Microsoft Defender) nem o Windows Update para abrir o app. O próprio
  app nunca desliga essas proteções.

## Onde o app guarda as suas informações
Quando você abre o `PCRestoreOptimizer.exe`, as preferências e o diário da otimização ficam em
`%LOCALAPPDATA%\PC-Restore-Optimizer\`, só no seu PC. Os backups ficam somente no lugar que você
escolher.

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
