# Complemento da auditoria — conversas, capturas e gravações da fase ZIP

**Data da revisão adicional:** 17/10/2026. **Status: em andamento — NÃO declarar revisão visual completa dos vídeos.** Documento complementar às [40 versões ZIP e relatórios](AUDITORIA-HISTORICA-ZIPS-TESTES-E-ESCOPO.md) e ao [ponto de retomada](ESTADO-DO-PROJETO-E-PROXIMOS-MARCOS.md).

## Princípios de prova

- **Uma versão ZIP com 160 funções `test_*` NÃO demonstra 160 aprovações práticas.** Relatórios e observações de usuário são evidências separadas.
- **Uma captura de falha é prova da falha NAQUELA versão, não prova da falha atual.** A correção deve ser ligada a testes/revisões posteriores; não repetir trabalho por pressupor regressão.
- Os históricos recuperáveis de conversa **não equivalem a transcrições literais de todas as mensagens**. As gravações foram localizadas na Biblioteca, mas até este complemento **não foi executada uma decodificação quadro a quadro**. Não marcar 'vídeo revisado' por existir arquivo MP4 ou pela leitura de screenshots relacionados.
- Nenhuma operação real de formatação, restauração de Windows, EFI ou exclusão foi feita nesta auditoria retrospectiva.

## Recuperação das decisões e testes antigos (fase sem GitHub)

| Versão/período | Evidência obtida de conversas e capturas | Situação e implicação |
| --- | --- | --- |
| v0.1 (15/10) | Primeira execução precisou de ajustes de Python; aplicativo abriu. Objetivo inicial: examinar C:/D:/F:/G:, preservar as escolhas e preparar reinstalação sem excluir automaticamente. | Não é a versão atual e não precisa ser novamente instalada. |
| v0.2 | Inventário exportado; conversas antigas reportam 51 pastas/184 aplicativos; documento `inventario-pc-v02.json` contém metadados dos quatro SSDs. | Primeiro inventário **não** era cópia dos dados. |
| v0.3 | O usuário marcou `A Plague Tale: Requiem` como `Não copiar` e usou itens de `Xbox Games` para ensaiar seleção. Foram citadas seleções de fotos em F:. | Prova do requisito `Não copiar` sem apagar; itens específicos eram exemplos, não regras fixas para todos os PCs. |
| v0.4 (15/10) | Proteção de Opera GX, `INICIAR.bat` e cripto; captura `Captura de tela 2026-10-15 163006.png` mostra perfil Opera GX extraído na pasta `CONFERIR-OperaGX-...`, incluindo `Bookmarks`, `History`, `Sessions`, `Preferences`. | **Recuperação em pasta separada aconteceu**; não equivale a restauração de sessões, senhas ou passkeys num navegador ativo. |
| v0.5/v0.5.1–v0.5.3 | O usuário encontrou jogos e saves, mas diversos locais exibiam `Conferir/Não encontrado`. Caso real: `MRS.cfg` (CS2) no SSD F:; The Witcher 3 exigiu busca melhor. | Vínculos têm **grau de confiança**. Detectar nome parecido não é prova de dados associados. |
| v0.5.4–v0.5.6 | Listas da interface ficaram vazias e precisaram ser corrigidas; cofres de navegadores e preservação unificada foram acrescentados. | Não apagar trabalhos prévios nem confundir ausência de UI com ausência de dados. |
| v0.5.7–v0.5.10 | Otimização, telemetria/PresentMon e diagnóstico de microstutters **já tinham código e cenários testados**. | Otimização não começa do zero após reinstalação: consolidar módulos existentes. |
| v0.5.15 e v0.5.16 (16/10) | Backup real reportado como **22.611 arquivos**, cerca de 2,77 GiB; screenshot `imagem_2026-10-16_093310297.png` registra **`(Não está respondendo)`** na seleção de arquivo para restauração, sobre uma lista imensa de dados do osu! clássico. | Era **falha real de responsividade**, não falha comprovada do SHA-256. V0.5.16–v0.5.19 adicionaram melhorias em segundo plano/paginação; a falha antiga não deve ser apresentada como problema atual sem nova reprodução. |
| v0.5.15 (deteção osu!) | Captura `imagem_2026-10-16_092050115.png` mostra agrupamentos `osu! clássico` (9 locais), `osu! lazer` (3) e `osu! edição a conferir` (6), com caminhos candidatos na NVIDIA, cache WinGet e Downloads. | **Possíveis falsos positivos em associação de jogos/saves**. O painel de prontidão não pode certificar dependências por apenas correspondência textual; associar somente evidência revisada. |
| v0.6.4–v0.6.9 | Auditorias encontraram 637 erros e 189 links ignorados em sessão de varredura; outra sessão sem inventário exibiu 0 erros, mas status `SEM INVENTÁRIO`. V0.6.6 relatório comprova **42 arquivos/22.983.187 B** SHA-256, mas `restore_verified=false` naquele JSON. | Não misturar sessões diferentes nem zerar lacunas de inventário sem nova evidência. |
| v0.6.8 → v0.6.8.1 | Conversa registra demora/travamento ao examinar pastas (4min10s), seguida de correção direcionada da prévia. | Problema de desempenho antigo, não motivo para refazer os testes de backup de grande escala. |
| 16/10, discos | Captura `imagem_2026-10-16_200216899.png` mostra no Gerenciamento de Disco **EFI de 100 MB no Disco 1 (F: dinâmica)**, **C: no Disco 2**, e entrada **Faltando** com 465,74 GiB/estado Falha; screenshot `imagem_2026-10-16_195929288.png` revela volumes sem letra não incluídos em varredura automática. | **Risco crítico de boot cruzado e disco dinâmico**. Essas imagens reforçam o diagnóstico v0.6.9. Nenhuma imagem prova independência de EFI. |
| 17/10, GitHub | PRs #1–#49 ampliaram o código para inventário universal/SQLite, CI econômico, segurança de disco, seleção e navegação. Testes reais de arquivos de prova e 2 GiB passaram em sessões anteriores; o teste final de 34 B foi **só validação de UX**. | Manter resultados e limitações anteriores; não exigir reexecuções sem causa. |

## Gravações localizadas — pendentes de inspeção do conteúdo

**Arquivos MP4 encontrados:** 24 entradas entre 15 e 16/10, algumas duplicadas (`(1)`), como `Gravação de Tela 2026-10-15 154808.mp4`, `Gravação de Tela 2026-10-15 233720.mp4`, `Gravação de Tela 2026-10-16 115448.mp4`, `Gravação de Tela 2026-10-16 123208.mp4`, `Gravação de Tela 2026-10-16 155238.mp4`, `Gravação de Tela 2026-10-16 160052.mp4`, `Gravação de Tela 2026-10-16 165859.mp4` e versões `Video Project 1.mp4`.

**O que foi feito:** identificados por nome, ordem cronológica, tamanho e correspondência com versões ZIP e capturas. Alguns MP4s foram copiados para o ambiente de trabalho técnico. **Ainda não foram decodificados para inspeção integral dos quadros**; não afirmar que foram assistidos. O objetivo de uma revisão de vídeo é inspecionar a sequência inteira de ações, evidenciando transições, travamentos, erros e resultados, sem necessidade de registrar milhares de frames idênticos. A revisão é considerada concluída apenas depois que cada gravação distinta tiver registro de duração, partes inspecionadas, conclusão e eventuais ambiguidades.

## Padrões e lacunas novas que afetam o plano

1. **Segurança do diagnóstico:** diferenciar `detectado`, `possível vínculo`, `revisado`, `arquivo presente`, `backup verificado`, `restauração comprovada`. Falsos positivos de associação de jogo (NVIDIA/WinGet/Downloads para osu!) não devem ser promovidos a `protegido`.
2. **UI responsiva:** não retroceder para seleção de milhares de arquivos em uma caixa de lista que congela; aproveitar `restore_ui.py`, `restore_groups.py`, `restore_jobs.py` e testes existentes. Registrar regressão apenas quando for reproduzida na main.
3. **Boot/EFI:** bloqueio claro de alteração de partições baseado no sistema cruzado entre Discos 1/2 e na unidade dinâmica, sem nenhuma modificação automática.
4. **Prova do backup:** o backup está operacional em múltiplos cenários, mas nenhum resultado sintético demonstra preservação integral dos cinco caminhos reais selecionados no relatório antigo.

## Conclusão desta etapa

**A reconstrução inicial dos ZIPs e testes não encerrava a auditoria visual/conversacional.** Esse complemento identifica novas decisões, screenshots de falha e associações suspeitas. O próximo desenvolvimento deve continuar a integrar a auditoria v0.6.9 à interface; nenhum novo motor de backup. **As gravações e eventuais transcrições integrais continuam com revisão pendente**, e isso deve permanecer explícito, não escondido.
