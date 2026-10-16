# PC Restore & Optimizer v0.6.6 — Backup seletivo e recuperação de teste (PRÉVIA)

## O que mudou

Esta versão integra à aba **Preservação** o primeiro fluxo de backup real para **somente os caminhos marcados para preservar no C:**. Ela reutiliza o motor de cópia e verificação das versões anteriores, mas organiza as etapas em uma janela única:

1. **Analisar arquivos do C:**: percorre apenas os caminhos confirmados no plano, conta arquivos e calcula o total de bytes; não escreve nada.
2. **Escolher pasta para backup**: selecione uma pasta existente em D:, F: ou G:. O programa cria uma subpasta de backup exclusiva dentro dela.
3. **Copiar e verificar SHA-256**: realiza a cópia dos arquivos selecionados e verifica novamente cada arquivo do backup. Um backup parcial/alterado não é aprovado.
4. **Recuperação de TESTE**: escolha **outra pasta existente** em D:, F: ou G:, diferente da pasta do backup; o programa restaura TODOS os arquivos do manifesto em uma nova subpasta de teste e confere os hashes. **Nunca escreve nos caminhos originais do C:**.

Há também **Conferir backup anterior** para abrir e revalidar um `manifest.json` de backup já existente, além de **Exportar relatório**. A verificação e a recuperação podem ser retomadas por uma nova sessão, escolhendo o manifesto anterior, sem repetir a cópia.

## Roteiro de teste recomendado (vídeo único)

1. Extraia o ZIP em pasta nova e execute `INICIAR.bat` (Windows com Python 3).
2. Entre em **Preservação** e use **Importar escolhas da versão anterior** para carregar `preferencias-v05.json` da v0.6.5, caso os jogos ainda não apareçam. Clique em **Atualizar plano** e mostre God of War Ragnarök e Forza Horizon 6 com seus caminhos de saves do C:.
3. Clique em **Backup seletivo e TESTE de recuperação do C: • v0.6.6**.
4. Clique em **1. Analisar arquivos do C:** e mostre **quantidade de arquivos e tamanho**. Em caso de erro, mostre a mensagem: NÃO avance para cópia com análise incompleta.
5. No Explorador, crie duas pastas diferentes, por exemplo `G:\PCRO-Backups-Teste` e `G:\PCRO-Restauracao-Teste` (ou uma pasta em D: para o teste de restauração). Essas pastas devem estar fora do C:.
6. Clique em **2. Escolher pasta para backup** e selecione a primeira pasta criada. Clique em **3. Copiar e verificar SHA-256**, confirme e aguarde o relatório com a quantidade de arquivos verificados.
7. Clique em **4. Recuperação de TESTE (pasta nova)** e selecione a *segunda* pasta. Aguarde a confirmação de recuperação e verificação. **Não selecione o C: para restaurar.**
8. Abra as pastas criadas no Explorador, mostre o `manifest.json`, `VERIFICACAO-PCRO-066.json` e `RESULTADO-TESTE-PCRO-066.json`. Volte à janela, clique em **Exportar relatório** e salve o resultado.
9. Feche e reabra o aplicativo. Escolha **Conferir backup anterior**, abra o `manifest.json` criado e confira se os hashes continuam aprovados. Não é necessário repetir a cópia.

## Limitações e segurança

- Esta versão **não apaga, não formata, não modifica EFI, não reinstala Windows e não coloca saves de volta em C:**. O botão do fluxo legado foi retirado da Preservação para evitar confusão; seus motores permanecem disponíveis nos arquivos do projeto.
- O backup protege **apenas os caminhos selecionados**. Dados ainda desconhecidos, erros de varredura, saves de outros jogos, documentos, perfis de navegadores, senhas, preferências e aplicativos podem continuar sem proteção. Um teste positivo **não libera a formatação**.
- **G: usa Storage Spaces simples e não tem redundância.** Um backup em G: pode ser útil como ensaio, mas não substitui uma segunda cópia fisicamente independente, caso o SSD falhe. Não desconfigure o Storage Spaces.
- Não repita varreduras de centenas de milhares de arquivos só para executar este ensaio. Use as seleções importadas.
- Se um jogo estiver aberto e mudar saves durante a cópia, o aplicativo deve interromper/apontar falha. Feche os jogos antes do teste.
- A análise evita links simbólicos/junções e bloqueia caminhos ausentes. Backups incompletos, com erros ou SHA-256 divergente não são aceitos para recuperação.
- A restauração cria sempre uma subpasta nova e nunca sobrescreve arquivos originais.
- Para recuperar o Windows no futuro, ainda será preciso avaliar integridade de todos os dados escolhidos, dependência da partição EFI do SSD F:, a instalação limpa na unidade física correta e os testes de inicialização.

### Arquivos relevantes

- `selective_recovery.py` — preparação de arquivos, verificação de cópia e ensaio de recuperação.
- `selective_backup_ui.py` — nova janela com execução em segundo plano e cancelamento.
- `tests/test_selective_recovery_v066.py` — casos de cópia/restauração, falhas, links, corrupção e seleções.
- `tests/test_selective_backup_ui_v066.py` — validação da ligação real entre a Preservação e a janela.
