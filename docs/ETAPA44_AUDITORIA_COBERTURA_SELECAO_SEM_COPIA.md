# Etapa 44 — Auditoria da cobertura das escolhas de preservação (sem cópia)

## Por que esta etapa existe

A Etapa 43 passou nos 19 testes locais após a correção na branch
`feature/preview-plan-capacity-readonly-20261019` (commit `87d8fe4`).
Ela reaproveita `Plan.files` e `Plan.total` da prévia de arquivos
existente, mas um usuário pode ter escolhido **também** saves,
jogos, aplicativos e navegadores que não pertencem àquela prévia.

No fluxo atual do `app.py`, a prévia destinada à revisão da
reinstalação pode abranger apenas a unidade do Windows. Um conjunto
de escolhas em outras unidades deve **aparecer como pendência**,
não ser silenciosamente convertido em uma estimativa falsa.

## Implementação

`selection_coverage_audit.audit_selection_coverage(...)` trabalha
**exclusivamente com objetos em memória**:

- `plan.selected`: escolhas do plano de arquivos já calculado.
- `choices`: estados `keep`/`skip` do usuário, inclusive saves;
  escolhas `keep` sem correspondente em `plan.selected` geram
  pendência.
- `auto_save_paths`: assinala quantos desses itens são saves
  detectados e mantidos fora da prévia.
- `catalog_choices` / `catalog_items`: informa o número de
  jogos/aplicativos marcados, e de caminhos candidatos ainda pendentes,
  sem alegar que a cópia dos arquivos garante reinstalação funcional.
- `browser_keep_paths`: informa quantos perfis dependem de um cofre
  ou restauração em procedimento independente. Mesmo um cofre
  anteriormente criado não é automaticamente tratado como verificado.

O resultado possui **apenas contagens e códigos de aviso fixos**;
nunca caminhos, nomes de programas, perfis, senhas ou identificadores.
A auditoria não acessa arquivos e nem coleta inventário de hardware.

No diálogo de diagnóstico aparecem:

1. **Conferir cobertura da seleção** — gera um resumo informativo
   sem ler discos.
2. **Usar tamanho da prévia** — não aceita como estimativa de backup
   abrangente um plano com escolhas `keep` fora da prévia,
   jogos/aplicativos não auditados ou navegadores selecionados.
   O usuário pode continuar digitando uma estimativa **manual**
   separada, explicitamente não verificada.

Se faltar informação ou o estado da seleção estiver inválido, a
auditoria **recusa**, em vez de concluir que nenhum item está pendente.
Mesmo quando não há pendências nessas categorias, o resultado
**não** comprova que todos os dados do computador foram descobertos.

## Teste local

```powershell
py -3 scripts\test_reporter.py --pattern "test_selection_coverage_audit_readonly.py" --publish
```

Os testes usam `Plan` / `FileTask` fictícios, letras Q:, R: e
outras, escolhas keep/skip, saves, aplicativos e navegadores artificiais.
Nenhum arquivo pessoal é copiado ou escaneado. A interface Tk substitui
a consulta física por mock; revisar a prévia sanitizada antes
de publicar o resultado no PR #54.

## Segurança e próximos passos

Esta etapa identifica **lacunas do planejamento**, mas não cria
manifesto multidisco, não reconhece dados relacionados que ainda não
foram inventariados e não testa restauração de aplicativos, saves e
navegadores. A próxima evolução exigirá consolidar os grupos de
arquivos selecionados em um **manifesto somente de planejamento**,
relacionando origem e dependências, com testes em `TemporaryDirectory`.

Continuam imutáveis as condições
`copy_authorized=False`,
`physical_independence_verified=False`,
`ready_for_format=False` e
`installation_authorized=False`.
Nenhuma formatação, remoção, reparticionamento, escrita EFI,
instalação do Windows ou backup real foi autorizada.
