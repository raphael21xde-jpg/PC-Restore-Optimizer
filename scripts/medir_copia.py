"""Medir a velocidade de cópia de uma pasta para outro disco (P2-10).

Exemplo (troque as pastas pelas suas):
    py -3 scripts\\medir_copia.py --origem D:\\Jogos --destino E:\\

A origem só é LIDA. O script cria uma pasta nova PCRO-MEDICAO-... dentro do
destino, copia uma amostra (padrão: até 1 GiB e 5000 arquivos), confere cada
cópia com SHA-256 e grava relatorio.txt e relatorio.json nessa pasta.
Nada é apagado. Para parar no meio, aperte Ctrl+C.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import copy_bench  # noqa: E402


def _chunks(text):
    try:
        values = tuple(int(part) for part in text.split(',') if part.strip())
    except ValueError:
        raise argparse.ArgumentTypeError('use números separados por vírgula, ex.: 1,4,8')
    if not values:
        raise argparse.ArgumentTypeError('informe pelo menos um tamanho de bloco')
    return values


def _positive(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError('use um número inteiro')
    if value < 1:
        raise argparse.ArgumentTypeError('use um número maior que zero')
    return value


def main(argv=None, *, usage=shutil.disk_usage):
    parser = argparse.ArgumentParser(
        description='Medir a velocidade de cópia (só lê a origem e só grava '
                    'numa pasta nova de medição dentro do destino; nada é apagado).')
    parser.add_argument('--origem', required=True,
                        help='Pasta que será só lida, ex.: D:\\Jogos')
    parser.add_argument('--destino', required=True,
                        help='Pasta onde a pasta de medição será criada, ex.: E:\\')
    parser.add_argument('--max-mib', type=_positive, default=1024,
                        help='Tamanho máximo da amostra em MiB (padrão: 1024)')
    parser.add_argument('--max-arquivos', type=_positive, default=5000,
                        help='Número máximo de arquivos da amostra (padrão: 5000)')
    parser.add_argument('--blocos', type=_chunks, default=(1, 4, 8),
                        help='Tamanhos de bloco em MiB, separados por vírgula (padrão: 1,4,8)')
    options = parser.parse_args(argv)
    print('Medindo a cópia. A origem só é lida; nada é apagado. '
          'Para parar, aperte Ctrl+C.', flush=True)
    try:
        result = copy_bench.run_bench(
            options.origem, options.destino, chunks=options.blocos,
            max_bytes=options.max_mib * copy_bench.MIB,
            max_files=options.max_arquivos, usage=usage)
    except copy_bench.BenchRefused as refusal:
        print('MEDIÇÃO NÃO FEITA: %s' % refusal)
        return 2
    except KeyboardInterrupt:
        print('Medição cancelada antes de começar a copiar.')
        return 1
    except OSError as error:
        # Sem repetir o caminho da exceção: pode ter o nome do usuário.
        print('MEDIÇÃO NÃO FEITA: erro do sistema (%s).'
              % (error.strerror or type(error).__name__))
        return 2
    text, _data = copy_bench.bench_report(result)
    print()
    print(text)
    print('Relatório salvo em relatorio.txt e relatorio.json, dentro da pasta %s.'
          % result.folder_name)
    return 0 if result.status == 'concluída' else 1


if __name__ == '__main__':
    sys.exit(main())
