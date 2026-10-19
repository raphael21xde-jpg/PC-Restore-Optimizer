# Etapa 33 — Conferir origens e destinos pela interface (somente leitura)

O botão **Conferir origens e destinos (somente leitura)** foi adicionado à aba
**Diagnóstico** do aplicativo principal (`app.py`).

## Como utilizar

1. Abrir o aplicativo principal e acessar **Diagnóstico**.
2. Clicar em **Conferir origens e destinos (somente leitura)**.
3. Informar explicitamente as letras das unidades que contêm arquivos
   a preservar e as letras candidatas a receber backup.
   O formulário **não escolhe nem recomenda automaticamente** unidades.
4. Clicar em **Conferir discos (SOMENTE LEITURA)**.
5. Revisar bloqueios, discos lógicos informados, limitações dos extents e
   alertas para origem/destino. A consulta acontece em segundo plano.
6. Fechar sem gravar arquivo nem alterar armazenamento.

O código recusa entradas inválidas, letras duplicadas e qualquer destino
que coincida com uma origem; **não executa consulta ao hardware** nesses
casos. A consulta só começa depois do clique explícito. Dados identificáveis
do inventário completo, como serial de dispositivo ou GUID, **não são
apresentados no resumo**. Erros internos não exibem as saídas brutas do
PowerShell ao usuário.

O diálogo usa `drive_safety_report.inspect_fresh_drive_safety()`,
que consulta metadados atualizados e informa o estado de revisão. Não
identifica com garantia física todos os dispositivos. Mesmo um resultado
`requires_review` **nunca** representa autorização para backup real.

## Verificação local dos cinco testes de interface

```powershell
py -3 scripts\test_reporter.py --pattern "test_drive_safety_ui.py" --publish
```

Revise a prévia sanitizada antes de publicar os resultados no PR #54.
Os testes utilizam Tk e um coletor sintético, não os discos verdadeiros.

## Limites de segurança

- O botão não realiza nenhuma cópia, exclusão, formatação nem instalação
  do Windows.
- O botão não modifica a EFI, o BCD, a ordem de inicialização, as partições
  ou a BIOS.
- A consulta ocorre só quando solicitada e pode demorar até o diagnóstico
  responder; fechar durante uma consulta aguarda seu término em vez de
  cancelar agressivamente a leitura.
- `copy_authorized`, `physical_independence_verified`,
  `ready_for_format` e `installation_authorized` continuam **False**.
- Storage Spaces, dispositivos virtualizados, RAID, extents ausentes e a
  identidade física exigem verificação independente adicional.

Próximo marco: validação do diagnóstico em hardware de laboratório e
revisão de integração com o inventário real. A aprovação dos testes
sintéticos desta interface não significa autorização de formato ou
reinstalação.
