# Etapa 34 — diagnóstico físico somente leitura com resumo filtrado

## Entrega

O diálogo de **Conferir origens e destinos (somente leitura)**, já acessível
pela aba **Diagnóstico** do aplicativo, ganhou o botão **Copiar resumo seguro**.
O botão aparece desabilitado até terminar uma nova consulta solicitada
expressamente. Entradas inválidas, erro de coleta ou nova consulta invalidam o
resumo anterior.

O resumo copiado contém somente uma lista fixa de campos:
- letra das unidades de origem/destino escolhidas;
- números de **disco lógico** associados, ou lista vazia se desconhecidos;
- estado dos extents, estado de capacidade, estado de revisão e **contagem**
  de bloqueios por destino;
- números lógicos marcados como boot/sistema/EFI;
- avisos e sinalizadores fixos de **NÃO AUTORIZAÇÃO**.

Nunca copia `SerialNumber`, GUID, modelo de dispositivo, nome de usuário,
caminhos locais, saída PowerShell, descrição textual bruta de erros ou
informações detalhadas dos membros Storage Spaces. Dados que chegam ao
serializador são tratados como potencialmente não confiáveis e validados por
lista de campos e valores permitidos.

## 1. Validar o código (dados fictícios)

No Windows e no diretório do projeto:

```powershell
py -3 scripts\test_reporter.py --pattern "test_safe_hardware_report.py" --publish
```

O `--publish` envia o resumo sanitizado dos **testes** ao PR #54: revise
a prévia antes de publicar. Esta bateria de testes não executa inventário
de discos reais e não utiliza GitHub Actions.

## 2. Ensaio de leitura com hardware real (somente se desejar)

```powershell
py -3 app.py
```

Abrir a aba **Diagnóstico**, clicar em **Conferir origens e destinos (somente
leitura)**, preencher as letras que **de fato existem no computador**
(com as origens que deseja preservar e destinos que deseja *analisar*,
não escolher automaticamente) e clicar em **Conferir discos (SOMENTE
LEITURA)**.

A leitura pode demorar; são usados metadados do Windows, como Get-Disk,
Get-Volume, extents, partitions e outras consultas que o projeto já emprega
no diagnóstico. Não executa backup, não toca EFI/BCD, não cria arquivo e
não formata. O resultado será `blocked`, `incomplete` ou
`requires_review`; **nunca aprovado para cópia**.

Depois, clicar em **Copiar resumo seguro**, revisar o texto copiado e
compartilhar somente se julgar adequado. O clique altera apenas a área de
transferência, e nenhum relatório é enviado automaticamente.

## Interpretação prudente

Mesmo num cenário sem bloqueio conhecido, diferenças de números lógicos
não comprovam independência física. Storage Spaces, RAID, armazenamento
virtual e volumes sem letra podem ter mapeamento incompleto. O relatório
não contém prova de que o Windows inicia de uma EFI independente, nem
garantia de que uma partição pode ser formatada.

`copy_authorized=False`,
`physical_independence_verified=False`,
`ready_for_format=False` e
`installation_authorized=False` permanecem fixos.

A aprovação dos testes sintéticos **não equivale** a executar com sucesso
uma coleta real de hardware. Registre dificuldades sem compartilhar dados
brutos do computador.
