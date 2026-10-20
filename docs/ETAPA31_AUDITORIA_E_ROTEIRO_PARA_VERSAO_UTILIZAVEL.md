# Etapa 31 — auditoria de prontidão e roteiro de entrega

**Data:** 2026-10-19  
**Base:** `test/offline-complete-recovery-e2e-20261019`, commit `fead2b8`  
**Natureza:** revisão de prontidão e critérios de aceite, **sem** novas operações em disco, PR, merge ou execução de testes.

## Resumo executivo

O aplicativo **não está pronto para formatar computadores de usuários**. As
etapas 24–30 demonstraram com sucesso o fluxo de backup de duas fontes,
duas cópias, reabertura por manifestos e recuperação seletiva **em diretórios
fictícios temporários**. Isso é um avanço do motor de preservação, não uma
certificação de segurança de execução real.

Para os módulos dessas sete etapas, há **62 testes direcionados reportados
como aprovados**: Etapa 24 (9, informação enviada pelo usuário no chat),
25 (10), 26 (10), 27 (7, após correção), 28 (11), 29 (8), 30 (7).
Os relatórios das etapas 25–30 estão registrados nos comentários do PR #54.
Esses números não correspondem à suíte inteira do projeto, não medem
cobertura de código e **não indicam quantos testes faltam** para lançamento.

## Situação revisada por capacidade

| Capacidade | Evidência | Situação para usuários reais |
| --- | --- | --- |
| Inventário e escolhas individuais de arquivos | Planos e prévias implementados; testes anteriores | Requer integração e validação real de várias unidades |
| Cópias simultâneas de múltiplas origens | `multi_source_fixture_runner.py`: sandbox obrigatório e flags negativas | **Bloqueado** fora da pasta de testes |
| Duas cópias e verificação SHA-256 | `run_multi_source_fixture_backups`; testes de fixture | **Não comprova** mídias fisicamente independentes |
| Reabertura depois de perder o inventário original | `multi_source_offline_import.py`, Etapa 28 | Implementado **somente em fixture** |
| Central de seleção e restauração | `multi_source_offline_reopen_ui.py`, `multi_source_recovery_center_ui.py`, Etapas 29–30 | Interface demonstrativa; não ligada ao fluxo real do app |
| Identificação de volumes e extents físicos | `multi_source_targets.py`, `multi_source_live_inventory.py` | Apenas prévia/conferência; não autoriza produção |
| Resiliência a swaps de arquivo/pasta durante cópia | `backup_destination_guard.py` e proteções por handle | Proteções parciais; troca privilegiada concorrente ainda é ameaça |
| Restauração de programas, jogos e dados de navegadores | Módulos existentes no aplicativo | Validação integrada após reinstalação real **pendente** |
| Reinstalação do Windows e EFI própria no SSD escolhido | Não demonstrada no ensaio | **Não autorizada e não validada** |
| Otimização de Windows, hardware e BIOS | Planejada após fechamento da preservação | Fora do escopo das etapas 24–30 |

### Bloqueadores de segurança — prioridade P0

1. **Inventário real atualizado e identidade de dispositivos.** Antes de
   qualquer cópia multidisco de produção, identificar os volumes e extents
   físicos, discos compartilhados, remapeamentos, dispositivos ausentes e
   espaço disponível. Incongruência ou falha do coletor deve bloquear o
   plano; nenhum mapeamento por letra de unidade pode ser interpretado como
   prova de disco fisicamente distinto.
2. **Executor de backup multidisco protegido.** O atual runner é
   propositalmente limitado a `test_root`. Uma implementação de produção
   precisará escopo de origem/destino explícito, confirmação humana, isolamento
   de caminhos, proteção contra reparse/junction, handles e ancestralidade
   verificados, checkpoint e cancelamento; nenhuma formatação implícita.
   Revisão específica de races TOCTOU do Windows permanece necessária.
3. **Recuperação persistente e segura no aplicativo principal.** A interface
   fictícia precisa ser substituída ou integrada por fluxo que use backups
   reais, **sem confiar somente na presença de SHA-256 ou em manifestos
   não autenticados**, protegendo contra adulteração, colisões, diretórios
   de sistema, arquivos sobrepostos e recuperação parcial. Aplicativos e
   saves devem receber tratamentos específicos; copiar arquivos não equivale
   a reinstalar programas.
4. **Preparação de reinstalação do Windows com barreiras independentes.**
   Diagnóstico de EFI/BCD, validação de mídia e alvo físico, prévia completa,
   confirmação inequívoca, opções de retorno e testes controlados. A existência
   de backups SHA-256 não pode liberar por si só instalação, exclusão ou
   formatação. Operações destrutivas não devem ser testadas no PC pessoal.

### Qualidade e experiência — prioridade P1

5. **Escala e recuperação de falhas.** Testar conjuntos grandes e
   transferências extensas (ex.: jogos de aproximadamente 120 GiB, inventários
   com dezenas de milhares de arquivos), limitações de memória, disco cheio,
   erros de permissão, mídia desconectada, reinício, retomada, cancelamento
   e interface responsiva. Conferir SHA-256 e os arquivos recuperados.
6. **Preservação de dados específicos.** Validar navegadores, favoritos,
   cofres/credenciais dentro dos limites conhecidos, jogos de launchers
   diversos, saves, bibliotecas, osu! clássico e vínculos entre unidades.
   Nenhuma garantia automática sobre passkeys, sessões ou senhas protegidas
   pelo Windows antigo.
7. **Empacotamento e experiência de primeiro uso.** Preparar instalador
   assinado quando apropriado, permissões mínimas, instruções confiáveis,
   mensagens compreensíveis, relatório de auditoria e testes de aceitação em
   máquinas/discos de laboratório antes de uso geral.

### Otimização — fase posterior (P2)

8. Somente após concluir a preservação, entrega, restauração e segurança da
   reinstalação: inventariar hardware, recomendar ajustes suportados pelo
   Windows e drivers, e distinguir alterações reversíveis de ajustes
   potencialmente perigosos em BIOS/firmware. **Não** aplicar alterações
   agressivas e irreversíveis automaticamente.

## Critério de progresso sem criar testes infinitos

- Não abrir uma nova etapa só para elevar a contagem de testes. Agrupar testes
  de unidade, integração e falha por **capacidade e risco**.
- Marcar um bloco como `validado_em_fixture` apenas após resultados locais
  registrados; não converter isso em `pronto_para_producao`.
- Uma etapa de código deve terminar com evidência repetível e revisão dos
  efeitos sobre usuário; regressões devem se concentrar na área modificada.
- O número de testes **restantes não pode ser definido honestamente agora**:
  depende das funcionalidades que forem implementadas e dos defeitos
  encontrados. Mais testes não são substituto para funcionalidades ausentes.
- A próxima fase de desenvolvimento deve priorizar os **bloqueadores P0**.
  Não habilitar exclusão, formatação, instalação, EFI ou cópia multidisco real
  até esses bloqueadores serem resolvidos e revisados em hardware controlado.

## Guardrails permanecem ativos

`physical_independence_verified=False`, `ready_for_format=False` e
`installation_authorized=False` em todos os resultados experimentais.
Nenhum dado real deve ser formatado; somente ensaios em `TemporaryDirectory`
até que exista uma implementação e um protocolo independente de segurança.

**Conclusão:** a recuperação simulada após reinstalação está funcional nos
cenários verificados, mas falta um trabalho substancial antes da versão
geralmente utilizável. A partir desta auditoria, o desenvolvimento deve ser
orientado por capacidades entregáveis, não pelo número sequencial de testes.
