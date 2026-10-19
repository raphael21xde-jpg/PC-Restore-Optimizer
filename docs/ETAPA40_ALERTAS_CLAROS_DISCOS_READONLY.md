# Etapa 40 — avisos de armazenamento claros para qualquer computador

## Resultado real da etapa 39 (somente leitura)

O relatório seguro enviado no teste real indicou:

- C: → disco lógico 2; inicialização associada; Get-Partition e IOCTL coincidem;
- D: → disco lógico 3; Get-Partition e IOCTL coincidem;
- F: → disco lógico 1; ausente do Get-Disk, mas encontrado em Win32_DiskDrive;
  Win32_DiskPartition relatou seis partições;
- G: → disco lógico 4 via Storage Spaces; Get-Partition e IOCTL coincidem
  limitadamente; Get-VirtualDisk/Get-PhysicalDisk relataram um membro,
  resiliência Simple; destino ainda bloqueado.

Essas são **evidências de APIs do Windows**, não identificação independente
de hardware. A configuração Simple não fornece redundância para a falha
de dispositivo. O fato de F: estar ausente no Get-Disk não implica que
esteja vazio, desligado ou sem partições.

## Mudança no aplicativo

`drive_diagnostic_advice.py` gera códigos de alerta estáticos, independentes
das letras das unidades e dos nomes de dispositivos. As regras funcionam para
quaisquer volumes identificados no Windows:

- extents associados à inicialização;
- diferenças entre Get-Partition e IOCTL;
- discos lógicos não listados pelo Get-Disk mas encontrados pela WMI;
- Storage Spaces `Simple` com um membro relatado, `Simple` com mais
  membros, ou associação de membros não confirmada;
- capacidade para backup ainda não avaliada;
- estado de bloqueio de um candidato;
- independência física ainda não comprovada.

A aba Diagnóstico apresenta descrições curtas em português, sempre derivadas
de textos fixos, sem incorporar diretamente nomes, modelos, GUIDs, seriais,
caminhos, descrições de dispositivos ou mensagens do coletor.

O botão **Copiar resumo seguro** acrescenta somente uma lista de **códigos
permitidos** (não mensagens brutas). Tamanho, tipo, duplicatas e códigos
desconhecidos são validados antes de copiar. Relatórios antigos sem
`findings` continuam compatíveis.

**Não há** seleção automática de disco seguro, formatação, reinstalação
do Windows, alteração EFI, cópia de arquivos ou aprovação de backup real.

## Testar localmente

```powershell
py -3 scripts\test_reporter.py --pattern "test_storage_risk_guidance_readonly.py" --publish
```

A bateria usa somente registros fictícios, incluindo letras Q:, R:, S:
e T: para garantir que o comportamento não esteja codificado para um
computador específico. Os testes GUI substituem a consulta real pelo
coletor de teste. Nenhum comando de escrita em discos nem GitHub Actions.
Revise a prévia sanitizada antes de publicar o resultado no PR #54.

## Conferência opcional após os testes

No Windows, `py -3 app.py` → aba Diagnóstico → Conferir origens e destinos
(somente leitura). Se as letras do PC continuarem as mesmas, selecionar
C:,D:,F: e G: *apenas como candidato para análise*, não como destino
autorizado. Os avisos devem explicar a configuração Simple de G: e
as seis partições relatadas via WMI no disco lógico 1 de F:.

É válido que as informações mudem após reinicialização ou alterações
na configuração de armazenamento. Em nenhum caso o diagnóstico comprova
independência física. Campos de segurança continuam:
`copy_authorized=False`, `physical_independence_verified=False`,
`ready_for_format=False`, `installation_authorized=False`.

### Pendências reais

O projeto ainda precisa de um mecanismo de confirmação de dispositivo
físico mais confiável, executor de backup multidisco com verificação,
recuperação integrada e um caminho seguro para reinstalação do Windows/EFI.
Nenhuma dessas funções está liberada por esta etapa.
