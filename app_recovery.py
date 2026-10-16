"""Explicit reinstall commands and verified, isolated data recovery."""
import os
import re
import shutil
import subprocess
from backup_identity import inside
from backup_features import verified_entries, restore_selected


def package_id(value):
    value = value.strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{1,180}', value) or '.' not in value:
        raise ValueError('Informe o ID completo mostrado na busca, por exemplo Fabricante.Programa.')
    return value


def command(action, value, executable='winget'):
    if action == 'search':
        if not isinstance(value, str) or not value.strip() or value.startswith('-') or len(value) > 250:
            raise ValueError('Nome de busca inválido.')
        return [executable, 'search', '--query', value.strip(), '--source', 'winget', '--disable-interactivity']
    if action not in ('show', 'install', 'list'):
        raise ValueError('Operação inválida.')
    args = [executable, action, '--id', package_id(value), '--exact', '--source', 'winget']
    if action != 'install': args.append('--disable-interactivity')
    else: args += ['--interactive', '--no-upgrade']
    return args


def winget_executable():
    if os.name != 'nt': raise RuntimeError('Reinstalação disponível somente no Windows.')
    executable = shutil.which('winget')
    if not executable: raise RuntimeError('WinGet não encontrado. Instale/atualize o Instalador de Aplicativo da Microsoft e reabra este aplicativo.')
    return executable


def query(action, value):
    if action == 'install': raise ValueError('Instalação exige confirmação separada.')
    result = subprocess.run(command(action, value, winget_executable()), capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=90, stdin=subprocess.DEVNULL)
    return result.returncode, (result.stdout + '\n' + result.stderr).strip()


def install(value):
    # No shell, no guessed package, no implicit acceptance of terms or elevation.
    proc = subprocess.Popen(command('install', value, winget_executable()),
                            creationflags=subprocess.CREATE_NEW_CONSOLE)
    return proc.wait()


def selected_items(plan):
    return [i for i in plan.get('items', []) if isinstance(i, dict) and i.get('decision') == 'keep' and i.get('kind') in ('game', 'app')]


def data_files(manifest, item):
    roots = item.get('save_paths' if item.get('kind') == 'game' else 'data_paths', [])
    roots = [r for r in roots if isinstance(r, str) and r.strip()]
    # Require explicit root metadata; do not match ambiguous display names alone.
    files = verified_entries(manifest)
    return {rel: f for rel, f in files.items() if any(inside(f.get('source', ''), r) for r in roots)}


def restore_data(manifest, item, destination):
    files = data_files(manifest, item)
    if not files: raise ValueError('Nenhum arquivo deste item foi encontrado no manifesto selecionado. Confira o backup e o plano.')
    return restore_selected(manifest, list(files), destination)


def game_help(item):
    origin = str(item.get('origin', '')).casefold()
    if 'steam' in origin:
        return ('Instale o Steam e entre na mesma conta. Se a biblioteca de jogos foi preservada, adicione sua pasta em Configurações > Armazenamento. Confira os jogos reconhecidos e verifique os arquivos pelo Steam. Saves são separados: use Recuperar dados deste item. Se os arquivos da instalação não foram preservados, baixe o jogo novamente.',
                'https://help.steampowered.com/en/faqs/view/4578-18A7-C819-8620')
    if 'epic' in origin:
        return ('Reinstale o Epic Games Launcher e entre na sua conta. O reconhecimento de arquivos existentes depende da versão do launcher; consulte a orientação oficial antes de mover arquivos. O aplicativo não altera .egstore nem apaga pastas. Saves são recuperados separadamente.',
                'https://www.epicgames.com/help/c-32735058/c-36403860/a18575341')
    return ('Reinstale o launcher oficial e entre na conta que possui o jogo. Confira nele se permite localizar arquivos preservados; caso contrário, reinstale o jogo. Não altere permissões de WindowsApps/XboxGames. Saves e configurações não equivalem aos arquivos de instalação do jogo.', None)


def require_equivalent_edition(item, package, details=''):
    name=str(item.get('name','')).casefold()
    if 'osu' in name.replace(' ', ''):
        edition=item.get('edition') or ('lazer' if 'lazer' in name else 'unknown')
        if edition != 'lazer':
            raise ValueError('osu! clássico ou edição não confirmada: reinstalação por WinGet bloqueada para evitar trocar pelo lazer. Preserve Songs/Skins/Replays e use a distribuição stable oficial. O pacote ppy.osu encontrado não comprova equivalência.')
    if 'stable' in name and 'lazer' in str(details).casefold():
        raise ValueError('O pacote apresentado é lazer e não corresponde à edição stable.')
