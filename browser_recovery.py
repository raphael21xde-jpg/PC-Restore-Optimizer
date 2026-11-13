"""Prepare explicit browser imports without writing to an installed profile."""
import html
import json
from pathlib import Path
from urllib.parse import urlsplit
from browser_vault import _special


def safe_file(root, relative):
    root = Path(root).absolute()
    p = root / relative
    for part in (root, *root.parents, p, *p.parents):
        if part.exists() and _special(part):
            raise ValueError('Links ou junções não são aceitos na recuperação.')
    if not p.is_file():
        return None
    if p.stat().st_size > 128 * 1024**2:
        raise ValueError('Arquivo excede 128 MiB.')
    return p


def inspect_recovery(root):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('Selecione a pasta extraída do cofre.')
    meta = safe_file(root, 'metadata/info.json')
    info = json.loads(meta.read_text(encoding='utf-8')) if meta else {}
    return {
        'browser': info.get('browser', 'Não identificado — confirme a origem'),
        'bookmarks_html': safe_file(root, 'manual-export/favoritos.html'),
        'bookmarks_json': safe_file(root, 'profile/Bookmarks'),
        'password_csv': safe_file(root, 'manual-export/senhas-exportadas.csv') or
                        safe_file(root, 'senhas_exportadas_MANUALMENTE.csv'),
    }


def bookmarks_html(source):
    data = json.loads(Path(source).read_text(encoding='utf-8-sig'))
    roots = data.get('roots')
    if not isinstance(roots, dict):
        raise ValueError('Arquivo Bookmarks inválido: roots ausente.')
    lines = ['<!DOCTYPE NETSCAPE-Bookmark-file-1>', '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
             '<TITLE>Favoritos recuperados</TITLE>', '<H1>Favoritos recuperados</H1>', '<DL><p>']
    count = 0
    def visit(node, depth=0):
        nonlocal count
        if depth > 64 or not isinstance(node, dict):
            raise ValueError('Estrutura de favoritos inválida ou profunda demais.')
        name = html.escape(str(node.get('name', 'Sem nome')), quote=True)
        if node.get('type') == 'url':
            url = str(node.get('url', ''))
            if urlsplit(url).scheme.lower() not in ('http', 'https', 'ftp'):
                return
            lines.append('<DT><A HREF="' + html.escape(url, quote=True) + '">' + name + '</A>')
            count += 1
        elif node.get('type') == 'folder':
            lines.extend(['<DT><H3>' + name + '</H3>', '<DL><p>'])
            for child in node.get('children', []):
                visit(child, depth + 1)
            lines.append('</DL><p>')
    for node in roots.values():
        if isinstance(node, dict) and node.get('type') in ('folder', 'url'):
            visit(node)
    lines.append('</DL><p>')
    if not count:
        raise ValueError('Nenhum favorito HTTP, HTTPS ou FTP encontrado.')
    return '\n'.join(lines), count


def prepare_bookmarks(root, destination):
    """Unique output; no existing file or profile is overwritten."""
    import uuid
    found = inspect_recovery(root)
    target = Path(destination)
    if not target.is_dir() or any(_special(p) for p in (target, *target.parents)):
        raise ValueError('Escolha uma pasta normal existente.')
    if found['bookmarks_html']:
        payload = found['bookmarks_html'].read_bytes()
        count = None
    elif found['bookmarks_json']:
        payload, count = bookmarks_html(found['bookmarks_json'])
        payload = payload.encode('utf-8')
    else:
        raise ValueError('O cofre não contém favoritos importáveis.')
    out = target / ('favoritos-recuperados-' + uuid.uuid4().hex[:10] + '.html')
    with out.open('xb') as stream:
        stream.write(payload)
    return out, count


# Navegadores para os quais o assistente mostra o passo a passo da importação.
GUIDED_BROWSERS = ('Opera', 'Opera GX', 'Google Chrome', 'Microsoft Edge', 'Mozilla Firefox')

OPERA_NAMES = ('Opera', 'Opera GX')

# Páginas de ajuda do fabricante sobre IMPORTAR, por etapa (R-83, R-84).
# O Opera e o Opera GX não têm página só sobre importar: ficam sem link, de propósito.
IMPORT_HELP = {
    'Google Chrome': {'favoritos': 'https://support.google.com/chrome/answer/96816',
                      'senhas': 'https://support.google.com/chrome/answer/13068232'},
    'Microsoft Edge': {'favoritos': 'https://support.microsoft.com/en-us/edge/import-your-favorites-and-passwords-in-microsoft-edge',
                       'senhas': 'https://support.microsoft.com/en-us/edge/import-your-favorites-and-passwords-in-microsoft-edge'},
    'Mozilla Firefox': {'favoritos': 'https://support.mozilla.org/en-US/kb/import-bookmarks-html-file',
                        'senhas': 'https://support.mozilla.org/en-US/kb/import-login-data-file'},
}

NO_OPERA_HELP_TEXT = ('Para o Opera e o Opera GX use os passos acima: não há página de ajuda '
                      'só sobre importar.')
NO_BROWSER_HELP_TEXT = ('Este navegador não tem passo a passo nem ajuda no assistente. Entre na conta '
                        'e ligue a sincronização, ou importe o CSV de senhas pelo próprio navegador '
                        'e depois apague o CSV.')


def _help_note(browser):
    if browser in OPERA_NAMES:
        return 'Se o menu estiver diferente, procure por "importar" na ajuda do próprio Opera.'
    return ('Se o menu estiver diferente, use, nesta janela, o botão '
            '"Ajuda oficial do navegador".')


def destination_supported(browser):
    """True só para os navegadores com passo a passo escrito aqui."""
    return browser in GUIDED_BROWSERS


def help_url(browser, step='favoritos'):
    """Endereço (https) da ajuda oficial sobre importar; vazio se não houver."""
    url = IMPORT_HELP.get(browser, {}).get(step, '')
    return url if url.lower().startswith('https://') else ''


def help_missing_text(browser):
    """Aviso para quando o botão de ajuda não tem página para este navegador."""
    return NO_OPERA_HELP_TEXT if browser in OPERA_NAMES else NO_BROWSER_HELP_TEXT


def bookmark_import_steps(browser, html_path):
    """Texto da tela 'Importar favoritos'. Só texto; não escreve em perfil."""
    if not destination_supported(browser):
        raise ValueError('Este navegador não tem passo a passo no assistente.')
    head = f'Arquivo preparado:\n{html_path}\n\nO caminho foi copiado. '
    if browser in ('Opera', 'Opera GX'):
        how = (f'Abra o {browser} no perfil escolhido, pressione Ctrl+Shift+B e use '
               'Importar favoritos → arquivo HTML. Selecione este arquivo.')
    elif browser == 'Google Chrome':
        how = ('Abra o Google Chrome no perfil escolhido, vá em Configurações → '
               '"Importar favoritos e configurações" e, em "Escolher o que importar", '
               'selecione "Arquivo HTML de favoritos". Escolha este arquivo.')
    elif browser == 'Microsoft Edge':
        how = ('Abra o Microsoft Edge no perfil escolhido, vá em Configurações → Perfis → '
               '"Importar dados do navegador", em "Importar de" escolha '
               '"Arquivo HTML de favoritos ou marcadores" e selecione este arquivo.')
    else:
        how = ('Abra o Mozilla Firefox no perfil escolhido, pressione Ctrl+Shift+O (Biblioteca), '
               'clique em "Importar e fazer backup" e use "Importar favoritos de HTML". '
               'Escolha este arquivo.')
    tail = ('\n\nConfira as pastas antes de repetir a importação para evitar duplicatas. '
            'Os favoritos atuais não são substituídos pelo aplicativo.\n' + _help_note(browser))
    return head + how + tail


def password_import_steps(browser):
    """Texto da tela 'Importar senhas'. Nunca recebe nem mostra senha."""
    if not destination_supported(browser):
        raise ValueError('Este navegador não tem passo a passo no assistente.')
    head = 'O caminho do CSV foi copiado; nenhuma senha foi exibida.\n\n'
    if browser in ('Opera', 'Opera GX'):
        how = ('No Opera escolhido: Configurações → Privacidade e segurança → '
               'Preenchimento automático e senhas → Gerenciador de senhas → '
               'Configurações → Importar senhas / Selecionar arquivo.')
    elif browser == 'Google Chrome':
        how = ('No Google Chrome: Configurações → Preenchimento automático e senhas → '
               'Gerenciador de senhas → Configurações → Importar senhas → Selecionar arquivo.')
    elif browser == 'Microsoft Edge':
        how = ('No Microsoft Edge: Configurações → Perfis → Senhas → botão de três pontos (...) → '
               '"Importar senhas" (ou "Importar dados do navegador" e escolha o arquivo CSV de senhas).')
    else:
        how = ('No Mozilla Firefox: digite about:logins na barra de endereço, clique no botão de três pontos (...) → '
               '"Importar de um arquivo" e escolha o CSV.')
    tail = ('\n\nSelecione o CSV. Confira o resultado no navegador. Depois de validar, '
            'apague o CSV: ele guarda as senhas em texto legível. Preserve o cofre criptografado.\n'
            + _help_note(browser))
    return head + how + tail
