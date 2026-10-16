# PC Restore & Optimizer v0.6.4 — Preservação Auditável (Prévia)

**NÃO formate nem apague partições nesta versão.** A v0.6.4 é uma prévia de varredura, escolha e planejamento, sem execução de exclusões, instalação do Windows ou mudanças na EFI.

## O que foi corrigido

- O painel **Preservação** consulta as mesmas escolhas que **Meu Computador**.
- Um save confirmado manualmente pode aparecer como vínculo de um jogo instalado em outra unidade (por exemplo, jogo no D:, save no C:).
- Distingue **associação confirmada pelo usuário**, **candidato ainda não confirmado** e **backup efetivamente verificado**. Esta prévia **não comprova que o backup já foi feito**.
- Contadores separados: (1) jogos/aplicativos marcados, (2) pastas/arquivos escolhidos, (3) caminhos do C: que ainda precisam de cópia, (4) candidatos à remoção. Não somar esses grupos como se fossem arquivos únicos.
- Painel **Revisar erros de varredura** agrupa as falhas e itens ignorados por unidade e apresenta motivos/caminhos, com exportação JSON e carregamento em blocos de 200.
- **Importar inventário anterior** em Meu Computador permite abrir `deteccao-detalhada-v063.json` da pasta antiga, sem sobrescrever unidades que já foram examinadas nesta sessão. Um inventário importado é histórico e pode estar desatualizado.
- Conexões entre jogos e saves são apresentadas em uma tabela com indicação explícita do local de instalação quando conhecido, local dos dados e estado da revisão.

## Como executar

1. Extraia o ZIP em uma pasta nova (não extraia dentro de versões anteriores).
2. No Windows, execute `INICIAR.bat`.
3. Para recuperar as decisões da versão anterior, abra **Preservação > Importar escolhas da versão anterior**, escolhendo o arquivo `preferencias-v05.json` que estava na pasta da v0.6.3. Confira o resultado antes de prosseguir.
4. Para não repetir varreduras muito grandes, entre em **Meu Computador > Importar inventário anterior** e escolha `deteccao-detalhada-v063.json` da pasta da v0.6.3, se existir. Os inventários antigos são somente referências: reexamine as unidades que tiverem mudado.
5. Confira um jogo escolhido no D: com saves no C:. Um vínculo manualmente confirmado deve aparecer na **Preservação** e a cópia deve continuar marcada como pendente.
6. Clique em **Revisar erros de varredura**, alterne entre C:, D:, F: e G: e verifique os caminhos afetados. Nenhum erro ou exclusão significa autorização para apagar.
7. Feche e abra o programa e verifique se as escolhas persistiram.

## Avisos importantes

- Marcar **Manter** não cria um backup. Associar um save ao jogo não comprova integridade nem jogabilidade posterior.
- Unidades F: e G: possuem aspectos especiais no computador testado: EFI no SSD de F: e G: em Storage Spaces. Não tente limpar ou reorganizar partições com esta prévia.
- Antes de reinstalar o Windows, ainda será necessário realizar cópias confiáveis dos dados a preservar no C:, validá-las em armazenamento que não será apagado e testar sua recuperação.
- **Não preservar** não significa **Excluir**; decisões pendentes ficam protegidas.
- Códigos e relatórios anteriores são mantidos para compatibilidade e auditoria.

## O que ainda não está implementado

Instalação automática do Windows, mudança da EFI, exclusões seletivas em D:/F:/G: e confirmação final de prontidão para formatação. A próxima etapa é testar cópia e recuperação real dos caminhos escolhidos no C:, com verificação SHA-256 e planejamento do destino.
