# Inventário universal de volumes — fase inicial v0.7.1-dev

## Entregue
- Enumeração **somente leitura** de IDs \`\\?\Volume{GUID}\\\` no Windows, via APIs FindFirstVolumeW/FindNextVolumeW.
- Mapeamento de letras e montagens em pastas (GetVolumePathNamesForVolumeNameW).
- Discos de rede, ópticos e dispositivos de tipo desconhecido não são oferecidos para varredura automática.
- Volumes sem letra aparecem no relatório de metadados, com revisão manual obrigatória.
- Botão **Ver todos os volumes** na tela de descoberta, exibindo lacunas e limitações.
- Guias por letra usam dados do mesmo inventário em vez de presumir letras fixas.

## Limitações explícitas
- O estado \`ok\` representa somente a **consulta de metadados**, não a leitura dos arquivos ou a execução de um backup.
- Esta etapa não relaciona de forma exaustiva volume GUID e disco físico. O projeto possui código separado de análise de extents, que precisa ser validado em diferentes computadores.
- Volumes montados **somente em pastas** ainda não possuem guia independente de seleção. São exibidos, mas precisam da futura seleção por identidade de volume.
- Volumes BitLocker bloqueados, espaços de armazenamento, dispositivos removíveis, VHDs, volumes dinâmicos e hotplug requerem testes específicos.
- A interface pode exigir um novo levantamento de volumes depois de conectar/desconectar dispositivos.
- Nenhum mecanismo de formatação, remoção, alteração de partição ou escrita em volume foi adicionado.

## Testes
- Mocks: letras arbitrárias, volume sem letra, montagem em pasta, rede, erros parciais, ID persistente.
- Teste nativo Windows de enumeração **somente de metadados**.
- Testes de regressão anteriores de sintaxe, backup/restauração temporária e cobertura honesta.

## Antes de marcar o inventário universal como completo
1. Correlacionar discos físicos, volumes e partições (incluindo montagens sem letra).
2. Vincular cada caminho ao volume correto para evitar confundir uma montagem NTFS com a unidade hospedeira.
3. Examinar todos os arquivos das raízes escolhidas, reportando permissões negadas e links/junções não visitados.
4. Validar a funcionalidade em máquinas virtuais e físicas Windows de topologias distintas.
5. Nunca autorizar a reinstalação baseada apenas neste inventário de metadados.
