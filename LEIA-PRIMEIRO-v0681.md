# PC Restore & Optimizer v0.6.8.1 — Correção da auditoria

Esta atualização corrige o problema em que a aba **Revisar pasta** permanecia indefinidamente em “Consultando entradas imediatas...” devido a uma falha no agendamento do processamento de resultados da interface.

## Teste recomendado
1. Extraia o ZIP em pasta própria, abra `INICIAR.bat` e importe as escolhas anteriores se necessário.
2. Entre em **Preservação > Auditar dados do C:**.
3. Em **Locais de dados**, selecione uma pasta pequena, clique em **Examinar selecionado**, verifique se a aba **Revisar pasta** mostra os itens.
4. Repita com a pasta que travou na versão anterior. Teste **Abrir subpasta**, **Voltar à pasta anterior**, **Próxima página** quando disponível e **Cancelar consulta**.
5. Não execute backup, exclusão, formatação ou alteração de EFI neste teste.

A opção Cancelar interrompe apenas a espera da interface; não interrompe uma chamada de sistema que já esteja bloqueada. O aplicativo mantém a proibição de formatação.
