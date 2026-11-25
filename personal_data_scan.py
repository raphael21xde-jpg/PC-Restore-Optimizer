"""Procura dados pessoais em arquivos que vão para o git (P5-02).

Funções puras, sem tkinter e sem tocar em disco real: recebem nome e texto
(ou os bytes, em `decode_text`).
O teste `tests/test_p5_02_no_personal_data.py` aplica isso a cada arquivo de
`git ls-files` e falha se algo aparecer.

Os achados dizem só o arquivo, a linha e o tipo; nunca repetem o nome de
usuário nem a credencial encontrada (R-07).
"""
from __future__ import annotations

from pathlib import PurePosixPath
import re

# Nomes genéricos usados como exemplo em testes e documentos. Lista explícita:
# qualquer outro nome depois de `C:\Users\`, `\\PC\c$\Users\`, `/home/` ou
# `/Users/` é tratado como possível nome real. O nome tem de ser exatamente um
# destes (sem diferença de maiúsculas): `Fulano-<algo>` não passa.
ALLOWED_USER_NAMES = frozenset({
    'fulano', 'beltrano', 'ciclano', 'alguem', 'someone',
    'usuario', 'user', 'tester', 'teste', 'test', 'demo', 'exemplo', 'example',
    'ficticio', 'public', 'default', 'administrador', 'administrator',
})
# Arquivos genéricos que ficam direto na pasta `Users` (não são nome de conta).
# Comparação exata do nome inteiro, com a extensão.
ALLOWED_PROFILE_FILES = frozenset({'desktop.ini', 'file.txt'})

# Nomes de arquivo pessoais que nunca podem estar no git.
PERSONAL_FILE_PREFIXES = ('preferencias-', 'deteccao-detalhada-')
SENSITIVE_FILE_NAMES = frozenset({
    '.env', 'id_rsa', 'id_ed25519', 'id_ecdsa', 'credentials.json',
    'otimizacao-diario.json', 'otimizacao-energia-reversao.json',
    'otimizacao-benchmarks.json', 'otimizacao-medicoes.json',
})
SENSITIVE_SUFFIXES = ('.pem', '.pfx', '.p12', '.key')

# Credencial fictícia já usada nos testes do relatório local (é ela que o
# teste confere que sai mascarada). Lista explícita, só valores inventados.
ALLOWED_FAKE_SECRETS = frozenset({
    'ghp_abcdefghijklmnopqrstuvwxyz123456',
})

_SEP = r'(?:\\\\|\\|/)+'
# `<nome>`, `{user}`, `%USERNAME%`, `$env:...` e `*` param o nome (são modelos).
_NAME = r'([^\\/\s"\'<>`*|:;,()\[\]{}$%]+)'
_PROFILES = r'(?:users|usuarios|usuários|documents and settings)'
_HOST = r'[^\\/\s"\'<>|]+'
# `/root` não entra: é a mesma conta em todo Linux e não identifica ninguém.
_USER_PATH = re.compile(
    r'(?i)(?:\b[a-z]:' + _SEP + _PROFILES + _SEP
    # caminho de rede: `\\PC\c$\Users\` ou `\\PC\Users\` (também escapado)
    + r'|\\{2,}' + _HOST + r'\\+(?:[a-z]\$\\+)?' + _PROFILES + r'\\+'
    + r'|(?<![\w:])//' + _HOST + r'/+[a-z]\$/+' + _PROFILES + r'/+'
    + r'|(?<![\w.])/(?:home|Users)/)' + _NAME
)
_SECRETS = (
    ('chave privada', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('token do GitHub', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,})\b')),
    ('chave da AWS', re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ('token do Slack', re.compile(r'\bxox[abprs]-[0-9A-Za-z-]{10,}')),
    ('chave de API', re.compile(r'\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}')),
    ('chave do Google', re.compile(r'\bAIza[0-9A-Za-z_-]{35}\b')),
)


def is_allowed_user_name(name: str) -> bool:
    """Diz se o nome depois de `Users\\` é um exemplo genérico (não identifica ninguém)."""
    name = name.rstrip('.')  # fim de frase: `C:\\Users\\Fulano.`
    if len(name) <= 1:
        return True
    return name.lower() in ALLOWED_USER_NAMES or name.lower() in ALLOWED_PROFILE_FILES


def decode_text(data: bytes) -> str:
    """Texto do arquivo para a busca; binário vira `''` (só o nome é conferido).

    Entende UTF-8 (com ou sem BOM), UTF-16 e UTF-32 com BOM e UTF-16 sem BOM
    (comum em arquivos salvos pelo PowerShell ou pelo Bloco de Notas antigo).
    """
    for bom, encoding in ((b'\xff\xfe\0\0', 'utf-32'), (b'\0\0\xfe\xff', 'utf-32'),
                          (b'\xff\xfe', 'utf-16'), (b'\xfe\xff', 'utf-16'),
                          (b'\xef\xbb\xbf', 'utf-8-sig')):
        if data.startswith(bom):
            return data.decode(encoding, errors='replace')
    head = data[:8192]
    if b'\0' not in head:
        return data.decode('utf-8', errors='replace')
    # UTF-16 sem BOM: quase todo byte de uma das posições (par ou ímpar) é zero.
    pairs = len(head) // 2
    if pairs >= 2:
        even_zero = head[0:pairs * 2:2].count(0) / pairs
        odd_zero = head[1:pairs * 2:2].count(0) / pairs
        if odd_zero >= 0.9 and even_zero == 0:
            return data.decode('utf-16-le', errors='replace')
        if even_zero >= 0.9 and odd_zero == 0:
            return data.decode('utf-16-be', errors='replace')
    return ''


def user_path_names(text: str) -> list[str]:
    """Nomes de usuário que aparecem em caminhos como `C:\\Users\\<nome>`."""
    return [match.group(1) for match in _USER_PATH.finditer(text)]


def personal_file_name_reason(path: str) -> str | None:
    """Motivo, se o próprio nome do arquivo é de dado pessoal ou credencial."""
    name = PurePosixPath(path.replace('\\', '/')).name.lower()
    if name.startswith(PERSONAL_FILE_PREFIXES) or name in SENSITIVE_FILE_NAMES:
        return 'arquivo pessoal do PC'
    if name.endswith(SENSITIVE_SUFFIXES):
        return 'arquivo de chave ou certificado'
    return None


def personal_data_findings(path: str, text: str) -> list[str]:
    """Lista o que há de pessoal no arquivo: `arquivo:linha: tipo` (sem o dado em si)."""
    findings = []
    reason = personal_file_name_reason(path)
    if reason:
        findings.append(f'{path}: {reason}')
    for number, line in enumerate(text.splitlines(), start=1):
        if any(not is_allowed_user_name(name) for name in user_path_names(line)):
            findings.append(f'{path}:{number}: caminho com nome de usuário')
        for kind, pattern in _SECRETS:
            if any(m.group(0) not in ALLOWED_FAKE_SECRETS for m in pattern.finditer(line)):
                findings.append(f'{path}:{number}: {kind}')
    return findings
