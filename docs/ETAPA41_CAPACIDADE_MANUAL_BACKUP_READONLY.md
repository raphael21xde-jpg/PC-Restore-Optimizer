# Etapa 41 — Estimativa manual de tamanho e espaço para backup (somente leitura)

## Por que esta etapa

O último relatório real dos volumes C:, D:, F: e G: informava
`capacity_status: not_evaluated`. O projeto já possuía uma função
`assess_backup_target(..., expected_backup_bytes=...)` para confrontar
um tamanho estimado de backup com `SizeRemaining` retornado pelo
**Get-Volume**, mas o diálogo da interface ainda não permitia informar
um tamanho.

## O que foi acrescentado

Na janela **Diagnóstico → Conferir origens e destinos (somente leitura)**,
há um terceiro campo:

**Tamanho estimado do backup (GiB, opcional)**

- Aceita valores como `120`, `1,5` ou `1.5`. A unidade é **GiB**,
  equivalente a 1.073.741.824 bytes.
- Valor em branco = tamanho **não avaliado**, jamais zero bytes.
- Valores zero, negativos, comandos, notação exponencial, valores
  gigantes ou casas decimais acima do limite são rejeitados **antes**
  da coleta de inventário.
- O número é **informado manualmente** pelo usuário, não calculado a
  partir da seleção de jogos, saves ou arquivos: isso continua sendo
  um trabalho independente para o planejamento completo.
- A comparação usa a **mesma consulta de inventário somente leitura**
  que já existe; não é feita outra passagem por pastas e não é
  realizada cópia física de arquivo.
- Mudanças nos volumes ou no tamanho invalidam a consulta anterior
  e desabilitam **Copiar resumo seguro** até nova conferência.

O resultado pode ser:

| Código | Significado |
| --- | --- |
| `not_evaluated` | Nenhum tamanho de backup informado |
| `reported_sufficient` | Espaço livre reportado é maior ou igual ao tamanho digitado, **sem** reserva de segurança |
| `insufficient` | Estimativa maior que espaço livre reportado; candidato bloqueado |
| `unknown` | O Windows não confirmou espaço livre, candidato bloqueado |

A área de detalhes apresenta tamanho estimado e espaço livre em GiB.
O resumo seguro exporta apenas números de bytes limitados, códigos
predefinidos e alertas de texto fixo; nunca caminho, GUID, serial,
identidade do computador nem mensagens brutas do inventário.

## Teste local com cenários fictícios

```powershell
py -3 scripts\test_reporter.py --pattern "test_backup_capacity_plan_readonly.py" --publish
```

Os testes verificam parsing, segurança, capacidade insuficiente/desconhecida,
boa estimativa sem aprovação, atualização da interface, compatibilidade
com o diálogo anterior e anonimização. Todas as consultas de hardware
nos testes Tk são simuladas. Não usar GitHub Actions. Revisar a prévia
sanitizada antes de publicar no PR #54.

## Ensaio opcional no próprio Windows

Depois que a bateria passar, abrir `py -3 app.py` e escolher
**Diagnóstico → Conferir origens e destinos (somente leitura)**.
Selecionar as unidades reais relevantes; informar, *se quiser*, um
tamanho **estimado**, por exemplo `120` GiB. A escolha de destino
é **somente para análise**. Observar `capacity_status`, 
`expected_backup_bytes` e `free_bytes_reported` em
**Copiar resumo seguro**.

**Não** selecionar uma unidade como destino real apenas porque o espaço
reportado parece suficiente; não é checada uma margem para manifestos,
saves alterados, movimentação de espaço livre nem a integridade de backup.
Deve haver revisão da independência física e dos vínculos EFI,
especialmente em Storage Spaces e discos não listados pelo Get-Disk.

`copy_authorized=False`, `physical_independence_verified=False`,
`ready_for_format=False` e `installation_authorized=False`
continuam **obrigatoriamente falsos**.

## Próximo trabalho funcional

Relacionar os tamanhos reais da seleção de arquivos, jogos e saves ao
plano de backup **sem** autorizar cópia de produção. Esse cálculo de
manifesto e a validação de destino físico ainda requerem implementação
e testes separados.
