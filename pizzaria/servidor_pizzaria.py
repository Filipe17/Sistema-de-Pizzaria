"""
servidor_pizzaria.py

Servidor da Pizzaria — mesmo padrão do ServidorVotacao
- Sobe servidor HTTP na porta 5000
- Ícone na bandeja do sistema (system tray)
- Clique no ícone → abre o admin no navegador
- Dados em dados/pizzaria.json
- Páginas HTML na mesma pasta do executável
"""

import sys
import os
import json
import threading
import webbrowser
import socket
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote, quote
import urllib.request
from datetime import datetime
import sqlite3

# ── Caminhos ──────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Usa o volume do Railway se disponível, senão pasta local
DADOS_DIR = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', os.path.join(BASE_DIR, 'dados'))
print(f'[DB] DADOS_DIR = {DADOS_DIR}', flush=True)
print(f'[DB] RAILWAY_VOLUME_MOUNT_PATH = {os.environ.get("RAILWAY_VOLUME_MOUNT_PATH","NAO_DEFINIDO")}', flush=True)
DB_PATH   = os.path.join(DADOS_DIR, 'pizzaria.db')
print(f'[DB] DB_PATH = {DB_PATH}, existe = {os.path.exists(DB_PATH)}', flush=True)
PORT      = int(os.environ.get("PORT", 5000))

IMGS_DIR  = os.path.join(DADOS_DIR, 'imagens')
os.makedirs(DADOS_DIR, exist_ok=True)
os.makedirs(IMGS_DIR,  exist_ok=True)


# ── Banco de dados ─────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        PRAGMA journal_mode = WAL;

        CREATE TABLE IF NOT EXISTS config (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS pizzas (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nome      TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            preco     REAL NOT NULL,
            preco_broto  REAL DEFAULT 0,
            preco_media  REAL DEFAULT 0,
            preco_grande REAL DEFAULT 0,
            tem_tamanho  INTEGER DEFAULT 0,
            categoria TEXT DEFAULT 'Pizzas',
            ativa     INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS pedidos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            numero     TEXT NOT NULL UNIQUE,
            mesa       TEXT NOT NULL,
            status     TEXT DEFAULT 'pendente',
            total      REAL DEFAULT 0,
            observacao TEXT DEFAULT '',
            itens_json TEXT DEFAULT '[]',
            criado_em  TEXT DEFAULT (datetime('now','localtime')),
            atualizado TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS mensagens_cliente (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_numero TEXT,
            pedido_itens  TEXT,
            mensagem  TEXT,
            nome_cliente TEXT,
            lida      INTEGER DEFAULT 0,
            criado    TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS mensagens_motoboy (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_numero TEXT,
            mensagem  TEXT,
            nome_cliente TEXT,
            lida      INTEGER DEFAULT 0,
            criado    TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS bairros (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            nome  TEXT NOT NULL,
            taxa  REAL DEFAULT 0,
            ativo INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS clientes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            nome          TEXT NOT NULL DEFAULT '',
            telefone      TEXT DEFAULT '',
            endereco      TEXT DEFAULT '',
            bairro        TEXT DEFAULT '',
            criado_em     TEXT DEFAULT (datetime('now','localtime')),
            ultimo_pedido TEXT,
            pedidos_total INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS usuarios (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario       TEXT NOT NULL UNIQUE,
            senha         TEXT NOT NULL,
            criado_em     TEXT DEFAULT (datetime('now','localtime')),
            ultimo_acesso TEXT
        );
        CREATE TABLE IF NOT EXISTS caixa (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo        TEXT NOT NULL DEFAULT 'entrada',
            valor       REAL NOT NULL DEFAULT 0,
            categoria   TEXT DEFAULT '',
            descricao   TEXT DEFAULT '',
            forma_pagto TEXT DEFAULT 'Dinheiro',
            data        TEXT DEFAULT (date('now','localtime')),
            auto        INTEGER DEFAULT 0,
            criado_em   TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS comandas (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            numero     TEXT NOT NULL,
            mesa       TEXT NOT NULL,
            status     TEXT DEFAULT 'aberta',
            criado_em  TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS estoque_produtos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            nome       TEXT NOT NULL,
            unidade    TEXT DEFAULT 'g',
            quantidade REAL DEFAULT 0,
            minimo     REAL DEFAULT 0,
            custo      REAL DEFAULT 0,
            categoria  TEXT DEFAULT 'Ingrediente'
        );
        CREATE TABLE IF NOT EXISTS estoque_historico (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER,
            tipo       TEXT,
            quantidade REAL,
            custo      REAL DEFAULT 0,
            observacao TEXT DEFAULT '',
            criado_em  TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS receitas (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pizza_id    INTEGER NOT NULL,
            produto_id  INTEGER NOT NULL,
            quantidade  REAL NOT NULL DEFAULT 0,
            UNIQUE(pizza_id, produto_id)
        );
    """)

    # Migração: remove UNIQUE de comandas.numero (SQLite não tem DROP CONSTRAINT)
    try:
        table_def = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='comandas'").fetchone()
        if table_def and 'UNIQUE' in table_def[0].upper():
            print("[DB] Removendo UNIQUE de comandas.numero...", flush=True)
            c.execute("CREATE TABLE comandas_new (id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT NOT NULL, mesa TEXT NOT NULL, status TEXT DEFAULT 'aberta', criado_em TEXT DEFAULT (datetime('now','localtime')))")
            c.execute("INSERT INTO comandas_new (id, numero, mesa, status, criado_em) SELECT id, numero, mesa, status, criado_em FROM comandas")
            c.execute("DROP TABLE comandas")
            c.execute("ALTER TABLE comandas_new RENAME TO comandas")
            conn.commit()
    except Exception as e:
        print(f"[DB] Erro ao migrar comandas: {e}", flush=True)

    # Migração: adiciona comanda_numero na tabela pedidos se não existir
    cols_pedidos = [r[1] for r in c.execute("PRAGMA table_info(pedidos)").fetchall()]
    if 'comanda_numero' not in cols_pedidos:
        c.execute("ALTER TABLE pedidos ADD COLUMN comanda_numero TEXT DEFAULT ''")

    # Seed: usuário padrão admin/1234 (só na primeira vez)
    if not c.execute("SELECT id FROM usuarios LIMIT 1").fetchone():
        c.execute("INSERT INTO usuarios (usuario, senha) VALUES ('admin', '1234')")

    # Seed só na primeira vez
    if not c.execute("SELECT id FROM pizzas LIMIT 1").fetchone():
        # (nome, desc, preco_base, preco_broto, preco_media, preco_grande, tem_tamanho, categoria)
        # (nome, desc, preco_unico, broto, media, grande, tem_tamanho, categoria)
        pizzas = [
            ('Margherita',        'Molho de tomate, mussarela, manjericão', 0, 30.00, 0, 45.00, 1, 'Clássicas'),
            ('Calabresa',         'Molho, mussarela, calabresa, cebola',    0, 30.00, 0, 45.00, 1, 'Clássicas'),
            ('Portuguesa',        'Molho, presunto, ovo, azeitona',         0, 30.00, 0, 45.00, 1, 'Clássicas'),
            ('Frango c/Catupiry', 'Molho, frango, catupiry',                0, 40.00, 0, 55.00, 1, 'Especiais'),
            ('Quatro Queijos',    'Quatro tipos de queijo',                  0, 40.00, 0, 55.00, 1, 'Especiais'),
            ('Chocolate',         'Chocolate ao leite com granulado',        0, 35.00, 0, 45.00, 1, 'Doces'),
            ('Morango c/Cream',   'Morango fresco com cream cheese',         0, 35.00, 0, 45.00, 1, 'Doces'),
            ('Coca-Cola Lata',    '350ml gelada',                         7.90,     0, 0,     0, 0, 'Bebidas'),
            ('Água Mineral',      '500ml',                                5.90,     0, 0,     0, 0, 'Bebidas'),
        ]
        c.executemany("INSERT INTO pizzas (nome,descricao,preco,preco_broto,preco_media,preco_grande,tem_tamanho,categoria) VALUES (?,?,?,?,?,?,?,?)", pizzas)

        configs = [
            ('nome',        'Pizzaria Bella Roma'),
            ('cor',         '#D62828'),
            ('telefone',    ''),
            ('endereco',    ''),
            ('mesas',         '10'),
            ('balcao',        '1'),
            ('anthropic_key', ''),
            ('taxa_delivery',  '0'),
            ('delivery_ativo', '1'),
        ]
        c.executemany("INSERT OR IGNORE INTO config (chave,valor) VALUES (?,?)", configs)

    # ── Migração automática: adiciona colunas novas se não existirem ──
    colunas_existentes = [r[1] for r in c.execute("PRAGMA table_info(pizzas)").fetchall()]
    migracoes = [
        ('preco_broto',  'REAL DEFAULT 0'),
        ('preco_media',  'REAL DEFAULT 0'),
        ('preco_grande', 'REAL DEFAULT 0'),
        ('tem_tamanho',  'INTEGER DEFAULT 0'),
        ('imagem',       'TEXT DEFAULT ""'),
    ]
    for col, defn in migracoes:
        if col not in colunas_existentes:
            c.execute(f'ALTER TABLE pizzas ADD COLUMN {col} {defn}')

    # Migração: forma_pagto em pedidos
    cols_pedidos = [r[1] for r in c.execute("PRAGMA table_info(pedidos)").fetchall()]
    if 'forma_pagto' not in cols_pedidos:
        c.execute("ALTER TABLE pedidos ADD COLUMN forma_pagto TEXT DEFAULT 'Dinheiro'")

    # Migração: colunas da tabela clientes
    cols_clientes = [r[1] for r in c.execute("PRAGMA table_info(clientes)").fetchall()]
    for col, defn in [('endereco', 'TEXT'), ('bairro', 'TEXT'),
                      ('ultimo_pedido', 'TEXT'), ('pedidos_total', 'INTEGER DEFAULT 0')]:
        if col not in cols_clientes:
            c.execute(f"ALTER TABLE clientes ADD COLUMN {col} {defn}")

    # Migração: nome_cliente em mensagens_motoboy
    cols_msg_motoboy = [r[1] for r in c.execute("PRAGMA table_info(mensagens_motoboy)").fetchall()]
    if 'nome_cliente' not in cols_msg_motoboy:
        c.execute("ALTER TABLE mensagens_motoboy ADD COLUMN nome_cliente TEXT DEFAULT '🛵 Motoboy'")

    # Migração: nome_cliente em mensagens_cliente
    cols_msg_cli = [r[1] for r in c.execute("PRAGMA table_info(mensagens_cliente)").fetchall()]
    if 'nome_cliente' not in cols_msg_cli:
        c.execute("ALTER TABLE mensagens_cliente ADD COLUMN nome_cliente TEXT DEFAULT 'Cliente'")

    conn.commit()
    conn.close()

init_db()

# ── Helpers ────────────────────────────────────────────────────────
def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return 'localhost'

def resp_json(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', len(body))
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type')
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(body)

def resp_html(handler, html):
    body = html.encode('utf-8')
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Content-Length', len(body))
    handler.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
    handler.send_header('Pragma', 'no-cache')
    handler.end_headers()
    handler.wfile.write(body)

def ler_html(nome, extra_vars=None):
    """Lê HTML da pasta e injeta variáveis JS"""
    caminho = os.path.join(BASE_DIR, nome)
    if not os.path.exists(caminho):
        return f'<h1>Arquivo não encontrado: {nome}</h1>'
    with open(caminho, encoding='utf-8') as f:
        html = f.read()
    if extra_vars:
        injecao = '<script>'
        for k, v in extra_vars.items():
            injecao += f'window.{k}={json.dumps(v)};'
        injecao += '</script>'
        html = html.replace('</head>', injecao + '</head>', 1)
    return html

# ── Servidor HTTP ──────────────────────────────────────────────────
# ── Gerador de QR Code (usa reportlab já instalado) ──────────────
def gerar_qr_svg(url, scale=9, quiet=4):
    """Gera SVG de QR Code usando reportlab (já vem instalado)."""
    try:
        from reportlab.graphics.barcode.qrencoder import (
            QRCode, QRErrorCorrectLevel, QR8bitByte)

        qr = QRCode.__new__(QRCode)
        qr.errorCorrectLevel = QRErrorCorrectLevel.L
        qr.modules    = None
        qr.moduleCount = 0
        qr.dataCache  = None
        qr.dataList   = [QR8bitByte(url)]

        # Detecta versão mínima
        for v in range(1, 11):
            qr.version    = v
            qr.typeNumber = v
            try:
                qr.makeImpl(True, 0)
                if qr.moduleCount > 0:
                    break
            except Exception:
                pass

        qr.makeImpl(False, qr.getBestMaskPattern())
        n  = qr.moduleCount
        qs = quiet * scale
        sz = n * scale + 2 * qs
        rects = []
        for r in range(n):
            for c in range(n):
                if qr.isDark(r, c):
                    x = qs + c * scale
                    y = qs + r * scale
                    rects.append(
                        '<rect x="{}" y="{}" width="{}" height="{}"/>'.format(x, y, scale, scale))
        return ('<svg xmlns="http://www.w3.org/2000/svg" '
                'width="{0}" height="{0}" viewBox="0 0 {0} {0}">'
                '<rect width="{0}" height="{0}" fill="#fff"/>'
                '<g fill="#000">{1}</g></svg>').format(sz, ''.join(rects))

    except ImportError:
        # Fallback: SVG de erro legível
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">'
                '<rect width="200" height="200" fill="#fff" stroke="#ccc"/>'
                '<text x="100" y="90" text-anchor="middle" font-size="12" fill="#c00">'
                'Instale reportlab</text>'
                '<text x="100" y="110" text-anchor="middle" font-size="10" fill="#666">'
                'pip install reportlab</text></svg>')


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def log_error(self, fmt, *args):
        pass

    def handle_error(self, request, client_address):
        pass  # silencia WinError 10053 e outros erros de conexão abortada

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        try:
            self._do_GET()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                body = json.dumps({'ok': False, 'erro': str(e)}).encode('utf-8')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
                import traceback; print('ERRO GET:', traceback.format_exc())
            except Exception:
                pass

    def _do_GET(self):
        url   = urlparse(self.path)
        path  = url.path
        ip    = get_ip()

        # Páginas HTML
        if path in ('/', '/admin', '/admin/'):
            resp_html(self, ler_html('admin.html', {'IP': ip, 'PORT': PORT}))
        elif path in ('/caixa', '/caixa/'):
            resp_html(self, ler_html('caixa.html', {'IP': ip, 'PORT': PORT}))

        elif path in ('/cozinha', '/cozinha/'):
            resp_html(self, ler_html('cozinha.html', {'IP': ip, 'PORT': PORT}))
        elif path in ('/pedido', '/pedido/'):
            resp_html(self, ler_html('pedido.html', {'IP': ip, 'PORT': PORT}))
        elif path.startswith('/pedido/mesa/'):
            mesa = unquote(path.split('/')[-1])
            resp_html(self, ler_html('pedido.html', {'IP': ip, 'PORT': PORT, 'MESA': mesa}))
        elif path in ('/qr', '/qr/'):
            conn = get_db()
            cfg  = dict(conn.execute("SELECT chave,valor FROM config").fetchall())
            conn.close()
            resp_html(self, ler_html('qr.html', {'IP': ip, 'PORT': PORT, 'NOME': cfg.get('nome','Pizzaria')}))

        elif path in ('/motoboy', '/motoboy/'):
            resp_html(self, ler_html('motoboy.html', {'IP': ip, 'PORT': PORT}))

        elif path in ('/acompanhar', '/acompanhar/'):
            resp_html(self, ler_html('acompanhar.html', {'IP': ip, 'PORT': PORT}))

        elif path in ('/delivery', '/delivery/'):
            conn = get_db()
            cfg  = dict(conn.execute("SELECT chave,valor FROM config").fetchall())
            conn.close()
            resp_html(self, ler_html('delivery.html', {
                'IP':            ip,
                'PORT':          PORT,
                'TAXA_DELIVERY': cfg.get('taxa_delivery','0'),
            }))

        # API
        elif path == '/api/cardapio':
            conn   = get_db()
            pizzas = [dict(r) for r in conn.execute("SELECT * FROM pizzas WHERE ativa=1 ORDER BY categoria,nome").fetchall()]
            conn.close()
            resp_json(self, pizzas)

        elif path == '/api/pedidos':
            params = parse_qs(url.query)
            conn   = get_db()
            q = "SELECT * FROM pedidos WHERE 1=1"
            args = []
            if 'status' in params:
                q += " AND status=?"; args.append(params['status'][0])
            if 'mesa' in params:
                q += " AND mesa=?"; args.append(params['mesa'][0])
            if 'numero' in params:
                q += " AND numero=?"; args.append(params['numero'][0])
            q += " ORDER BY criado_em DESC LIMIT 200"
            pedidos = []
            for r in conn.execute(q, args).fetchall():
                p = dict(r)
                p['itens'] = json.loads(p.get('itens_json') or '[]')
                # Garante comanda_numero mesmo para pedidos antigos (sem o campo)
                if not p.get('comanda_numero') and p.get('mesa') and 'Delivery' not in p.get('mesa',''):
                    cmd = conn.execute(
                        "SELECT numero FROM comandas WHERE mesa=? AND status='aberta' ORDER BY id DESC LIMIT 1",
                        (p['mesa'],)
                    ).fetchone()
                    if cmd:
                        p['comanda_numero'] = cmd['numero']
                pedidos.append(p)
            conn.close()
            resp_json(self, pedidos)

        elif path == '/api/config':
            conn = get_db()
            cfg  = dict(conn.execute("SELECT chave,valor FROM config").fetchall())
            conn.close()
            resp_json(self, cfg)

        elif path == '/api/mensagens-cliente':
            conn = get_db()
            rows = conn.execute("SELECT * FROM mensagens_cliente ORDER BY id DESC").fetchall()
            conn.close()
            resp_json(self, [dict(r) for r in rows])

        elif path == '/api/mensagens-motoboy':
            conn = get_db()
            rows = conn.execute("SELECT * FROM mensagens_motoboy ORDER BY id DESC").fetchall()
            conn.close()
            resp_json(self, [dict(r) for r in rows])

        elif path == '/api/caixa':
            conn = get_db()
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM caixa ORDER BY criado_em DESC"
            ).fetchall()]
            conn.close()
            resp_json(self, rows)

        elif path == '/api/comanda':
            # Busca comanda aberta de uma mesa ou por número
            conn   = get_db()
            params_l = parse_qs(url.query)
            mesa_q = params_l.get('mesa',[''])[0]
            num_q  = params_l.get('numero',[''])[0]
            if num_q:
                row = conn.execute(
                    "SELECT * FROM comandas WHERE numero=? AND status='aberta'", (num_q,)
                ).fetchone()
            elif mesa_q:
                row = conn.execute(
                    "SELECT * FROM comandas WHERE mesa=? AND status='aberta' ORDER BY id DESC LIMIT 1",
                    (mesa_q,)
                ).fetchone()
            else:
                row = None
            conn.close()
            resp_json(self, dict(row) if row else {})

        elif path == '/api/estoque/produtos':
            conn  = get_db()
            rows  = [dict(r) for r in conn.execute("SELECT * FROM estoque_produtos ORDER BY nome").fetchall()]
            conn.close()
            resp_json(self, rows)

        elif path == '/api/receitas':
            conn  = get_db()
            pizza_q = parse_qs(url.query).get('pizza_id',[''])[0]
            if pizza_q:
                rows = [dict(r) for r in conn.execute(
                    "SELECT r.*, p.nome as produto_nome, p.unidade FROM receitas r JOIN estoque_produtos p ON p.id=r.produto_id WHERE r.pizza_id=?",
                    (pizza_q,)
                ).fetchall()]
            else:
                rows = [dict(r) for r in conn.execute(
                    "SELECT r.*, p.nome as produto_nome, p.unidade FROM receitas r JOIN estoque_produtos p ON p.id=r.produto_id"
                ).fetchall()]
            conn.close()
            resp_json(self, rows)

        elif path == '/api/comanda/pedidos':
            # Retorna todos os pedidos de uma comanda
            conn    = get_db()
            num_q   = parse_qs(url.query).get('numero',[''])[0]
            if not num_q:
                resp_json(self, []); conn.close(); return
            # Pega a comanda mais recente com este número (pode haver duplicados fechados)
            cmd = conn.execute("SELECT * FROM comandas WHERE numero=? ORDER BY id DESC LIMIT 1", (num_q,)).fetchone()
            if not cmd:
                resp_json(self, {'erro': 'Comanda não encontrada'}, 404); conn.close(); return
            # Busca por comanda_numero (novo) com fallback por mesa+data (legado)
            pedidos_rows = conn.execute(
                "SELECT * FROM pedidos WHERE comanda_numero=? ORDER BY criado_em",
                (num_q,)
            ).fetchall()
            if not pedidos_rows:
                # Fallback para pedidos antigos sem comanda_numero
                pedidos_rows = conn.execute(
                    "SELECT * FROM pedidos WHERE mesa=? AND criado_em >= ? ORDER BY criado_em",
                    (dict(cmd)['mesa'], dict(cmd)['criado_em'])
                ).fetchall()
            pedidos = [dict(r) for r in pedidos_rows]
            for p in pedidos:
                p['itens'] = json.loads(p.get('itens_json') or '[]')
            conn.close()
            resp_json(self, {'comanda': dict(cmd), 'pedidos': pedidos})

        elif path == '/api/status':
            resp_json(self, {'ok': True, 'ip': ip, 'port': PORT})

        elif path == '/api/bairros':
            conn    = get_db()
            bairros = [dict(r) for r in conn.execute("SELECT * FROM bairros WHERE ativo=1 ORDER BY nome").fetchall()]
            conn.close()
            resp_json(self, bairros)

        elif path == '/api/clientes':
            conn = get_db()
            busca = parse_qs(url.query).get('busca', [''])[0].strip().lower()
            # Busca da tabela clientes se existir dados
            if busca:
                clientes = [dict(r) for r in conn.execute(
                    "SELECT * FROM clientes WHERE LOWER(nome) LIKE ? ORDER BY nome LIMIT 10",
                    (busca + '%',)
                ).fetchall()]
            else:
                clientes = [dict(r) for r in conn.execute(
                    "SELECT * FROM clientes ORDER BY CASE WHEN ultimo_pedido IS NULL THEN 1 ELSE 0 END, ultimo_pedido DESC, nome"
                ).fetchall()]
            if not clientes:
                # Extrai clientes únicos dos pedidos de delivery
                pedidos_delivery = conn.execute(
                    "SELECT mesa, observacao, MAX(criado_em) as ultimo, COUNT(*) as total "
                    "FROM pedidos WHERE mesa LIKE '%Delivery%' OR mesa LIKE '%delivery%' "
                    "GROUP BY observacao ORDER BY ultimo DESC"
                ).fetchall()
                vistos = set()
                for p in pedidos_delivery:
                    obs = p['observacao'] or ''
                    # Extrai campos da observação
                    import re
                    # Suporta tanto 'Cliente:' (delivery) quanto 'Nome:' (legado)
                    nome_m   = re.search(r'Cliente:\s*([^|]+)', obs) or re.search(r'Nome:\s*([^|]+)', obs)
                    tel_m    = re.search(r'Tel:\s*([^|]+)', obs)
                    end_m    = re.search(r'End:\s*([^|]+)', obs)
                    nome     = nome_m.group(1).strip() if nome_m else ''
                    tel      = tel_m.group(1).strip()  if tel_m  else ''
                    end_raw  = end_m.group(1).strip()  if end_m  else ''
                    # Bairro vem dentro do End: "Rua X — Bairro Y"
                    if ' — ' in end_raw:
                        end_parts = end_raw.split(' — ', 1)
                        end    = end_parts[0].strip()
                        bairro = end_parts[1].strip()
                    else:
                        end    = end_raw
                        bairro = (re.search(r'Bairro:\s*([^|]+)', obs) or type('', (), {'group': lambda s,x: ''})()).group(1) if re.search(r'Bairro:\s*([^|]+)', obs) else ''
                    chave  = tel or nome
                    if not chave or chave in vistos:
                        continue
                    vistos.add(chave)
                    clientes.append({
                        'id': len(clientes) + 1,
                        'nome': nome,
                        'telefone': tel,
                        'endereco': end,
                        'bairro': bairro,
                        'ultimo_pedido': p['ultimo'],
                        'pedidos_total': p['total'],
                    })
            conn.close()
            resp_json(self, clientes)

        elif path == '/cozinha-manifest.json':
            manifest = {
                "name": "Cozinha Pizzaria",
                "short_name": "Cozinha",
                "start_url": "/cozinha",
                "display": "fullscreen",
                "orientation": "landscape",
                "background_color": "#0d0d0d",
                "theme_color": "#0d0d0d",
                "icons": [
                    {"src": "/cozinha-icon.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                    {"src": "/cozinha-icon.png", "sizes": "512x512", "type": "image/png"}
                ]
            }
            body_m = json.dumps(manifest).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/manifest+json')
            self.send_header('Content-Length', len(body_m))
            self.end_headers()
            self.wfile.write(body_m)

        elif path == '/cozinha-sw.js':
            sw_code = (
                "self.addEventListener('install',e=>self.skipWaiting());"
                "self.addEventListener('activate',e=>e.waitUntil(clients.claim()));"
                "self.addEventListener('fetch',e=>e.respondWith(fetch(e.request).catch(()=>new Response('offline'))));"
            ).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript')
            self.send_header('Content-Length', len(sw_code))
            self.send_header('Service-Worker-Allowed', '/')
            self.end_headers()
            self.wfile.write(sw_code)

        elif path == '/cozinha-icon.png':
            try:
                from PIL import Image, ImageDraw
                import io
                img  = Image.new('RGB', (512, 512), color=(13, 13, 13))
                draw = ImageDraw.Draw(img)
                draw.ellipse([56, 56, 456, 456], fill=(214, 40, 40))
                draw.ellipse([90, 90, 422, 422], fill=(255, 140, 0))
                draw.line([256, 90, 256, 422], fill=(214, 40, 40), width=10)
                draw.line([90, 256, 422, 256], fill=(214, 40, 40), width=10)
                draw.line([146, 146, 366, 366], fill=(214, 40, 40), width=7)
                draw.line([366, 146, 146, 366], fill=(214, 40, 40), width=7)
                buf = io.BytesIO()
                img.save(buf, 'PNG')
                png_bytes = buf.getvalue()
            except Exception:
                import base64 as _b64
                png_bytes = _b64.b64decode(
                    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQ'
                    'AABjkB6QAAAABJRU5ErkJggg=='
                )
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', len(png_bytes))
            self.send_header('Cache-Control', 'max-age=86400')
            self.end_headers()
            self.wfile.write(png_bytes)

        elif path.startswith('/api/imagem/'):
            fname  = unquote(path[len('/api/imagem/'):])
            fpath  = os.path.join(IMGS_DIR, os.path.basename(fname))
            if os.path.isfile(fpath):
                ext  = os.path.splitext(fname)[1].lower()
                mime = {'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','webp':'image/webp','gif':'image/gif'}.get(ext.lstrip('.'), 'image/jpeg')
                data = open(fpath, 'rb').read()
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', len(data))
                self.send_header('Cache-Control', 'max-age=86400')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404); self.end_headers()

        elif path.startswith('/api/proxy-imagem'):
            qs   = parse_qs(urlparse(self.path).query)
            iurl = qs.get('url', [''])[0]
            if not iurl:
                self.send_response(400); self.end_headers(); return
            try:
                req = urllib.request.Request(iurl, headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Accept': 'image/*,*/*'
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    dados   = resp.read()
                    ctype   = resp.headers.get('Content-Type', 'image/jpeg')
                    if not ctype.startswith('image'):
                        raise ValueError('Não é imagem')
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', len(dados))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(dados)
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 502)

        elif path.startswith('/api/qr/'):
            mesa_qr = unquote(path[len('/api/qr/'):])
            host = self.headers.get('Host', f'{ip}:{PORT}')
            proto = self.headers.get('X-Forwarded-Proto', '')
            protocolo = 'https' if proto == 'https' or ':443' in host else 'http'
            mesa_encoded = quote(mesa_qr, safe='')
            url_pedido = f'{protocolo}://{host}/pedido/mesa/{mesa_encoded}'
            svg = gerar_qr_svg(url_pedido)
            body = svg.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'image/svg+xml')
            self.send_header('Content-Length', len(body))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not found')

    def do_POST(self):
        try:
            self._do_POST()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception as e:
            # Sempre responde mesmo em erro — evita ERR_EMPTY_RESPONSE
            try:
                import traceback
                msg = traceback.format_exc()
                body = json.dumps({'ok': False, 'erro': str(e)}).encode('utf-8')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
                print('ERRO POST:', msg)
            except Exception:
                pass

    def _do_POST(self):
        url    = urlparse(self.path)
        path   = url.path
        length = int(self.headers.get('Content-Length', 0))
        body   = json.loads(self.rfile.read(length) or b'{}')

        if path == '/api/pedido/novo':
            conn      = get_db()
            numero    = 'P' + datetime.now().strftime('%H%M%S')
            observacao = body.get('observacao','')
            mesa_ped = body.get('mesa', '-')
            # Busca comanda aberta para esta mesa (ou usa o número enviado pelo cliente se estiver aberta)
            comanda_num = body.get('comanda', '') or ''
            if comanda_num:
                # Valida se a comanda enviada ainda está aberta para esta mesa
                v = conn.execute(
                    "SELECT id FROM comandas WHERE numero=? AND mesa=? AND status='aberta'",
                    (comanda_num, mesa_ped)
                ).fetchone()
                if not v: comanda_num = ''

            if not comanda_num:
                cmd_row = conn.execute(
                    "SELECT numero FROM comandas WHERE mesa=? AND status='aberta' ORDER BY id DESC LIMIT 1",
                    (mesa_ped,)
                ).fetchone()
                if cmd_row:
                    comanda_num = cmd_row['numero']

            conn.execute(
                "INSERT INTO pedidos (numero,mesa,total,observacao,itens_json,comanda_numero) VALUES (?,?,?,?,?,?)",
                (numero, mesa_ped, body.get('total',0),
                 observacao, json.dumps(body.get('itens',[])), comanda_num)
            )
            conn.execute("UPDATE pedidos SET atualizado=datetime('now','localtime') WHERE numero=?", (numero,))
            conn.commit()  # commit do pedido primeiro — garante que o pedido é salvo

            # Cria comanda automaticamente para pedidos de mesa (não delivery)
            try:
                mesa_ped = body.get('mesa', '-')
                is_delivery = 'Delivery' in mesa_ped or body.get('tipo') == 'delivery'
                if not is_delivery:
                    existe_cmd = conn.execute(
                        "SELECT numero FROM comandas WHERE mesa=? AND status='aberta'", (mesa_ped,)
                    ).fetchone()
                    if not existe_cmd:
                        # Gera número único de 4 dígitos (diferente do anterior dessa mesa)
                        import random as _rnd
                        ultima_cmd = conn.execute("SELECT numero FROM comandas WHERE mesa=? ORDER BY id DESC LIMIT 1", (mesa_ped,)).fetchone()
                        ultimo_num = ultima_cmd['numero'] if ultima_cmd else None

                        for _ in range(100):
                            num_cmd = str(_rnd.randint(1000, 9999))
                            if num_cmd == ultimo_num: continue
                            dup = conn.execute("SELECT id FROM comandas WHERE numero=? AND status='aberta'", (num_cmd,)).fetchone()
                            if not dup: break
                        conn.execute("INSERT INTO comandas (numero, mesa) VALUES (?,?)", (num_cmd, mesa_ped))
                        conn.commit()
            except Exception as ex:
                print(f'[AVISO] Erro ao criar comanda: {ex}', flush=True)

            # Salva/atualiza cliente (apenas delivery) — em try separado para não bloquear o pedido
            try:
                import re as _re
                if body.get('tipo') == 'delivery' or '\U0001f6f5 DELIVERY' in str(observacao):
                    def _ext(pat):
                        m = _re.search(pat, str(observacao))
                        return m.group(1).strip() if m else ''
                    cli_nome   = _ext(r'Cliente:\s*([^|]+)')
                    cli_tel    = _ext(r'Tel:\s*([^|]+)')
                    cli_end    = _ext(r'End:\s*([^|]+)')
                    cli_bairro = ''
                    if ' \u2014 ' in cli_end:
                        partes     = cli_end.split(' \u2014 ', 1)
                        cli_end    = partes[0].strip()
                        cli_bairro = partes[1].strip()
                    if cli_tel:
                        existe = conn.execute(
                            "SELECT id, nome, pedidos_total FROM clientes WHERE telefone=?", (cli_tel,)
                        ).fetchone()
                        if existe:
                            conn.execute(
                                "UPDATE clientes SET nome=?, endereco=?, bairro=?, ultimo_pedido=datetime('now','localtime'), pedidos_total=pedidos_total+1 WHERE telefone=?",
                                (cli_nome or existe['nome'], cli_end, cli_bairro, cli_tel)
                            )
                        else:
                            conn.execute(
                                "INSERT INTO clientes (nome,telefone,endereco,bairro,ultimo_pedido,pedidos_total) VALUES (?,?,?,?,datetime('now','localtime'),1)",
                                (cli_nome, cli_tel, cli_end, cli_bairro)
                            )
                        conn.commit()
            except Exception as ex:
                print(f'[AVISO] Erro ao salvar cliente: {ex}', flush=True)

            pedido = dict(conn.execute("SELECT * FROM pedidos WHERE numero=?", (numero,)).fetchone())
            pedido['itens'] = body.get('itens', [])
            conn.close()
            resp_json(self, {'ok': True, 'pedido': pedido})

        elif path == '/api/pedido/status':
            conn = get_db()
            conn.execute(
                "UPDATE pedidos SET status=?,atualizado=datetime('now','localtime') WHERE id=?",
                (body.get('status'), body.get('id'))
            )
            conn.commit()
            conn.close()
            resp_json(self, {'ok': True})

        elif path == '/api/pedido/forma-pagto':
            conn = get_db()
            conn.execute(
                "UPDATE pedidos SET forma_pagto=? WHERE id=?",
                (body.get('forma_pagto','Dinheiro'), body.get('id'))
            )
            conn.commit()
            conn.close()
            resp_json(self, {'ok': True})

        elif path == '/api/config/salvar':
            conn = get_db()
            for k, v in body.items():
                conn.execute("INSERT INTO config(chave,valor) VALUES(?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (k, v))
            conn.commit()
            conn.close()
            resp_json(self, {'ok': True})

        elif path == '/api/pizza/nova':
            conn = get_db()
            conn.execute(
                "INSERT INTO pizzas(nome,descricao,preco,preco_broto,preco_media,preco_grande,tem_tamanho,categoria,ativa,imagem) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (body['nome'], body.get('descricao',''), body.get('preco',0),
                 body.get('preco_broto',0), body.get('preco_media',0), body.get('preco_grande',0),
                 body.get('tem_tamanho',0), body.get('categoria','Clássicas'), body.get('ativa',1),
                 body.get('imagem',''))
            )
            novo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            conn.close()
            resp_json(self, {'ok': True, 'id': novo_id})

        elif path == '/api/pizza/editar':
            conn = get_db()
            conn.execute(
                "UPDATE pizzas SET nome=?,descricao=?,preco=?,preco_broto=?,preco_media=?,preco_grande=?,tem_tamanho=?,categoria=?,ativa=?,imagem=? WHERE id=?",
                (body['nome'], body.get('descricao',''), body.get('preco',0),
                 body.get('preco_broto',0), body.get('preco_media',0), body.get('preco_grande',0),
                 body.get('tem_tamanho',0), body.get('categoria','Clássicas'), body.get('ativa',1),
                 body.get('imagem',''), body['id'])
            )
            conn.commit()
            conn.close()
            resp_json(self, {'ok': True})

        elif path == '/api/pizza/imagem':
            # Recebe imagem como base64 JSON: {id, base64, ext}
            pid  = body.get('id')
            b64  = body.get('base64','')
            ext  = body.get('ext','jpg').lower().lstrip('.')
            if not pid or not b64:
                resp_json(self, {'ok': False, 'erro': 'id e base64 obrigatórios'}); return
            import base64 as _b64
            dados = _b64.b64decode(b64.split(',')[-1])  # remove data:image/...;base64, prefix
            ts    = int(time.time())
            fname = f'pizza_{pid}_{ts}.{ext}'
            # Remove imagem anterior deste produto
            conn  = get_db()
            old_img = conn.execute("SELECT imagem FROM pizzas WHERE id=?", (pid,)).fetchone()
            if old_img and old_img[0]:
                old_path = os.path.join(IMGS_DIR, old_img[0])
                try: os.remove(old_path)
                except: pass
            fpath = os.path.join(IMGS_DIR, fname)
            open(fpath, 'wb').write(dados)
            conn.execute("UPDATE pizzas SET imagem=? WHERE id=?", (fname, pid))
            conn.commit()
            conn.close()
            resp_json(self, {'ok': True, 'imagem': fname})

        elif path == '/api/bairro/novo':
            try:
                conn = get_db()
                conn.execute("INSERT INTO bairros(nome,taxa) VALUES(?,?)",
                             (body.get('nome','').strip(), float(body.get('taxa',0))))
                novo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.commit()
                bairro = dict(conn.execute("SELECT * FROM bairros WHERE id=?", (novo_id,)).fetchone())
                conn.close()
                resp_json(self, {'ok': True, 'bairro': bairro})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/bairro/editar':
            try:
                conn = get_db()
                conn.execute("UPDATE bairros SET nome=?, taxa=? WHERE id=?",
                             (body.get('nome','').strip(), float(body.get('taxa',0)), body.get('id')))
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/bairros/deletar-todos':
            conn = get_db()
            conn.execute("DELETE FROM bairros")
            conn.commit(); conn.close()
            resp_json(self, {'ok': True})

        elif path == '/api/bairro/deletar':
            try:
                conn = get_db()
                conn.execute("DELETE FROM bairros WHERE id=?", (body.get('id'),))
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/pedidos/limpar':
            try:
                conn = get_db()
                apagados = conn.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0]
                conn.execute("DELETE FROM pedidos")
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True, 'apagados': apagados})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/login':
            usuario = body.get('usuario', '').strip()
            senha   = body.get('senha', '')
            if not usuario or not senha:
                resp_json(self, {'ok': False, 'erro': 'Usuário e senha obrigatórios'}, 400)
                return
            conn = get_db()
            row  = conn.execute(
                "SELECT id FROM usuarios WHERE usuario=? AND senha=?",
                (usuario, senha)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE usuarios SET ultimo_acesso=datetime('now','localtime') WHERE id=?",
                    (row['id'],)
                )
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True})
            else:
                conn.close()
                resp_json(self, {'ok': False, 'erro': 'Usuário ou senha incorretos'}, 401)

        elif path == '/api/usuario/trocar-senha':
            senha_atual   = body.get('senha_atual', '')
            novo_usuario  = body.get('novo_usuario', '').strip()
            nova_senha    = body.get('nova_senha', '')
            if not senha_atual or not novo_usuario or not nova_senha:
                resp_json(self, {'ok': False, 'erro': 'Todos os campos são obrigatórios'}, 400)
                return
            if len(novo_usuario) < 3:
                resp_json(self, {'ok': False, 'erro': 'Usuário deve ter no mínimo 3 caracteres'}, 400)
                return
            conn = get_db()
            row  = conn.execute(
                "SELECT id FROM usuarios WHERE senha=?", (senha_atual,)
            ).fetchone()
            if not row:
                conn.close()
                resp_json(self, {'ok': False, 'erro': 'Senha atual incorreta'}, 401)
                return
            try:
                conn.execute(
                    "UPDATE usuarios SET usuario=?, senha=?, ultimo_acesso=datetime('now','localtime') WHERE id=?",
                    (novo_usuario, nova_senha, row['id'])
                )
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True})
            except sqlite3.IntegrityError:
                conn.close()
                resp_json(self, {'ok': False, 'erro': 'Este usuário já existe'}, 409)

        elif path == '/api/pizza/imagem-url':
            pid  = body.get('id')
            iurl = body.get('url','')
            if not pid or not iurl:
                resp_json(self, {'ok': False, 'erro': 'id e url obrigatórios'}); return
            try:
                req = urllib.request.Request(iurl, headers={'User-Agent':'Mozilla/5.0','Accept':'image/*'})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    dados = resp.read()
                    ctype = resp.headers.get('Content-Type','image/jpeg')
                ext_map = {'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}
                ext   = ext_map.get(ctype.split(';')[0].strip(), 'jpg')
                ts    = int(time.time())
                fname = f'pizza_{pid}_{ts}.{ext}'
                conn  = get_db()
                old_img = conn.execute("SELECT imagem FROM pizzas WHERE id=?", (pid,)).fetchone()
                if old_img and old_img[0]:
                    try: os.remove(os.path.join(IMGS_DIR, old_img[0]))
                    except: pass
                fpath = os.path.join(IMGS_DIR, fname)
                open(fpath, 'wb').write(dados)
                conn.execute("UPDATE pizzas SET imagem=? WHERE id=?", (fname, pid))
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True, 'imagem': fname})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 502)

        elif path == '/api/mensagens-cliente/nova':
            try:
                conn = get_db()
                conn.execute(
                    "INSERT INTO mensagens_cliente (pedido_numero,pedido_itens,mensagem,nome_cliente) VALUES (?,?,?,?)",
                    (body.get('pedido_numero',''), body.get('pedido_itens',''),
                     body.get('mensagem',''), body.get('nome_cliente','Cliente'))
                )
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/mensagens-motoboy/nova':
            try:
                conn = get_db()
                conn.execute(
                    "INSERT INTO mensagens_motoboy (pedido_numero,mensagem,nome_cliente) VALUES (?,?,?)",
                    (body.get('pedido_numero','MOTOBOY'),
                     body.get('mensagem',''),
                     body.get('nome_cliente','🛵 Motoboy'))
                )
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True})
            except Exception as ex:
                import traceback
                print(f'[ERRO mensagens-motoboy/nova] {traceback.format_exc()}', flush=True)
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/mensagens-cliente/excluir':
            try:
                conn = get_db()
                conn.execute("DELETE FROM mensagens_cliente WHERE id=?", (body.get('id'),))
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/mensagens-motoboy/excluir':
            try:
                conn = get_db()
                conn.execute("DELETE FROM mensagens_motoboy WHERE id=?", (body.get('id'),))
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/caixa/novo':
            try:
                conn = get_db()
                conn.execute(
                    "INSERT INTO caixa (tipo,valor,categoria,descricao,forma_pagto,data,auto) VALUES (?,?,?,?,?,?,?)",
                    (body.get('tipo','entrada'), body.get('valor',0), body.get('categoria',''),
                     body.get('descricao',''), body.get('forma_pagto','Dinheiro'),
                     body.get('data', ''), 1 if body.get('auto') else 0)
                )
                conn.commit()
                row = conn.execute("SELECT last_insert_rowid() as id").fetchone()
                conn.close()
                resp_json(self, {'ok': True, 'id': row['id']})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/caixa/editar':
            try:
                conn = get_db()
                conn.execute(
                    "UPDATE caixa SET tipo=?,valor=?,categoria=?,descricao=?,forma_pagto=?,data=? WHERE id=?",
                    (body.get('tipo','entrada'), body.get('valor',0), body.get('categoria',''),
                     body.get('descricao',''), body.get('forma_pagto','Dinheiro'),
                     body.get('data',''), body.get('id'))
                )
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/caixa/excluir':
            try:
                conn = get_db()
                conn.execute("DELETE FROM caixa WHERE id=?", (body.get('id'),))
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/comanda/abrir':
            # Cria comanda nova para a mesa (4 dígitos únicos)
            try:
                conn  = get_db()
                mesa  = body.get('mesa','')
                if not mesa:
                    resp_json(self, {'ok': False, 'erro': 'mesa obrigatória'}); conn.close(); return
                # Verifica se já existe comanda aberta para essa mesa
                existe = conn.execute(
                    "SELECT numero FROM comandas WHERE mesa=? AND status='aberta'", (mesa,)
                ).fetchone()
                if existe:
                    conn.close()
                    resp_json(self, {'ok': True, 'numero': existe['numero'], 'existia': True})
                    return
                # Gera número único de 4 dígitos (diferente do anterior dessa mesa)
                import random as _rnd
                ultima_cmd = conn.execute("SELECT numero FROM comandas WHERE mesa=? ORDER BY id DESC LIMIT 1", (mesa,)).fetchone()
                ultimo_num = ultima_cmd['numero'] if ultima_cmd else None

                for _ in range(100):
                    num = str(_rnd.randint(1000, 9999))
                    if num == ultimo_num: continue
                    dup = conn.execute("SELECT id FROM comandas WHERE numero=? AND status='aberta'", (num,)).fetchone()
                    if not dup: break
                conn.execute("INSERT INTO comandas (numero, mesa) VALUES (?,?)", (num, mesa))
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True, 'numero': num})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/comanda/fechar':
            # Fecha comanda, dá baixa no estoque via receitas, e retorna resumo de consumo
            try:
                conn   = get_db()
                numero = body.get('numero','')
                # Pega a comanda aberta mais recente com este número
                cmd    = conn.execute("SELECT * FROM comandas WHERE numero=? AND status='aberta' ORDER BY id DESC LIMIT 1", (numero,)).fetchone()
                if not cmd:
                    # Fallback para a última fechada se não houver aberta
                    cmd = conn.execute("SELECT * FROM comandas WHERE numero=? ORDER BY id DESC LIMIT 1", (numero,)).fetchone()
                
                if not cmd:
                    conn.close(); resp_json(self, {'ok': False, 'erro': 'Comanda não encontrada'}); return
                cmd = dict(cmd)
                # Busca todos os pedidos da comanda
                # Busca por comanda_numero (novo) com fallback legado
                pedidos = conn.execute(
                    "SELECT * FROM pedidos WHERE comanda_numero=?", (numero,)
                ).fetchall()
                if not pedidos:
                    pedidos = conn.execute(
                        "SELECT * FROM pedidos WHERE mesa=? AND criado_em >= ?",
                        (cmd['mesa'], cmd['criado_em'])
                    ).fetchall()
                # Agrega itens consumidos
                consumo_itens = {}  # pizza_id -> {nome, qtd}
                for p in pedidos:
                    itens = json.loads(p['itens_json'] or '[]')
                    for it in itens:
                        pid = it.get('id')
                        if not pid: continue
                        if pid not in consumo_itens:
                            consumo_itens[pid] = {'nome': it.get('nome',''), 'qtd': 0}
                        consumo_itens[pid]['qtd'] += it.get('qtd', 1)
                # Dá baixa no estoque via receitas
                baixas = []
                for pizza_id, info in consumo_itens.items():
                    receitas = conn.execute(
                        "SELECT r.*, p.nome as prod_nome, p.unidade FROM receitas r JOIN estoque_produtos p ON p.id=r.produto_id WHERE r.pizza_id=?",
                        (pizza_id,)
                    ).fetchall()
                    for rec in receitas:
                        rec = dict(rec)
                        qtd_baixa = rec['quantidade'] * info['qtd']
                        conn.execute(
                            "UPDATE estoque_produtos SET quantidade = quantidade - ? WHERE id=?",
                            (qtd_baixa, rec['produto_id'])
                        )
                        conn.execute(
                            "INSERT INTO estoque_historico (produto_id, tipo, quantidade, observacao) VALUES (?,?,?,?)",
                            (rec['produto_id'], 'saida', qtd_baixa, f"Comanda {numero} — {info['nome']} x{info['qtd']}")
                        )
                        baixas.append({'produto': rec['prod_nome'], 'unidade': rec['unidade'], 'quantidade': qtd_baixa})
                # Fecha comanda (apenas se estiver aberta)
                conn.execute("UPDATE comandas SET status='fechada' WHERE numero=? AND status='aberta' AND id=?", (numero, cmd['id']))
                conn.commit()
                conn.close()
                resp_json(self, {'ok': True, 'baixas': baixas, 'consumo': list(consumo_itens.values())})
            except Exception as ex:
                import traceback; print(f'[ERRO comanda/fechar] {traceback.format_exc()}', flush=True)
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/estoque/produto/novo':
            try:
                conn = get_db()
                conn.execute(
                    "INSERT INTO estoque_produtos (nome,unidade,quantidade,minimo,custo,categoria) VALUES (?,?,?,?,?,?)",
                    (body.get('nome',''), body.get('unidade','g'), body.get('quantidade',0),
                     body.get('minimo',0), body.get('custo',0), body.get('categoria','Ingrediente'))
                )
                conn.commit()
                row = conn.execute("SELECT last_insert_rowid() as id").fetchone()
                conn.close()
                resp_json(self, {'ok': True, 'id': row['id']})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/estoque/produto/editar':
            try:
                conn = get_db()
                conn.execute(
                    "UPDATE estoque_produtos SET nome=?,unidade=?,quantidade=?,minimo=?,custo=?,categoria=? WHERE id=?",
                    (body.get('nome',''), body.get('unidade','g'), body.get('quantidade',0),
                     body.get('minimo',0), body.get('custo',0), body.get('categoria','Ingrediente'), body.get('id'))
                )
                conn.commit(); conn.close()
                resp_json(self, {'ok': True})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/receita/salvar':
            # Salva ou atualiza ingrediente de uma receita
            try:
                conn = get_db()
                conn.execute(
                    "INSERT INTO receitas (pizza_id, produto_id, quantidade) VALUES (?,?,?) ON CONFLICT(pizza_id,produto_id) DO UPDATE SET quantidade=excluded.quantidade",
                    (body.get('pizza_id'), body.get('produto_id'), body.get('quantidade', 0))
                )
                conn.commit(); conn.close()
                resp_json(self, {'ok': True})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        elif path == '/api/receita/excluir':
            try:
                conn = get_db()
                conn.execute("DELETE FROM receitas WHERE pizza_id=? AND produto_id=?",
                    (body.get('pizza_id'), body.get('produto_id')))
                conn.commit(); conn.close()
                resp_json(self, {'ok': True})
            except Exception as ex:
                resp_json(self, {'ok': False, 'erro': str(ex)}, 500)

        else:
            self.send_response(404)
            self.end_headers()

# ── Polling simples (substitui WebSocket) ─────────────────────────
# As páginas fazem GET /api/pedidos a cada 3s — simples e confiável

# ── Tray ──────────────────────────────────────────────────────────
def iniciar_servidor():
    import socket as _socket
    servidor = HTTPServer(('0.0.0.0', PORT), Handler)
    servidor.socket.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    print('✅ Servidor rodando em http://localhost:{}/admin'.format(PORT))
    servidor.serve_forever()

def abrir_admin():
    webbrowser.open(f'http://localhost:{PORT}/admin')

def criar_tray():
    try:
        import pystray
        from PIL import Image, ImageDraw

        # Cria ícone vermelho simples
        img = Image.new('RGB', (64, 64), color='#D62828')
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 56, 56], fill='#FF6B6B')
        draw.text((20, 20), '🍕', fill='white')

        ip = get_ip()
        menu = pystray.Menu(
            pystray.MenuItem('⚙️  Abrir Admin',         lambda: abrir_admin()),
            pystray.MenuItem('📺 Abrir Cozinha',         lambda: webbrowser.open(f'http://localhost:{PORT}/cozinha')),
            pystray.MenuItem('📱 Cardápio (clientes)',   lambda: webbrowser.open(f'http://localhost:{PORT}/pedido')),
            pystray.MenuItem('📋 QR Codes das mesas',    lambda: webbrowser.open(f'http://localhost:{PORT}/qr')),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f'🌐 IP: {ip}:{PORT}',      None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('❌ Encerrar',              lambda icon, _: icon.stop()),
        )
        icon = pystray.Icon('Pizzaria', img, f'Pizzaria — {ip}:{PORT}', menu)
        icon.run()

    except ImportError:
        # pystray não instalado — roda só o servidor
        print('pystray não encontrado. Rodando sem ícone na bandeja.')
        print(f'Acesse: http://localhost:{PORT}/admin')
        try:
            input('Pressione Enter para encerrar...\n')
        except:
            threading.Event().wait()

# ── Main ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f'Pizzaria Cloud rodando na porta {PORT}')
    iniciar_servidor()
