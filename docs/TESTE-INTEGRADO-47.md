# Teste integrado #47 — fluxo de preservação em diretório descartável

Este teste valida o caminho **índice → marcações de pasta/arquivo →
exportação/importação de escolhas (Windows) → plano seletivo →
backup real de arquivos FICTÍCIOS → verificação SHA-256 →
restauração em pasta isolada → confronto de integridade**.

Também testa: arquivo excluído pela regra de pasta, exceção explícita para
preservar um save dentro de pasta ignorada, backup adulterado que precisa
falhar na verificação e arquivo selecionado que desapareceu.

**Fontes reais do usuário NÃO são examinadas.** São criados apenas arquivos
fictícios em uma nova pasta temporária e ela é removida após os testes.
São usadas as rotinas efetivas de cópia/verificação/restauração do aplicativo,
mas isso NÃO comprova comportamento com jogos reais, mídia EFI, drivers,
navegadores, licenças ou reinstalação do Windows. Formatação permanece bloqueada.

## Executar no Windows (PowerShell)

Abra o terminal na pasta atualizada do repositório:

```powershell
py -3 -m unittest discover -s tests -p "test_selection_backup_restore_e2e_v047.py" -v
```

Se quiser executar as verificações rápidas locais e gerar um resumo JSON:

```powershell
.\TESTAR-APP-SEGURO.ps1
```

A bateria completa é opcional e pode levar vários minutos:

```powershell
.\TESTAR-APP-SEGURO.ps1 -Completo
```

**Não confundir teste simulado com autorização de formatação ou com backup
independente.** A bateria de estresse de 2 GiB continua opcional, apenas na
rotina completa explicitamente preparada para isso.
