# Testes adicionais da pré-checagem de backup (#20)

## Objetivo

A primeira rodada no computador real identificou C: no disco lógico 2 (Windows em uso), D: no disco 3, F: no disco 1 (volume com BOOTMGR **registrado** na ordem UEFI) e G: no disco lógico virtual 4, associado a Storage Spaces Simple com 1 SSD HUSKY reportado. Esses fatos são metadados e **não** autorização para formatar.

## Simulação sem cópia

Em **Diagnóstico → Analisar computador e discos**, clique em **Simular destino de backup (somente leitura)**. Escolha uma ou mais **unidades de origem**, o **destino** e um tamanho de teste estimado em **GiB**, por exemplo `20` ou `20,5`. Clique em **Simular** e use **Copiar relatório** para compartilhar apenas o texto da avaliação.

O cálculo utiliza o inventário já coletado. Não abre arquivos de origem nem escreve no destino. Verifica conflitos *reportados* entre discos lógicos e analisa a capacidade informada com reserva de **10 GiB ou 10% do espaço livre, o que for maior**. Se o espaço não comportar a estimativa mais a reserva, mostra `blocked`. Se não houver bloqueios conhecidos, mostra `requires_review`, nunca uma aprovação de backup.

## Casos úteis (simulação, não execução)

| Origem | Destino | Tamanho manual | Resultado esperado com capacidades observadas |
| --- | --- | --- | --- |
| C: | G: | 20 GiB | `requires_review`; G: Simple sem redundância |
| C: | D: | 80 GiB | `blocked` por reserva de segurança, mesmo quando os bytes informados parecem suficientes |
| G: | G: | 1 GiB | `blocked`, destino coincide com origem |
| C: | F: | 10 GiB | `requires_review` com alerta BOOTMGR registrado |
| C: e F: | D: | 10 GiB | `requires_review`; sem comprovação de independência física |

Os valores acima valem somente como exemplos da capacidade observada na sessão anterior. Os resultados podem variar ao atualizar a capacidade. Não simule formatação nem apague arquivos.

## Limites

- A origem é **uma letra de volume**, não uma seleção de arquivos; o tamanho é **informado manualmente** e não calculado de arquivos reais.
- Não verifica dispositivo físico independente, integridade SHA-256, restauração, propriedade dos dados, acesso remoto, sincronização em nuvem, BootCurrent ou EFI efetivamente utilizada.
- Não altera o fluxo real de backup da #21.
- Cada simulação utiliza o último inventário da sessão: alterações de dispositivos ou espaço exigem executar novamente **Analisar computador e discos**.
- Bloqueios ou ausências de bloqueio **não** autorizam copiar, formatar, reinstalar Windows ou desconectar unidades.
