# PC Restore & Optimizer — estado consolidado e marcos

**Consolidação:** 17/10/2026. **Referência:** `main`, após PR #49 (`a91af153101c571793dd3b1a54f741aa30bfd889`).

**Auditoria retrospectiva completa dos 40 ZIPs (15–16/out), evidências e marcos até o GitHub:** [AUDITORIA-HISTORICA-ZIPS-TESTES-E-ESCOPO.md](AUDITORIA-HISTORICA-ZIPS-TESTES-E-ESCOPO.md). Releia antes de propor repetição de testes de backup, integração ou reinstalação.

**Revisão complementar de conversas, screenshots e situação dos MP4s:** [COMPLEMENTO-AUDITORIA-CONVERSAS-CAPTURAS-VIDEOS.md](COMPLEMENTO-AUDITORIA-CONVERSAS-CAPTURAS-VIDEOS.md). **A inspeção integral dos vídeos ainda está pendente**: não apresentar o material como 100% revisto.

> **Documento de continuidade.** Substitui planos improvisados em conversas e evita refazer funcionalidades testadas. Não é certificado de segurança, não é autorização de exclusão, formatação, alteração de EFI ou reinstalação real. O PC do desenvolvedor é **somente o ambiente inicial de testes**; o produto deve atender diferentes computadores Windows.

## 1. Missão do produto (acordada com o autor)

1. Detectar volumes/discos, arquivos, pastas, aplicativos, jogos, saves e vínculos entre unidades, sem assumir letras fixas.
2. Permitir decisões explícitas e granulares: preservar, não copiar, revisar. **Não copiar nunca significa apagar.** Não examinar outros volumes implicitamente.
3. Preparar backup apenas dos dados que precisam de cópia, verificar SHA-256 e comprovar restauração. Preservar no lugar unidades que não serão alteradas.
4. Guiar a reinstalação do Windows **no disco escolhido pelo usuário**, com identificação física inequívoca, proteção de EFI e dependências de boot, confirmação separada e recuperação planejada.
5. Recuperar dados e orientar reinstalação/configuração de programas, jogos, navegadores e saves sem prometer restauração universal de software, senhas, passkeys ou sessões.
6. Depois, evoluir otimização segura de Windows, aplicativos e hardware, com medições, reversibilidade e autorização para mudanças relevantes.

**Não confundir:** o projeto futuro pode preparar/realizar a reinstalação, mas a versão atual ainda **não formata e não reinstala Windows**. Não iniciar desenvolvimento de operações destrutivas enquanto a segurança não estiver comprovada em ambiente descartável.

## 2. Linha do tempo recuperada

| Data | Entregas/evidências relevantes |
| --- | --- |
| 15/out | Inventário inicial v0.2/v0.3; seleção individual e planejamento de backup por unidade; testes com escolhas de jogos/pastas; começo do fluxo de restauração. |
| 16/out | Evolução v0.6.x: descoberta por disco, preservação, saves e vínculos, navegadores, backup seletivo, auditoria C:/EFI v0.6.9 e relatórios reais; criação da base v0.7.0-dev. |
| 16–17/out | GitHub PRs #7–#26: inventário GUID, Storage Spaces, topologia física e boot/BCD, diagnóstico EFI, segurança do destino, múltiplos destinos e pré-checagens. |
| 17/out | PRs #27–#36: autotestes #25–#43 (SHA-256, corrupção, interrupção, retomada, 2 GiB, 2.048 arquivos, inventário e restauração). |
| 17/out | PRs #37–#45: paginação #44–#46, índice SQLite, marcação granular de arquivos/pastas, exportação/importação de decisões, seleção de unidades do inventário. |
| 17/out | PRs #42–#43: CI econômico, Windows rápido no PR e suíte pesada somente sob demanda/tag. PRs #46–#48: ajustes de Tk/SQLite, PowerShell 5.1 e symlinks em Windows. |
| 17/out | PR #49: retirar marcação antiga na própria Preservação, encaminhamento à revisão/histórico; **teste manual de interface:** 1 arquivo de 34 B, backup e restauração reportados como concluídos. Este último é teste de fluxo visual, **não** de escala. |

Os números de PR, os commits e os arquivos relevantes estão no histórico GitHub; os relatórios JSON enviados durante as conversas são evidências adicionais, **não reexecuções exigidas**.

## 3. O que já existe e NÃO será refeito do zero

| Subsistema | Código ou prova existente | Situação real |
| --- | --- | --- |
| Descoberta/inventário | `volume_inventory.py`, `deep_discovery.py`, `inventory_paged.py`, `inventory_index.py`, `file_index_ui.py` | Funcionalidades implementadas e testadas; SQLite pesquisável com **mais de 1 milhão** de entradas no ambiente de desenvolvimento. Cobertura total de qualquer disco **não garantida** quando existem erros, reparse points e volume sem letra. |
| Seleções e vínculos | `unified_selection.py`, `index_choices_bridge.py`, `discovery_groups.py`, `game_links.py`, `game_saves.py` | Preservar/não copiar, pasta com exceções, saves relacionados, importação de escolhas confirmada. Ainda há superfícies de seleção/planejamento separadas e cobertura não universal. |
| Backup | `backup_core.py`, `transfer_engine.py`, `selective_recovery.py`, `selective_backup_ui.py` | Motor funcional; SHA-256, checkpoints, cancelamento, recuperação de falhas, limites de memória. **Não reimplementar nem repetir automaticamente cargas**. |
| Recuperação | `backup_features.py`, `restore_ui.py`, `app_recovery.py`, `recovery_kit.py` | Restauração seletiva em pasta isolada, verificação e histórico; reinstalar softwares/associar saves no ambiente pós-Windows ainda requer revisão. |
| Navegadores | `browser_vault.py`, `browser_recovery.py`, telas próprias | Testes anteriores de cofre/restauração; limitações explícitas para credenciais do Windows, passkeys, cookies e sessões. |
| Topologia física/boot | `volume_extents.py`, `spaces_membership.py`, `boot_dependency.py`, `firmware_order_evidence.py`, `storage_safety.py` e diagnósticos correlatos | Análises **somente leitura** implementadas; não provam EFI independente nem autorizam formatação. |
| Otimização | `optimization_engine.py`, `optimization_ui.py`, monitores/diagnósticos | Código pré-existente; fase de fechamento do produto fica depois da preservação/reinstalação segura. |

### Evidências históricas que NÃO devem ser solicitadas novamente sem regressão justificada

- O usuário reportou um backup prático com **22.611 arquivos** e execução/restauração seletiva; não inferir que isso valida todos os perfis/discos ou uma instalação limpa.
- `resultado-autoteste35.json`: **2 GiB (2.147.483.648 B)** sintéticos copiados/restaurados com SHA-256 aprovado, fonte preservada, pico RSS abaixo do limite; tempos observados no SO com cache, não benchmark universal. Não equivale a backup externo independente.
- `resultado-autoteste38.json`: **2.048 arquivos** fictícios, operação e restauração aprovadas.
- Relatórios `resultado-autoteste25.json` a `43.json`: integridade, arquivos ausentes, corrupção, retomada, interrupção, arquivos pequenos, limites de seleção, inventário e relatórios; salvos em conversas anteriores.
- Testes Windows já relatados para saves de jogos, cofre/recuperação de navegadores, restauração e transferência, índice SQLite, GUI e backup/resgate. Alguns testes usam `skip` legítimo para symlink sem privilégio; **não** contar skip como erro nem como cobertura testada.
- Índice real **superior a um milhão de arquivos**: usuário pesquisou `osu`, registrou preservar/não copiar e exportou `escolhas-inventario-pcro.json`. O relatório exportado não contém cópia nem prova de integridade.

## 4. Impedimentos reais registrados na auditoria 0.6.9

**Fonte:** `auditoria-inteligente-c-efi-v069.json` de 16/out. É um retrato histórico, não diagnóstico atualizado automaticamente.

- **22** locais candidatos inspecionados; **19** exigiam revisão. **5 caminhos do C:** estavam selecionados, mas a auditoria não tinha manifesto de backup/restauração verificado para esses caminhos. O teste posterior de 34 bytes com arquivo fictício **não resolve essa pendência**.
- Os cinco caminhos relacionavam-se a saves/configurações de **God of War Ragnarök, Forza Horizon, osu! (Songs/Skins) e A Plague Tale**; não copiar lista fixa para outros usuários.
- A auditoria registrou `scan_c.status=SEM INVENTÁRIO` naquela sessão; contadores de erros foram 0 por **ausência de inventário carregado**, não por cobertura total do C:. Um inventário mais recente pode existir no SQLite, mas precisa ser explicitamente referenciado como evidência para essa auditoria.
- **Windows no disco físico 2; volume marcado como Sistema no disco físico 1**. Status `SISTEMA EM OUTRO DISCO`; boot independente no SSD do Windows **não testado**. Cuidado redobrado com o disco dinâmico F: e o pool Storage Spaces G: (Simple, sem redundância), e com `Disco M0 Faltando` relatado no plano anterior.
- `ready_for_format=false`, `installation_authorized=false`, `deletions_authorized=false`. Não realizar formatação de verdade para 'experimentar'.

## 5. Bloqueios de produto, em ordem de execução

### Marco A — Fechar preservação com evidência real, SEM novo motor

**Próximo desenvolvimento.** **Completar e conectar a auditoria já implementada em `audit_v069.py`, `audit_v068.py` e `completeness_audit_ui_v068.py`** às escolhas atuais, ao índice SQLite existente, aos manifestos verificados e às evidências de restauração. O resultado pode aparecer em um painel de prontidão, **mas não desenvolver outra auditoria nem outro motor do zero**. Para cada fonte escolhida, mostrar separadamente:

- **escolhido / precisa cópia / não precisa cópia (preservar no volume intacto);**
- **encontrado hoje / inventariado com lacunas / origem não conferida;**
- **consta no manifesto verificado / cobertura parcial / sem prova;**
- **restauração de ensaio comprovada / não comprovada**, com referência ao manifesto e ao teste;
- localização da unidade de origem e destino; relação com jogo/app/save; escolhas pendentes ou contraditórias.

Não declarar 'protegido' só porque o backup de **outro arquivo** foi aprovado. Não misturar antigo inventário SQLite, prévia, conteúdo de manifesto e arquivos restaurados como se fossem a mesma evidência. Não fazer varredura de conteúdo, backup ou cópias implícitas apenas para desenhar o painel.

**Critério de aceite:** o usuário consegue abrir o app e ver exatamente **o que ainda precisa ser preservado e por quê**, usando dados já existentes; caminhos sem evidência continuam pendentes; nada é formatado. Cobrir o caso real de dependência jogo D:/save C: e osu! clássico, respeitando escolhas manuais.

### Marco B — Prontidão física da reinstalação, somente leitura

Integrar ao painel: seleção de SSD de instalação por modelo, número e GUID (não apenas letra), volumes/partições relevantes, EFI/BCD, vínculo de inicialização entre discos, Storage Spaces, volumes dinâmicos e erros de detecção. Reusar rotinas já existentes; apresentar bloqueios corretos.

**Critério de aceite:** no caso real com Sistema no disco 1 e Windows no disco 2, **exibir bloqueio para alterar o disco** até haver plano e ensaio controlado. Não inferir boot autônomo de metadados.

### Marco C — Preparação guiada e ensaio em ambiente descartável

Preparar mídia oficial do Windows, mapa explícito do SSD-alvo e passos para instalação limpa, com ensaio/validação de EFI própria em VM ou equipamento descartável; recuperar manifestos e arquivos sem escrever por cima dos dados de produção. **Não criar formatação ou comandos destrutivos reais antes de cumprir os requisitos de segurança e testar em ambiente controlado.**

### Marco D — Recuperação completa e otimização

Guiar reinstalação de apps, Steam, osu! clássico, saves e perfis de navegadores; registrar quais itens são arquivos recuperados, quais exigem instalador/login/sincronização. Depois, avançar para otimização segura, monitoramento, BIOS/UEFI apenas com riscos e procedimentos reversíveis comprovados.

## 6. Disciplina de desenvolvimento a partir de agora

1. **Antes de criar código:** procurar função e teste existentes no `main`, consultar este arquivo e registros anexos. Reusar, integrar, corrigir — não reescrever backup, scanner e restorer.
2. **Uma entrega funcional por PR:** dizer qual bloqueio resolve, quais telas foram integradas, qual evidência melhora e qual teste focal demonstra o resultado.
3. **Validação proporcional:** teste de sintaxe e unidade afetada primeiro; Windows UI apenas quando a interface mudar; suíte completa somente em alteração relevante/release. **Não repetir 2 GiB, 22 mil arquivos ou inventário de 1 milhão** sem regressão específica.
4. **CI econômico:** `docs/PROTOCOLO-GITHUB-ACTIONS.md`. Minutos/custo sob controle; jobs GitHub Actions recentemente falham sem iniciar etapas (`steps=null`), então não afirmar CI 'aprovado'. Preferir validação local e explicar restrições.
5. **Entrega por GitHub:** branch/PR e atualização de `main`, sem obrigar download de ZIP. Informar o commit e o que o usuário verá na interface. Não instruir a procurar controle que não exista na `main`.
6. **Nunca misturar:** código implementado, teste automatizado, teste manual real, prova de cópia específica, prova de EFI e produto final. Cada categoria tem seu próprio estado.
7. **Dados reais são conservados:** evitar operações que alterem sistemas de arquivos existentes, estado do boot e discos. Seleção `Não copiar` e inventário de cobertura parcial jamais significam autorização de apagar.
8. **Continuidade:** toda conversa seguinte deve tomar este arquivo e a situação real de `main` como ponto de partida, atualizar os marcos conforme resultados, **não recomeçar o planejamento**.

## 7. Ponto de retomada inequívoco

**Próxima tarefa de código: MARCO A, painel de lacunas e evidências de preservação.** Motor de backup e restauração permanecem preservados. Não iniciar com novo backup fictício, testes de throughput ou redesign genérico. O objetivo é responder: **'Se eu formatasse o disco escolhido hoje, que informações ainda não tenho prova de que conseguiria recuperar?'**

**Estado final de 17/10:** backend e testes históricos significativos; interface básica seleção → backup → recuperação confirmada manualmente; auditoria de preservação global incompleta; EFI independente não comprovada; reinstalação real não implementada nem autorizada.
