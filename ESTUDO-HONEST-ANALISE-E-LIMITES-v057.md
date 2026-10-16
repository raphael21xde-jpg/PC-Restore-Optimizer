# Leitura técnica do artigo HONEST — PC Restore & Optimizer v0.5.7

**Fonte**: Barreto et al. (2026), *HONEST: ferramenta automatizada de otimização integrada de Windows e firmware para desempenho de computadores*, Revista Scientia, v.11, n.5, p.325–352, 28 páginas. DOI 10.5281/zenodo.20761339.

**Atenção**: esta implementação se inspira na metodologia do trabalho. NÃO é uma cópia do programa Honest e NÃO possui seu código-fonte, parâmetros privados, integração NVAPI/ADL ou API de alteração de BIOS. Não há comprovação dos ganhos percentuais do artigo para outros computadores.

## O que foi estudado (todas as seções e gráficos)

- **Resumo, introdução e metodologia (pp. 1–5):** programa integrado para otimização de Windows e firmware, procedimento comparativo antes/depois, foco em jogos e segurança.
- **Referencial Windows (pp. 6–7):** Figura 1, relação software/OS/hardware; registro, plano de energia, drivers e serviços, avaliados por benchmarks.
- **Firmware (pp. 7–8):** UEFI/BIOS, SMT/Hyper-Threading, boost, XMP; riscos de temperatura/consumo; servidores citados não são evidência transferível automaticamente a desktops.
- **Produtos e segurança (pp. 9–11):** Intel APO e OMEN AI têm restrições; DevSecOps/SSDLC, backups, rollback, gerenciamento de riscos. Figuras 2–3 ilustram interfaces de firmware.
- **Implementação Honest (pp. 12–15):** C#/.NET, Win32/PInvoke, NVAPI/ADL, registro, serviços e prioridades; interfaces Windows Forms nas Figuras 4–6; backups pré-alteração e restauração. Não há documentação suficiente para reproduzir os parâmetros específicos.
- **Métodos de teste (pp. 16–17):** dois equipamentos Windows 11 23H2; testes DWM, OCAT, CapFrameX; métricas FPS/frametime/1% e 0,2% e três repetições.
- **Resultados (pp. 17–21):** Figuras 7–12 e Tabelas 1–4; DWM *máximo* no desktop de 1269→2994 (+136%) após ajustes combinados; CS2 FPS médio de 385,4→495,1 (+28,4%). São **métricas diferentes**. O notebook não recebeu alterações de firmware por limitações térmicas. Na Tabela 2, o cenário +17% é rotulado “Firmware otimizado”, enquanto uma passagem do texto atribui +17% ao Windows; isso não deve ser interpretado como um isolamento consistente dos efeitos.
- **Limitações e conclusão (pp. 22–24):** apenas dois PCs; notebooks com limite térmico; somente Windows; ganhos não uniformes; demanda estudos com muito mais hardware e validação.
- **Referências e currículos (pp. 24–28):** bibliografia, referências sobre segurança, APIs, benchmarking e firmware; são contexto, não manuais de execução dos mesmos ajustes.

## Matriz de implementação e decisão

| Técnica no HONEST | Situação no PC Restore v0.5.7 | Critério |
| --- | --- | --- |
| Inventário de hardware e Windows | **Implementado**, leitura via CIM/PowerShell | Leitura somente; mostra ausência de dados |
| Identificação de GPU, driver, firmware/placa-mãe/RAM | **Implementado**, inventário | Não interpreta como suporte a OC/BIOS |
| Planos de energia | **Implementado**, listar/escolher um plano existente e desfazer | Dupla confirmação, journal, validação GUID; impacto não garantido |
| Resultados com OCAT/CapFrameX | **Implementado parcialmente**, importar CSV compatível e comparar medianas | 3 corridas por fase, cenário idêntico, cálculo de percentis aproximado |
| DWM FPS | **Não implementado** | Medir máximo DWM isolado não equivale a FPS de jogo; exige coleta adequada |
| XMP/EXPO | **Orientação e leitura parcial da velocidade de RAM** | Requer UEFI, placa/módulos compatíveis e teste de estabilidade |
| Hyper-Threading/SMT/Boost | **Orientação** | Alteração firmware não universal, pode piorar desempenho e aquecer |
| GPU NVAPI/AMD ADL | **Inventário e orientação** | Artigo não publica ajustes completos e APIs dependem de compatibilidade/licença |
| Auto Debloat/desabilitar serviços | **Não aplica** | Sem lista verificável; pode desativar drivers, segurança, atualizações e periféricos |
| Registry `lopagelocklimit` e ajustes de memória | **Não aplica** | Artigo não fornece chave/valor validado para versões modernas |
| FSE e otimização de drivers | **Não aplica** | Necessita perfil específico de jogo e teste; configurar individualmente no driver/jogo |
| Prioridades/afinidade | **Não aplica** | Não é melhoria geral; pode gerar stutter, prejudicar estabilidade e aplicações |
| Ponto de restauração | **Recomendado manualmente** antes de alterações complexas | O Windows pode estar com a Proteção do Sistema desabilitada; não é backup de arquivos |
| Segurança e rollback | **Implementado no ajuste de energia** | Estado anterior registrado em LocalAppData, revertido após confirmação |
| Reinstalação/limpeza e partições | **Não há comandos destrutivos** | F: possui ESP e fotos; G: é Storage Space sem redundância |

### Como funciona o primeiro teste no seu computador

1. Abra **Otimização → Diagnóstico → Analisar este PC**. Não muda nada.
2. Exporte o relatório se desejar; ele pode conter nomes/modelos de hardware, não o conteúdo dos seus arquivos.
3. Faça três execuções reproduzíveis no mesmo mapa/jogo usando OCAT ou CapFrameX. Exporte CSV de **amostras por quadro** contendo `FPS` ou `FrameTime (ms)` e importe como **ANTES**.
4. Se considerar mudar energia, use **Energia reversível → Atualizar**, selecione um plano *já disponível* e confirme. Se preferir, mantenha o plano atual: otimização correta também pode ser **não mudar**.
5. Repita as três execuções **DEPOIS** sob as mesmas condições. Compare medianas; se piorar, **Desfazer**.
6. Confira temperatura/estabilidade em ferramentas específicas e, se decidir revisar BIOS ou drivers, faça isso fora do app e com suporte do fabricante. Não automatizar modificações desconhecidas.

### Condições gerais de qualidade e segurança

- **Nenhuma alteração acontece ao iniciar a aplicação, navegar, diagnosticar ou importar CSV.** Apenas o botão “Aplicar plano selecionado” altera um plano existente, com confirmação explícita.
- O histórico de plano de energia e benchmarks fica em `%LOCALAPPDATA%\PC-Restore-Optimizer\` no Windows para continuar disponível após atualizações de versão.
- **Sem garantia universal de desempenho:** temperatura, carga, clocks, firmware, resfriamento, controles do fabricante e jogo variam. Dados observacionais antes/depois não isolam automaticamente causa e efeito.
- Não troca drivers, desabilita Defender/Windows Update, edita BCD/registro, altera BIOS, aumenta frequência ou voltagem, limpa diretórios e não formata nenhuma unidade.
- Para cambios importantes de sistema, siga a Proteção do Sistema oficial, valide os backups e tenha cópia física independente.
