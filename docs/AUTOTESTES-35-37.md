# Bateria #35–37

Abra Preservação → Backup seletivo e TESTE de recuperação do C:.
A janela tem uma barra de rolagem à direita para alcançar os novos botões.
Exporte o JSON após cada teste; o teste seguinte substitui o resultado mostrado.
Não precisa selecionar arquivos reais nem configurar um backup anterior.

- #35: grava efetivamente um arquivo sintético de 2 GiB, copia e restaura com
  SHA-256 conferido contra o hash da geração. Mede tempo e pico de memória do
  subprocesso pelo SO. Reprova acima de 512 MiB de pico de RSS/working set.
  Usa até cerca de 6 GiB temporários. Antes de gerar dados, exige espaço para
  três cópias, reserva de pelo menos 10 GiB (ou 10% do livre) e 256 MiB extras.
  No Windows usa o disco da pasta TEMP; não escolhe o destino real do usuário.
  Cancelar encerra somente o subprocesso criado para esse teste, aguarda sua
  saída e remove a área temporária. O limite de memória é critério de aprovação,
  não limite imposto pelo sistema operacional.
- #36: em arquivo de 8 MiB, encerra um subprocesso próprio com os._exit(86)
  após duas escritas de bloco. Não executa finally/cleanup no filho. Rejeita
  o manifesto incompleto e retoma em outro interpretador. Repete a saída abrupta
  na restauração, retoma em novo interpretador e confere SHA-256 e o original.
  Identifica fragmentos temporários abandonados; eles podem permanecer durante
  a retomada e são removidos com toda a área sintética ao terminar.
- #37: usa o loop Tk real da janela enquanto uma thread copia 128 MiB com pausa
  controlada por bloco. O loop atualiza a interface e invoca o botão de cancelar
  a cópia fictícia após oito atualizações. Retoma, restaura e confere SHA-256.
  Registra quantidade de atualizações e maior intervalo; reprova se o intervalo
  observado superar 1 segundo ou o botão não for atendido. Mede esta janela
  nesta carga, não certifica todos os fluxos nem todos os computadores.

Os testes geram resultado-autoteste35.json, resultado-autoteste36.json e
resultado-autoteste37.json. Utilizam somente pastas temporárias novas. Falta de
espaço, cancelamento e exceções não produzem relatório de aprovação. A limpeza
é verificada antes de retornar um relatório aprovado.

Os tempos incluem efeitos do cache do sistema de arquivos. Pico de memória é
por processo; não mede memória total do computador. #36 é saída abrupta de um
processo, não corte de energia nem falha do Windows. Nenhum teste examina backups
reais, prova independência física de cópias ou autoriza reinstalação/formatação.

## Verificações automáticas

`python -m unittest discover -s tests -p "test_autotestes_escala_v035_v037.py" -v`

Para incluir os 2 GiB, defina PCRO_RUN_2GIB=1. A etapa dedicada do GitHub executa
esse tamanho integral no Windows e Linux. Para exigir Tk em vez de pular por
falta de display, defina PCRO_REQUIRE_TK=1. No Linux, use xvfb-run -a. O teste Tk
abre a janela real, invoca os controles, exporta o JSON e confere as métricas.
